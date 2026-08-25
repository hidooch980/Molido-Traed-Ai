#!/usr/bin/env bash
#
# Turn a fresh Ubuntu server into this deployment, in one command.
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/infra/provision.sh | bash
# or, once the repository is on the machine:
#   sudo bash infra/provision.sh
#
# `deploy.sh` updates a deployment that already exists. This creates one.
# Everything it does is idempotent: run it twice and the second run changes
# nothing, which matters because the first run is the one most likely to be
# interrupted.
#
# It does NOT wipe anything. A server that has to be cleared should be
# reinstalled from the provider's panel instead - that is a real wipe, it
# cannot half-succeed, and it leaves nothing behind for this script to trip
# over. A shell script deleting a running system's files is the version of
# "clean" that ends with a machine that neither boots nor serves.
#
# So this refuses to run if something is already serving on 80 or 443 that it
# did not put there. Override with FORCE=1 only after looking at what that is.

set -euo pipefail

REPO="${REPO:-https://github.com/hidooch980/Molido-Traed-Ai.git}"
TARGET="${TARGET:-/opt/molidotrade}"
BRANCH="${BRANCH:-main}"

# The public hostname. Every certificate decision below depends on it.
DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"

# How TLS is terminated, which is a fact about the network in front of this
# server rather than a preference:
#
#   letsencrypt  Caddy obtains its own certificate. Correct when the DNS
#                record points straight here. Behind a CDN it needs the
#                ACME challenge to be passed through to the origin, which
#                not every CDN does - and a failed renewal in sixty days
#                is a site that goes dark on a Tuesday.
#   internal     Caddy serves a self-signed certificate. Correct behind a
#                CDN that terminates TLS itself and connects to the origin
#                over HTTPS without demanding a public certificate
#                (ArvanCloud and Cloudflare both call this "full"). The
#                origin link stays encrypted and nothing expires.
#   http-only    Caddy serves plain HTTP on port 80. The CDN terminates TLS
#                and talks to the origin unencrypted. Simplest, and the
#                traffic between the CDN and this machine is readable by
#                anything on the path. Use only if the other two cannot.
TLS_MODE="${TLS_MODE:-internal}"

# How many proxies sit in front. Read by the sign-in rate limiter, which
# counts failures per caller address - so an address the caller can choose is
# not a limit. 0 direct, 1 behind Caddy alone, 2 behind a CDN and Caddy.
TRUSTED_PROXY_HOPS="${TRUSTED_PROXY_HOPS:-2}"

say() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo bash infra/provision.sh)"
[ -n "$DOMAIN" ] || die "set DOMAIN, e.g. DOMAIN=trade.molido.shop bash infra/provision.sh"

case "$TLS_MODE" in
  letsencrypt) [ -n "$ACME_EMAIL" ] || die "TLS_MODE=letsencrypt needs ACME_EMAIL" ;;
  internal|http-only) ;;
  *) die "TLS_MODE must be letsencrypt, internal or http-only" ;;
esac

say "checking what is already here"
if [ "${FORCE:-0}" != "1" ] && [ ! -d "$TARGET" ]; then
  # `ss` is in iproute2, which Ubuntu has by default.
  if ss -ltn 2>/dev/null | grep -qE ':(80|443)\s'; then
    printf 'Something is already serving on port 80 or 443:\n\n' >&2
    ss -ltnp 2>/dev/null | grep -E ':(80|443)\s' >&2 || true
    printf '\nThis script will not displace it. Either stop it, or reinstall\n' >&2
    printf 'the OS from the provider panel for a real clean start, or set\n' >&2
    printf 'FORCE=1 once you know what that service is.\n' >&2
    exit 1
  fi
fi

say "installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl git ufw fail2ban openssl \
  docker.io docker-compose-v2 cloud-guest-utils parted >/dev/null
systemctl enable --now docker >/dev/null 2>&1 || true

say "fetching the project into $TARGET"
if [ -d "$TARGET/.git" ]; then
  git -C "$TARGET" fetch --quiet origin "$BRANCH"
  git -C "$TARGET" checkout --quiet "$BRANCH"
  git -C "$TARGET" reset --hard --quiet "origin/$BRANCH"
else
  mkdir -p "$(dirname "$TARGET")"
  git clone --quiet --branch "$BRANCH" "$REPO" "$TARGET"
fi
cd "$TARGET"

say "writing infra/.env.prod"
ENV_FILE="infra/.env.prod"
if [ -f "$ENV_FILE" ]; then
  echo "-> already exists, left alone (delete it to regenerate)"
else
  # Generated here and never printed. A password this script echoes is a
  # password in a terminal scrollback, a screen recording and a support chat.
  POSTGRES_PASSWORD="$(openssl rand -base64 32 | tr -d '\n/+=' | head -c 40)"
  cp infra/.env.prod.example "$ENV_FILE"
  sed -i "s|^DOMAIN=.*|DOMAIN=${DOMAIN}|" "$ENV_FILE"
  sed -i "s|^ACME_EMAIL=.*|ACME_EMAIL=${ACME_EMAIL:-admin@${DOMAIN}}|" "$ENV_FILE"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "-> generated, mode 600, not in git"
fi

