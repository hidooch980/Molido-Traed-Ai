#!/usr/bin/env bash
#
# Bring the site back when the origin's HTTPS has stopped answering.
#
# Written on 22 September 2026, when trade.molido.shop had been returning 503
# ("upstream connect error ... connection timeout") from the CDN while the
# origin itself was healthy: Caddy answered on port 80 and reset every
# connection on 443. The bot kept trading and reporting to Telegram the whole
# time - only the site was gone, which also took the kill switch and every
# settings page with it.
#
# `provision.sh` names the cause in its own output, under the letsencrypt
# mode it was deployed with:
#
#     This needs the ACME challenge to reach this machine. Behind a CDN,
#     check that /.well-known/acme-challenge/ is passed through to the
#     origin - if it is not, the first renewal fails silently in sixty days.
#
# That is a deadlock once it happens: the certificate expires, 443 stops
# serving, the CDN can no longer reach the origin, and the HTTP-01 challenge
# that would renew the certificate now 503s too. Nothing breaks it from the
# outside.
#
# So this switches the origin to the mode `provision.sh` documents for a
# machine behind a CDN - a self-signed certificate that never has to renew,
# with the CDN's origin protocol set to HTTPS in its permissive mode
# ("full", not "full strict"). The link stays encrypted and the renewal
# problem stops existing.
#
# It diagnoses first and prints what it found, then stops and waits, so a
# reading that contradicts the diagnosis above can be carried out of here
# instead of acted on. Nothing is changed before that pause.
#
# Usage, from any shell on the server (a panel's web console is enough):
#
#     curl -fsSL https://raw.githubusercontent.com/hidooch980/Molido-Traed-Ai/claude/status-d7a1df/infra/recover.sh -o /tmp/recover.sh
#     sudo bash /tmp/recover.sh
#
set -uo pipefail

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }

