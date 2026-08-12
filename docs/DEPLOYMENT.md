# VPS deployment

What this deploys, precisely: the **data layer and the collector**. The
cognitive brain, risk brain and execution engine do not exist yet (phases 14+),
so nothing here trades, and nothing here can. What it does do is start
accumulating real market history and features immediately, so those later
phases inherit years of data instead of an empty database.

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
