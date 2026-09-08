#!/bin/bash
# What the disk hygiene job does, and more importantly what it will not do.
#
# It runs unattended on the trading host and it can delete. Everything below
# is about the boundary: it prunes build cache and nothing else, it acts only
# when the volume is genuinely tight, and when pruning is not enough it says
# so rather than reaching for data somebody chose to keep.
set -uo pipefail

ROOT=$(mktemp -d)
LOG="$ROOT/hygiene.log"
CALLS="$ROOT/docker-calls"
SCRIPT="$(cd "$(dirname "$0")" && pwd)/molido-disk-hygiene.sh"

pass=0
fail=0
check() {
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
    echo "  ok   $1"
  else
    fail=$((fail + 1))
    echo "  FAIL $1: expected '$3', got '$2'"
  fi
}

mkdir -p "$ROOT/bin"

# A stubbed docker and journalctl: they record what they were asked to do and
# do none of it, so the script's decisions are what is under test.
cat > "$ROOT/bin/docker" <<'STUB'
#!/bin/bash
echo "$*" >> "$DOCKER_CALLS"
echo "Total reclaimed space: 4.2GB"
STUB
cat > "$ROOT/bin/journalctl" <<'STUB'
#!/bin/bash
echo "journalctl $*" >> "$DOCKER_CALLS"
STUB
chmod +x "$ROOT/bin/docker" "$ROOT/bin/journalctl"

# `df` is stubbed per-case: the whole decision turns on what it reports.
stub_df() { # percent used
  cat > "$ROOT/bin/df" <<STUB
#!/bin/bash
case "\$*" in
  *pcent*) echo "Use%"; echo " $1%" ;;
  *avail*) echo "Avail"; echo " 20G" ;;
  *) echo "stub" ;;
esac
STUB
  chmod +x "$ROOT/bin/df"
}

run() {
  : > "$CALLS"
  : > "$LOG"
  DOCKER_CALLS="$CALLS" LOG="$LOG" PATH="$ROOT/bin:$PATH" bash "$SCRIPT"
}

echo "A volume with room is left alone:"
stub_df 50
run
check "no prune when half the disk is free" "$(grep -c 'builder prune' "$CALLS")" "0"
check "and it says so"                      "$(grep -c 'nothing to do' "$LOG")" "1"

echo
echo "A tight volume is pruned:"
stub_df 85
run
check "the build cache is pruned"  "$(grep -c 'builder prune -af' "$CALLS")" "1"
check "the journal is vacuumed"    "$(grep -c 'journalctl' "$CALLS")" "1"

echo
echo "And nothing else is ever touched:"
check "images are not pruned"     "$(grep -c 'image prune' "$CALLS")" "0"
check "volumes are not pruned"    "$(grep -c 'volume prune' "$CALLS")" "0"
check "no system-wide prune"      "$(grep -c 'system prune' "$CALLS")" "0"
check "nothing is removed by rm"  "$(grep -c 'rm ' "$CALLS")" "0"

echo
echo "It acts before the trading gate closes, not after:"
# The gate blocks below 15% free. 82% used is 18% free - already past the
# script's own 20% mark and not yet past the gate's.
stub_df 82
run
check "18% free is already tight enough to act" "$(grep -c 'builder prune' "$CALLS")" "1"

echo
echo "When pruning cannot fix it, it says so rather than deleting data:"
stub_df 95
run
check "the shortfall is named"        "$(grep -c 'STILL ONLY' "$LOG")" "1"
check "and still nothing else pruned" "$(grep -c 'image prune\|volume prune\|system prune' "$CALLS")" "0"

rm -rf "$ROOT"
echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
