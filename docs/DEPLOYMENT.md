# VPS deployment

What this deploys, precisely: **the whole system, with the trading engine
switched off**. The brain, the risk layer and the execution engine all exist
now, and every one of their switches defaults to refusing - execution
disabled, dry-run on, autopilot halted, kill switch engaged. Nothing trades
until somebody decides it should, deliberately, more than once.

(This page used to say those layers did not exist. They were built; the
sentence was not updated, which is the ordinary way a deployment document
starts lying.)

What it does from the first minute is accumulate real market history and
features, so the measurement that has not yet found an edge has more to work
with tomorrow than it did today.

## The short way

On a **fresh** Ubuntu 22.04 or 24.04 server, as root:

```bash
DOMAIN=trade.molido.shop TLS_MODE=internal TRUSTED_PROXY_HOPS=2 bash infra/provision.sh
```

That installs Docker, clones the project, generates a database password it
never prints, configures the firewall and fail2ban, starts everything, seeds
the market calendar and schedules the nightly verified backup. It is
idempotent - the second run changes nothing.

`TLS_MODE` and `TRUSTED_PROXY_HOPS` are facts about the network in front of
the machine, not preferences. See **Behind a CDN** below; the values above are
for `trade.molido.shop`, which sits behind ArvanCloud.

The rest of this page is what that script does, in case it has to be done or
undone by hand.

## Behind a CDN

`trade.molido.shop` resolves to ArvanCloud, not to the server. Three things
follow, and getting any of them wrong is quiet rather than loud:

**TLS.** Caddy cannot complete a Let's Encrypt HTTP-01 challenge from behind a
CDN unless the CDN passes `/.well-known/acme-challenge/` through to the origin.
A certificate that issues once and then cannot renew is a site that goes dark
sixty days later, on a day nobody is looking. `TLS_MODE=internal` avoids the
question: Caddy serves a self-signed certificate, the CDN terminates public
TLS, and the origin link is still encrypted. Set the CDN's origin mode to its
permissive HTTPS setting - ArvanCloud and Cloudflare both call it "full",
as distinct from "full (strict)".

**The caller's address.** `MOLIDO_TRUSTED_PROXY_HOPS` must be **2** here: the
CDN, then Caddy. The sign-in rate limiter counts failures per caller address.
Set too low, every request appears to come from the CDN and the whole world
shares one bucket - the first fifteen failed logins anywhere lock out
everybody. Set too high, the address counted is one the caller wrote in a
header, which is no limit at all while looking exactly like one.

**Denial of service.** The CDN is the layer that can absorb it. Nothing in
this application can, and nothing in it pretends to.

## What runs

| Service | Role |
| --- | --- |
| `caddy` | TLS termination, reverse proxy. The only service with host ports. |
| `web` | Next.js dashboard |
| `api` | FastAPI, read-only endpoints |
| `collector` | Long-running worker: ingest → quality → features, every 15 min |
| `postgres` | TimescaleDB. **No host port** — reachable only inside the network |
| `redis` | Queue/scheduler backend. Also no host port |
| `migrate` | Runs once, applies migrations, exits. Everything waits on it |

## Server requirements

- 2 vCPU / 4 GB RAM / 40 GB SSD is comfortable for the current watchlist.
  Postgres and the collector are the memory consumers; the API is idle.
- Ubuntu 22.04 or 24.04, Docker Engine with the compose plugin.
- A domain pointed at the server's IP (an A record). Caddy needs it resolving
  **before** first start or certificate issuance fails.

## First deployment

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
```

```bash
sudo mkdir -p /opt/molidotrade && sudo chown "$USER" /opt/molidotrade
```

Copy the project to `/opt/molidotrade` (git clone, rsync, or scp), then:

```bash
cp /opt/molidotrade/infra/.env.prod.example /opt/molidotrade/infra/.env.prod
```

Edit `infra/.env.prod` — set `DOMAIN`, `ACME_EMAIL`, and a real password:

```bash
openssl rand -base64 32
```

```bash
cd /opt/molidotrade && docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build
```

The first build takes several minutes. `migrate` runs to completion before the
API and collector start, so a partial schema can never be served.

## Verify — do not skip this

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod ps
```

Every service should be `running`, `migrate` should be `exited (0)`.

```bash
curl -s https://YOUR_DOMAIN/health/ready
```

Expect `"status":"ok"` with both dependencies healthy. A 503 means a dependency
is down — the response names which.

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod logs -f collector
```

Within a minute or two you should see `collector.backfilling`, then
`ingestion.completed` with a bar count, then `features.materialized`. The first
cycle backfills history (up to ~680 days of H1 per instrument) and takes a
while; later cycles are seconds.

```bash
curl -s https://YOUR_DOMAIN/api/v1/instruments
```

The watchlist instruments should appear. If the list is empty after two cycles,
read the collector log — the failure will be named there, per symbol.

## Load the holiday calendar

Gap detection is only as good as the calendar behind it:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod exec api python -m app.cli seed-holidays
```

Only unambiguous closures are seeded. Venue-specific holidays must come from a
source you trust — a wrong holiday entry silently excuses a real outage.

## Backups

```bash
chmod +x /opt/molidotrade/infra/backup.sh
```

```bash
crontab -e
```

Add:

```
15 3 * * * /opt/molidotrade/infra/backup.sh >> /var/log/molido-backup.log 2>&1
```

The script dumps, then **restores the dump into a scratch database and counts
rows** before declaring success. An unverified dump is not a backup.

Run it once by hand before trusting the schedule.

## Updating

```bash
cd /opt/molidotrade && git pull && docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build
```

Migrations run automatically. To roll a migration back:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod run --rm migrate alembic downgrade -1
```

## Firewall

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

Postgres and Redis publish no host ports, so this is belt and braces — but on a
public IP, wear both.

## Security status — read before exposing this publicly

**There is no authentication.** Every endpoint is read-only and nothing mutates
state, so the exposure is disclosure of your own market data and system health,
not takeover. Even so:

- Restrict the host by IP, or put Caddy behind basic auth, if the deployment is
  not meant to be public.
- Do not add a mutating endpoint, a broker credential, or an execution path to
  this deployment until auth and RBAC ship. That ordering is recorded in
  `docs/PHASES.md` and is not a formality — an execution endpoint without auth
  on a public host is a wallet with the door open.

## Operating notes

- **Closed markets are skipped, not polled.** Idle collector logs at the
  weekend are correct behaviour for FX, not a fault. Crypto keeps collecting.
- **Restarts are safe at any moment.** Ingestion is idempotent per window and
  features are skipped when present, so a kill during a cycle costs one chunk.
- **Rate limiting looks like silence.** If bar counts drop to zero on a weekday,
  suspect the provider before the code, and raise
  `MOLIDO_COLLECTOR_INTERVAL_SECONDS` rather than lowering it.
- **Disk grows with history.** One H1 instrument is a few MB per year; ticks are
  not collected. Compression kicks in after 180 days automatically.
