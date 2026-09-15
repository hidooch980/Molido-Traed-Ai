#!/bin/bash
# Restart a container Docker itself reports unhealthy, and say so on Telegram.
#
# `restart: unless-stopped` brings back a container that exits, but not one
# that is running and failing its healthcheck: Docker marks it "unhealthy"
# and leaves it there. Nothing on this host acted on that mark, so a hung
# collector read as "up" until somebody looked.
#
# Narrow on purpose: only containers of this project, only the "unhealthy"
# state (never "starting"), and at most one restart per container per hour -
# a container that is unhealthy again right after a restart has a fault a
# restart does not fix, and restarting it forever would hide the evidence.
# That case alerts instead.

set -uo pipefail

PROJECT=${COMPOSE_PROJECT_NAME:-molidotrade}
STATE_DIR=${STATE_DIR:-/var/lib/molido/autoheal}
LOG=${LOG:-/var/log/molido-autoheal.log}
COOLDOWN_SECONDS=${COOLDOWN_SECONDS:-3600}
DOCKER=${DOCKER:-docker}
NOW=${NOW:-$(date +%s)}

mkdir -p "$STATE_DIR"
say() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }

alert() {
  # Through the api container; if that is the one unhealthy, the log still has it.
  "$DOCKER" exec "${PROJECT}-api-1" python -m app.ops.host_alert "$1" "$2" "$3" >/dev/null 2>&1 || true
}

for name in $("$DOCKER" ps --filter "label=com.docker.compose.project=${PROJECT}" \
    --filter health=unhealthy --format '{{.Names}}'); do
  stamp="$STATE_DIR/$name"
  last=$(cat "$stamp" 2>/dev/null || echo 0)
  if [ $((NOW - last)) -lt "$COOLDOWN_SECONDS" ]; then
    say "$name unhealthy again within the cooldown - left for a human"
    alert "container still unhealthy" \
      "$name is unhealthy again after an automatic restart; not restarting it twice in an hour." \
      "autoheal-repeat:$name"
    continue
  fi
  echo "$NOW" > "$stamp"
  if "$DOCKER" restart "$name" >/dev/null 2>&1; then
    say "$name unhealthy - restarted"
    alert "container restarted" "$name was unhealthy and was restarted automatically." \
      "autoheal:$name"
  else
    say "$name unhealthy - restart FAILED"
    alert "container restart failed" "$name is unhealthy and could not be restarted." \
      "autoheal-failed:$name"
  fi
done