# Set on every run, not only on the first. These three describe the network in
# front of the machine, and that is exactly the thing somebody re-runs this
# script to correct - a value written once and then skipped forever would mean
# fixing it by hand in the file the script claims to own.
say "recording the shape of the network in front"
sed -i '/^MOLIDO_TRUSTED_PROXY_HOPS=/d' "$ENV_FILE"
{
  echo ""
  echo "# How many proxies are in front. The sign-in limiter counts failures"
  echo "# per caller address; too low and every caller in the world shares one"
  echo "# bucket, too high and the address counted is one the caller wrote."
  echo "MOLIDO_TRUSTED_PROXY_HOPS=${TRUSTED_PROXY_HOPS}"
} >> "$ENV_FILE"
echo "-> ${TRUSTED_PROXY_HOPS} hop(s)"

say "configuring TLS for mode: $TLS_MODE"
# Written into .env.prod rather than into the Caddyfile, so a `git pull` never
# has to resolve a conflict against a local edit of a tracked file.
case "$TLS_MODE" in
  letsencrypt)
    SITE_ADDRESS="${DOMAIN}"
    CADDY_TLS=""
    echo "-> Caddy will request its own certificate for ${DOMAIN}"
    echo "   This needs the ACME challenge to reach this machine. Behind a CDN,"
    echo "   check that /.well-known/acme-challenge/ is passed through to the"
    echo "   origin - if it is not, the first renewal fails silently in sixty days."
    ;;
  internal)
    SITE_ADDRESS="${DOMAIN}"
    CADDY_TLS="tls internal"
    echo "-> Caddy will serve a self-signed certificate."
    echo "   Set the CDN's origin protocol to HTTPS in its permissive mode"
    echo "   (ArvanCloud and Cloudflare both call it 'full', not 'full strict')."
    echo "   The origin link stays encrypted and nothing ever has to renew."
    ;;
  http-only)
    SITE_ADDRESS="http://${DOMAIN}"
    CADDY_TLS=""
    echo "-> Caddy will serve plain HTTP on port 80."
    echo "   The link between the CDN and this machine is readable by anything"
    echo "   on the path. Use this only when the other two cannot work."
    ;;
esac

# Replaced rather than appended, so re-running with a different mode changes
# the mode instead of leaving two lines and letting the file decide.
sed -i '/^SITE_ADDRESS=/d; /^CADDY_TLS=/d' "$ENV_FILE"
{
  echo "SITE_ADDRESS=${SITE_ADDRESS}"
  echo "CADDY_TLS=${CADDY_TLS}"
} >> "$ENV_FILE"

say "firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "-> SSH, 80 and 443. Postgres and Redis publish no host ports at all."

say "fail2ban"
cat > /etc/fail2ban/jail.d/molido.conf <<'JAIL'
# SSH only. The application's own sign-in limiter lives in the database and
# knows things fail2ban cannot see from a log line - which account was tried,
# whether the caller is behind a CDN, and whether the attempt carried a proof
# of work. Two systems banning the same thing by different rules is how an
# operator ends up unable to explain why they are locked out.
[sshd]
enabled  = true
maxretry = 5
findtime = 10m
bantime  = 1h
JAIL
# `enable --now`, not `restart`. Restart alone starts it for this boot and
# leaves it disabled, so the jail is up until the machine reboots and then
# silently is not - and the first reboot is usually months later, unattended,
# on a host that is being scanned the whole time. This deployment shipped that
# way once and the reboot found it.
systemctl enable --now fail2ban || true
echo "-> sshd jail: 5 failures in 10 minutes, banned for an hour"
echo "   enabled, so it survives a reboot: $(systemctl is-enabled fail2ban 2>&1)"

say "building and starting"
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --build

say "waiting for the API to answer"
for _ in $(seq 1 60); do
  if curl -fsS -m 3 "http://127.0.0.1/health/ready" >/dev/null 2>&1; then
    echo "-> ready"
    break
  fi
  sleep 5
done

say "seeding the market calendar"
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod \
  exec -T api python -m app.cli seed-holidays || echo "-> skipped; run it by hand once the API is up"

say "nightly verified backup"
chmod +x infra/backup.sh
CRON_LINE="15 3 * * * ${TARGET}/infra/backup.sh >> /var/log/molido-backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'infra/backup.sh' ; echo "$CRON_LINE" ) | crontab -
echo "-> 03:15 daily. The script restores its own dump into a scratch database"
echo "   and counts rows before reporting success; an unverified dump is not a backup."

say "what survives a reboot"
# Asserted rather than assumed. Every one of these starts correctly on the day
# it is installed; the question is whether it comes back, and nothing asks that
# until something has already been down for a while.
for unit in docker containerd fail2ban ufw; do
  state="$(systemctl is-enabled "$unit" 2>&1 || true)"
  printf '  %-12s %s
' "$unit" "$state"
  case "$state" in
    enabled|enabled-runtime|static|alias) ;;
    *) echo "     ^ not enabled - it will not come back after a reboot" ;;
  esac
done
echo "  containers    restart: unless-stopped (declared in the compose file)"

say "done"
cat <<SUMMARY

  Deployment  ${TARGET}
  Domain      ${DOMAIN}
  TLS         ${TLS_MODE}
  Proxy hops  ${TRUSTED_PROXY_HOPS}

  State of the trading engine, which this does not change:

    execution disabled, dry-run on, autopilot halted, kill switch engaged.
    Nothing trades until somebody decides it should, on purpose, twice.

  Next, in a browser, not a terminal:

    https://${DOMAIN}/  ->  the first person to claim the deployment
                            becomes its owner and holds every permission.
                            Nobody can claim it twice.

  Check on it with:

    docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod ps
    docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod logs -f collector

SUMMARY
