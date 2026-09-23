#!/bin/bash
# Run the deploy an admin asked for from Telegram, and report back there.
#
# The chat worker cannot deploy and must not: it runs in a container, and a
# chat is not a shell. `/update` + `/update_confirm <code>` only writes
# $STATE/update-request.json. This timer, on the host, is what acts on it -
# and the only thing it will ever run is `infra/deploy.sh`, which
# fast-forwards to origin/main and nothing else. Nothing in the request file
# is passed to a command; it is read only for its age.
#
#   - a request older than MAX_AGE_SECONDS is dropped (a timer that was off
#     for a day must not redeploy on its first tick),
#   - at most one deploy per COOLDOWN_SECONDS,
#   - one at a time (flock), and the request is removed before the deploy
#     starts, so a slow deploy is never started twice.

set -uo pipefail

ROOT=${MOLIDO_ROOT:-/opt/molidotrade}
PROJECT=${COMPOSE_PROJECT_NAME:-molidotrade}
STATE=${STATE:-/var/lib/molido/state}
WORK_DIR=${WORK_DIR:-/var/lib/molido/update}
LOG=${LOG:-/var/log/molido-update.log}
LOCK=${LOCK:-/run/lock/molido-update.lock}
MAX_AGE_SECONDS=${MAX_AGE_SECONDS:-900}
COOLDOWN_SECONDS=${COOLDOWN_SECONDS:-600}
DOCKER=${DOCKER:-docker}
DEPLOY=${DEPLOY:-$ROOT/infra/deploy.sh}
NOW=${NOW:-$(date +%s)}

REQUEST="$STATE/update-request.json"
[ -f "$REQUEST" ] || exit 0

mkdir -p "$WORK_DIR" "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || exit 0

say() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }
alert() {
  # Through the api container, which the deploy rebuilds - so the last alert
  # waits for it to answer. If it never does, the log still has the result.
  "$DOCKER" exec "${PROJECT}-api-1" python -m app.ops.host_alert "$1" "$2" >/dev/null 2>&1 || true
}

requested=$(stat -c %Y "$REQUEST" 2>/dev/null || echo 0)
rm -f "$REQUEST"

if [ $((NOW - requested)) -gt "$MAX_AGE_SECONDS" ]; then
  say "request from $(date -u -d "@$requested" +%FT%TZ 2>/dev/null) is stale - ignored"
  alert "به‌روزرسانی انجام نشد" "درخواست قدیمی‌تر از $((MAX_AGE_SECONDS / 60)) دقیقه بود و نادیده گرفته شد. دوباره /update را بفرستید."
  exit 0
fi

last=$(cat "$WORK_DIR/last" 2>/dev/null || echo 0)
if [ $((NOW - last)) -lt "$COOLDOWN_SECONDS" ]; then
  say "request inside the cooldown - ignored"
  alert "به‌روزرسانی انجام نشد" "آخرین به‌روزرسانی کمتر از $((COOLDOWN_SECONDS / 60)) دقیقه پیش بود. کمی بعد دوباره /update را بفرستید."
  exit 0
fi
echo "$NOW" > "$WORK_DIR/last"

before=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "?")
say "deploy requested from Telegram, at $before"
alert "به‌روزرسانی شروع شد" "نسخهٔ فعلی: $before. چند دقیقه سایت و ربات در دسترس نیستند."

if (cd "$ROOT" && "$DEPLOY") >> "$LOG" 2>&1; then
  status=ok
else
  status=failed
fi
after=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "?")
say "deploy $status, $before -> $after"

# The api container was just rebuilt; give it up to two minutes to answer.
for _ in $(seq 1 24); do
  "$DOCKER" exec "${PROJECT}-api-1" true >/dev/null 2>&1 && break
  sleep "${WAIT_STEP:-5}"
done

if [ "$status" = ok ]; then
  alert "به‌روزرسانی تمام شد ✅" "نسخه: $before ← $after. پانزده دقیقه بعد /why_no_trade را بزنید."
else
  tail_text=$(tail -n 8 "$LOG" | tr -d '`' | cut -c1-200)
  alert "به‌روزرسانی ناموفق ❌" "نسخه روی $after ماند. آخر گزارش:
$tail_text"
fi
