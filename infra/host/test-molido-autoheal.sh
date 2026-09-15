#!/bin/bash
# The autoheal job against a stubbed docker: restarts once, then only alerts.
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/molido-autoheal.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/docker" <<'STUB'
#!/bin/bash
echo "$*" >> "$CALLS"
case "$1" in
  ps) echo "molidotrade-collector-1" ;;
esac
exit 0
STUB
chmod +x "$WORK/docker"

run() {
  CALLS="$WORK/calls" DOCKER="$WORK/docker" STATE_DIR="$WORK/state" LOG="$WORK/log" \
    NOW="$1" bash "$SCRIPT"
}
fail() { echo "FAIL: $*"; cat "$WORK/calls"; exit 1; }

export CALLS="$WORK/calls"

run 10000
grep -q "^restart molidotrade-collector-1" "$WORK/calls" || fail "first unhealthy run did not restart"
grep -q "autoheal:molidotrade-collector-1" "$WORK/calls" || fail "restart was not alerted"

: > "$WORK/calls"
run 10600
grep -q "^restart" "$WORK/calls" && fail "restarted again inside the cooldown"
grep -q "autoheal-repeat:molidotrade-collector-1" "$WORK/calls" || fail "repeat was not alerted"

: > "$WORK/calls"
run 20000
grep -q "^restart molidotrade-collector-1" "$WORK/calls" || fail "did not restart after the cooldown"

echo "ok  autoheal: restart, cooldown alert, restart after cooldown"
