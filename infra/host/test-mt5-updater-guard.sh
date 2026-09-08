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
  # ActiveEnterTimestampMonotonic, read from a file the test writes per unit.
  # Silence for a unit with no file, which is what systemd answers for one
  # that has never been started - and the guard must not treat that as
  # "started just now".
  show) unit="${@: -1}"; cat "$STARTED_DIR/$unit" 2>/dev/null || echo 0; exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$ROOT/bin/systemctl"

STARTED_DIR="$ROOT/started"
export STARTED_DIR
mkdir -p "$STARTED_DIR"

# Say that a unit entered its active state this many seconds ago, in the
# monotonic microseconds systemd reports.
started_ago() { # unit, seconds
  awk -v s="$2" '{printf "%d", ($1 - s) * 1000000}' /proc/uptime > "$STARTED_DIR/$1"
}

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
# Down for the same reason as `looping`, but restarted a minute ago and still
# working through a cold start. On 2026-09-07 term-b spent an hour like this:
# the guard restarted it every five minutes, a cold start on that host takes
# nearly seven, and it never got far enough to write a heartbeat. The log read
# "restarted 1" each time and looked like recovery in progress.
terminal starting  900        yes      yes
started_ago molido-mt5starting 60
# The looping one has been up long enough to have failed on its own merits.
started_ago molido-mt5looping 1800
# A terminal nobody logged into: silent on purpose.
mkdir -p "$ROOT/.mt5empty/$SUFFIX"; echo '{}' > "$ROOT/.mt5empty/$SUFFIX/molido_account.json"

# A terminal nobody logged into that is *carrying a payload*. This is the case
# the guard used to skip entirely: the login check gated both halves, so a
# fresh prefix could never be defused. Terminal I was built by copying another
# prefix, inherited its payload, and looped from its first start while the
# guard passed over it every five minutes.
mkdir -p "$ROOT/.mt5fresh/$SUFFIX" "$ROOT/.mt5fresh/drive_c/Program Files/MetaTrader 5/logs"
mkdir -p "$ROOT/.mt5fresh/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/ABC/liveupdate"
echo binary > "$ROOT/.mt5fresh/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/ABC/liveupdate/terminal64.exe"
echo "LiveUpdate start terminal64.exe /upd" > "$ROOT/.mt5fresh/drive_c/Program Files/MetaTrader 5/logs/today.log"


# A terminal that looped last night and started cleanly this morning. Its log
# still carries the updater line from then, and the check used to read the
# last 200 KB - most of a day on an hourly log - so it saw that line and
# restarted a terminal that was authorising. Terminals B and G spent an hour
# that way on 2026-09-08 while the log said "restarted" each time.
mkdir -p "$ROOT/.mt5recovered/$SUFFIX" "$ROOT/.mt5recovered/drive_c/Program Files/MetaTrader 5/logs"
echo '{"login":123,"equity":1000}' > "$ROOT/.mt5recovered/$SUFFIX/molido_account.json"
echo '{"connected":true}' > "$ROOT/.mt5recovered/$SUFFIX/molido_heartbeat.json"
touch -d "@$(( $(date +%s) - 900 ))" "$ROOT/.mt5recovered/$SUFFIX/molido_heartbeat.json"
{
  echo "LiveUpdate start terminal64.exe /upd"
  echo "Terminal stopped with 0"
  echo "Terminal MetaTrader 5 x64 build 6140 started for MetaQuotes Ltd"
  echo "Network synchronized with RoboForex Ltd"
} > "$ROOT/.mt5recovered/drive_c/Program Files/MetaTrader 5/logs/today.log"
started_ago molido-mt5recovered 4000

# A white-label build: the terminal installs under the firm's own name, and
# the old fixed path looked only under "MetaTrader 5", so neither prop
# terminal could ever be recovered.
mkdir -p "$ROOT/.mt5branded/$SUFFIX" "$ROOT/.mt5branded/drive_c/Program Files/FTMO Global Markets MT5 Terminal/logs"
echo '{"login":123,"equity":1000}' > "$ROOT/.mt5branded/$SUFFIX/molido_account.json"
echo '{"connected":true}' > "$ROOT/.mt5branded/$SUFFIX/molido_heartbeat.json"
touch -d "@$(( $(date +%s) - 900 ))" "$ROOT/.mt5branded/$SUFFIX/molido_heartbeat.json"
{
  echo "Terminal FTMO MT5 x64 build 6140 started for FTMO Global Markets Ltd"
  echo "LiveUpdate start terminal64.exe /upd"
} > "$ROOT/.mt5branded/drive_c/Program Files/FTMO Global Markets MT5 Terminal/logs/today.log"
started_ago molido-mt5branded 4000

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
check "one that started a minute ago is left to finish coming up" "$(count 'molido-mt5starting')" "0"
check "and that is written down as what it is"  "$(grep -c 'still coming up' "$LOG")" "1"
check "and that decision is written down"      "$(grep -c 'mt5quiet.*left alone for a human' "$LOG")" "1"

echo "A terminal nobody logged into is not a fault:"
check "it is not restarted"                 "$(count 'molido-mt5empty')" "0"
check "nor is a fresh one carrying a payload" "$(count 'molido-mt5fresh')" "0"

echo "But it is still defused - the one terminal that cannot recover alone:"
check "a fresh prefix's payload is moved aside" "$(has_exe fresh)" "no"
check "and kept, like every other"             "$(defused_dirs fresh)" "1"
check "nine terminals were checked"           "$(grep -oE 'checked [0-9]+' "$LOG" | tail -1 | cut -d' ' -f2)" "9"


echo "The updater line has to belong to this launch:"
check "one that looped last night and started clean is left alone" "$(count 'molido-mt5recovered')" "0"
check "and it is named for a human rather than restarted"          "$(grep -c 'mt5recovered.*left alone for a human' "$LOG")" "1"

echo "A white-label build has a log too:"
check "a branded terminal in the loop is recovered"  "$(count 'start molido-mt5branded')" "1"

rm -rf "$ROOT"
echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
