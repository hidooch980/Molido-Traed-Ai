#!/bin/bash
# The Telegram updater against a stubbed docker and deploy: nothing is built.
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/molido-update.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$WORK" init -q repo
git -C "$WORK/repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init

cat > "$WORK/docker" <<'STUB'
#!/bin/bash
echo "$*" >> "$CALLS"
exit 0
STUB
cat > "$WORK/deploy-ok" <<'STUB'
#!/bin/bash
echo "deploy ran in $PWD" >> "$CALLS"
exit 0
STUB
cat > "$WORK/deploy-fail" <<'STUB'
#!/bin/bash
echo "deploy ran" >> "$CALLS"
echo "error: cannot fast-forward"
exit 1
STUB
chmod +x "$WORK/docker" "$WORK/deploy-ok" "$WORK/deploy-fail"

export CALLS="$WORK/calls"
mkdir -p "$WORK/state"

request() { echo '{"requested_by":"1"}' > "$WORK/state/update-request.json"; touch -d "@$1" "$WORK/state/update-request.json"; }
run() {
  MOLIDO_ROOT="$WORK/repo" STATE="$WORK/state" WORK_DIR="$WORK/work" LOG="$WORK/log" \
    LOCK="$WORK/lock" DOCKER="$WORK/docker" DEPLOY="$WORK/$2" NOW="$1" WAIT_STEP=0 \
    bash "$SCRIPT"
}
fail() { echo "FAIL: $*"; cat "$WORK/calls" 2>/dev/null; exit 1; }

# No request: nothing at all.
: > "$CALLS"
run 100000 deploy-ok
[ -s "$CALLS" ] && fail "acted with no request"

# A fresh request deploys, removes itself, and reports start and finish.
request 100000
: > "$CALLS"
run 100030 deploy-ok
grep -q "^deploy ran in $WORK/repo" "$CALLS" || fail "fresh request did not deploy from the repo root"
[ -f "$WORK/state/update-request.json" ] && fail "request was not removed"
grep -q "شروع شد" "$CALLS" || fail "start was not reported"
grep -q "تمام شد" "$CALLS" || fail "success was not reported"

# Inside the cooldown: refused and reported, no deploy.
request 100100
: > "$CALLS"
run 100120 deploy-ok
grep -q "^deploy ran" "$CALLS" && fail "deployed inside the cooldown"
grep -q "انجام نشد" "$CALLS" || fail "cooldown refusal was not reported"

# A stale request: dropped and reported, no deploy.
request 200000
: > "$CALLS"
run 201000 deploy-ok
grep -q "^deploy ran" "$CALLS" && fail "deployed a stale request"
[ -f "$WORK/state/update-request.json" ] && fail "stale request was not removed"

# A failing deploy is reported as a failure with the log tail.
request 300000
: > "$CALLS"
run 300010 deploy-fail
grep -q "^deploy ran" "$CALLS" || fail "second deploy did not run"
grep -q "ناموفق" "$CALLS" || fail "failure was not reported"
grep -q "cannot fast-forward" "$CALLS" || fail "failure did not carry the log tail"

echo "ok  updater: no request, deploy + report, cooldown, stale, failure"