# ------------------------------------------------------------------ the repo
#
# Searched for rather than assumed: whoever is running this is likely doing it
# from a rescue console, on a machine they have not logged into in weeks, and
# "cd to the project root" is the step that stalls.
say "finding the project"
APP_DIR=""
for candidate in /root/Molido-Traed-Ai /opt/Molido-Traed-Ai /home/*/Molido-Traed-Ai "$PWD"; do
  if [ -f "${candidate}/infra/docker-compose.prod.yml" ]; then
    APP_DIR="$candidate"
    break
  fi
done
if [ -z "$APP_DIR" ]; then
  APP_DIR="$(find / -maxdepth 6 -name docker-compose.prod.yml -path '*/infra/*' 2>/dev/null \
    | head -1 | xargs -r dirname | xargs -r dirname)"
fi
if [ -z "$APP_DIR" ] || [ ! -f "${APP_DIR}/infra/docker-compose.prod.yml" ]; then
  echo "!! could not find the project on this machine."
  echo "   Look for it by hand:  find / -name docker-compose.prod.yml 2>/dev/null"
  exit 1
fi
cd "$APP_DIR"
note "found: ${APP_DIR}"

ENV_FILE="infra/.env.prod"
if [ ! -f "$ENV_FILE" ]; then
  echo "!! ${APP_DIR}/${ENV_FILE} is missing. Nothing here can run without it."
  exit 1
fi

compose() {
  sudo docker compose -f infra/docker-compose.prod.yml --env-file "$ENV_FILE" "$@"
}

# Read before the diagnosis, because the health checks below have to ask for
# the site by name: Caddy serves one site block, for this domain, and a
# request addressed to 127.0.0.1 does not match it. `--resolve` sends the
# right name to the local machine.
DOMAIN_VALUE="$(grep -E '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"
if [ -z "$DOMAIN_VALUE" ]; then
  echo "!! DOMAIN is not set in ${ENV_FILE}. Nothing here can be checked by name."
  exit 1
fi
note "domain: ${DOMAIN_VALUE}"

# Asked of this machine, by the site's own name, so Caddy answers as it would
# for the CDN. -k because a self-signed certificate is a correct answer here;
# the question is whether a handshake completes at all.
probe_https() {
  curl -sS -k --max-time 10 --resolve "${DOMAIN_VALUE}:443:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "https://${DOMAIN_VALUE}/health/live" 2>/dev/null
}
probe_http() {
  curl -sS --max-time 10 --resolve "${DOMAIN_VALUE}:80:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "http://${DOMAIN_VALUE}/health/live" 2>/dev/null
}

# ------------------------------------------------------------------ diagnosis
#
# Printed in full before anything is touched. If the site is down for a reason
# other than the certificate, it shows up here and this script is the wrong
# tool - stop at the pause below and send this output on.
say "containers"
compose ps --format '{{.Name}}\t{{.State}}\t{{.Status}}' 2>/dev/null || sudo docker ps

say "how TLS is configured now"
# Only these three lines. The rest of the file is passwords and tokens.
grep -E '^(DOMAIN|SITE_ADDRESS|CADDY_TLS)=' "$ENV_FILE" || note "(none set - SITE_ADDRESS defaults to DOMAIN, CADDY_TLS to empty)"

say "what Caddy has been saying"
compose logs caddy --tail 40 2>/dev/null | tail -40 || note "(no caddy logs)"

say "does the origin answer, from the machine itself"
# 000 is curl for "nothing completed" - which is the symptom being chased, so
# it is reported as itself rather than as an error.
note "https -> $(probe_https)   (000 = no handshake: the symptom)"
note "http  -> $(probe_http)"

say "is the bot still trading"
# Independent of Caddy, and the thing that actually matters. A cycle that ran
# in the last hour means the outage never touched the trading loop.
compose logs collector --tail 12 2>/dev/null | tail -12 || note "(no collector logs)"

# --------------------------------------------------------------------- pause
say "read the above before going on"
cat <<'EXPLAIN'
   The fix this script applies, if the picture matches:

     CADDY_TLS="tls internal"   - a self-signed certificate that never
                                  has to renew, which is what provision.sh
                                  documents for an origin behind a CDN

   Nothing else is touched. infra/.env.prod is backed up first, and only the
   caddy container is recreated - the collector keeps trading through it.

   AFTERWARDS, in the ArvanCloud panel, the origin protocol has to be HTTPS
   in its permissive mode - "full", NOT "full strict". A self-signed
   certificate fails strict mode, and the site stays down.

   Press ENTER to apply it, or Ctrl-C to stop here and take the output above
   to someone first.
EXPLAIN
read -r _ < /dev/tty

# ----------------------------------------------------------------------- fix
say "backing up the environment file"
BACKUP="${ENV_FILE}.bak-recover-$(date -u +%Y%m%d-%H%M%S)"
cp -a "$ENV_FILE" "$BACKUP"
note "saved: ${APP_DIR}/${BACKUP}"
note "to undo everything this script did:"
note "  cd ${APP_DIR} && cp -a ${BACKUP} ${ENV_FILE} && sudo docker compose -f infra/docker-compose.prod.yml --env-file ${ENV_FILE} up -d --force-recreate caddy"

say "switching the origin to a self-signed certificate"
# Replaced rather than appended, the same way provision.sh does it: two lines
# for one setting leaves the file to decide which one wins.
sed -i '/^SITE_ADDRESS=/d; /^CADDY_TLS=/d' "$ENV_FILE"
{
  echo "SITE_ADDRESS=${DOMAIN_VALUE}"
  echo "CADDY_TLS=tls internal"
} >> "$ENV_FILE"
grep -E '^(DOMAIN|SITE_ADDRESS|CADDY_TLS)=' "$ENV_FILE"

say "recreating caddy only"
# Only caddy. `deploy.sh` would rebuild and restart the collector too, and the
# trading cycle is the one thing here that is still working.
compose up -d --force-recreate caddy

say "waiting for it to come up"
sleep 8

say "does the origin answer on 443 now"
OK=0
for _ in 1 2 3 4 5; do
  CODE="$(probe_https)"
  if [ "${CODE:-000}" = "200" ]; then OK=1; break; fi
  sleep 4
done
if [ "$OK" = "1" ]; then
  note "local https -> HTTP 200. The origin is serving again."
  echo
  echo "   NEXT, and the site stays down without it:"
  echo "   ArvanCloud panel -> the origin protocol for ${DOMAIN_VALUE} must be"
  echo "   HTTPS in the permissive mode (\"full\", not \"full strict\")."
  echo
  echo "   Then open https://${DOMAIN_VALUE} - the footer names the build and"
  echo "   commit that is running, which is how to tell what is deployed."
else
  note "local https still not answering (last code: ${CODE:-none})."
  note "Send the caddy logs on:  sudo docker compose -f infra/docker-compose.prod.yml --env-file ${ENV_FILE} logs caddy --tail 60"
  note "The environment file is unchanged from before except the two TLS lines, and ${BACKUP} restores it."
  exit 1
fi

# -------------------------------------------------------------------- deploy
say "deploying the merged code"
cat <<'EXPLAIN'
   The site is serving again. The code on this machine is still whatever was
   last deployed - PR #23 (the prop correlation caps, the per-account symbol
   list, self-service trailing) is merged on main but not running here.

   Press ENTER to run ./infra/deploy.sh, or Ctrl-C to stop and do it later.
   Deploying restarts the collector, so the trading cycle pauses for about a
   minute.
EXPLAIN
read -r _ < /dev/tty
./infra/deploy.sh
