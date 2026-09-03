#!/bin/bash
# Prove the guard does what it claims, against a fake fleet on disk.
#
# A watchdog nobody tested is a watchdog that either does nothing or restarts
# the fleet. Both are worse than no watchdog, and neither shows up until the
# night it matters. So every branch is exercised here with real directories
# and a stubbed systemctl - no terminal is started or stopped.

set -uo pipefail
GUARD="$(cd "$(dirname "$0")" && pwd)/mt5-updater-guard.sh"
ROOT=$(mktemp -d)
LOG="$ROOT/guard.log"
ACTIONS="$ROOT/systemctl-calls"
SUFFIX="drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files"
pass=0; fail=0

# grep -c prints 0 and exits 1 when nothing matches, so the old "|| echo 0"
# printed a second zero and every count read as two lines. Those failures were
# the harness own, not the guard - its own small lesson about trusting a test.
count() { grep -c "$1" "$ACTIONS" 2>/dev/null; true; }

check() { if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "  ok   $1"; else fail=$((fail+1)); echo "  FAIL $1: expected '$3', got '$2'"; fi; }

# A stubbed systemctl: records what it was asked to do and claims every unit
# exists, so the guard's real decisions are what is under test.
mkdir -p "$ROOT/bin"
cat > "$ROOT/bin/systemctl" <<'STUB'
#!/bin/bash
case "$1" in
  list-unit-files) exit 0 ;;
  stop|start|restart) echo "$1 $2" >> "$SYSTEMCTL_CALLS" ; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$ROOT/bin/systemctl"

terminal() { # name, heartbeat_age, has_payload_exe, log_has_liveupdate
  local p="$ROOT/.mt5$1"
  mkdir -p "$p/$SUFFIX" "$p/drive_c/Program Files/MetaTrader 5/logs"
  echo '{"login":123,"equity":1000}' > "$p/$SUFFIX/molido_account.json"
  echo '{"connected":true}' > "$p/$SUFFIX/molido_heartbeat.json"
  touch -d "@$(( $(date +%s) - $2 ))" "$p/$SUFFIX/molido_heartbeat.json"
  mkdir -p "$p/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/ABC/liveupdate"
  [ "$3" = yes ] && echo binary > "$p/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/ABC/liveupdate/terminal64.exe"
  if [ "$4" = yes ]; then echo "LiveUpdate start terminal64.exe /upd" > "$p/drive_c/Program Files/MetaTrader 5/logs/today.log"
  else echo "Network synchronized" > "$p/drive_c/Program Files/MetaTrader 5/logs/today.log"; fi
}

#            name  heartbeat  payload  log-shows-updater
terminal healthy   10         no       no
terminal armed     10         yes      no    # publishing fine, payload waiting
terminal looping   900        yes      yes   # already down
terminal quiet     900        no       no    # stale for some other reason
# A terminal nobody logged into: silent on purpose.
mkdir -p "$ROOT/.mt5empty/$SUFFIX"; echo '{}' > "$ROOT/.mt5empty/$SUFFIX/molido_account.json"

SYSTEMCTL_CALLS="$ACTIONS" PATH="$ROOT/bin:$PATH" \
  bash -c "sed 's#/root/.mt5\*#$ROOT/.mt5*#; s#/root/.mt5#$ROOT/.mt5#g' '$GUARD' > '$ROOT/guard.sh'; STALE_SECONDS=420 LOG='$LOG' bash '$ROOT/guard.sh'"

has_exe() { [ -f "$ROOT/.mt5$1/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/ABC/liveupdate/terminal64.exe" ] && echo yes || echo no; }
defused_dirs() { find "$ROOT/.mt5$1" -maxdepth 10 -type d -name "liveupdate.defused-*" 2>/dev/null | wc -l; }

echo "The payload is defused before it can stop a terminal:"
check "a healthy terminal carrying a payload has it moved aside" "$(has_exe armed)" "no"
check "and the payload is kept, not deleted"                     "$(defused_dirs armed)" "1"
check "a healthy terminal with no payload is untouched"          "$(defused_dirs healthy)" "0"

echo "Only a terminal the updater actually stopped is restarted:"
check "the looping terminal is restarted"      "$(count 'start molido-mt5looping')" "1"
check "the healthy one is never restarted"     "$(count 'molido-mt5healthy')" "0"
check "the one carrying a payload but publishing is never restarted" "$(count 'molido-mt5armed')" "0"
check "stale for another reason is left for a human, not restarted" "$(count 'molido-mt5quiet')" "0"
check "and that decision is written down"      "$(grep -c 'left alone for a human' "$LOG")" "1"

echo "A terminal nobody logged into is not a fault:"
check "it is not counted or acted on" "$(count 'molido-mt5empty')" "0"
check "four terminals were checked"   "$(grep -oE 'checked [0-9]+' "$LOG" | tail -1 | cut -d' ' -f2)" "4"

rm -rf "$ROOT"
echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
