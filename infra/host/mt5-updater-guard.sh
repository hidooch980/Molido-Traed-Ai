#!/bin/bash
# Keep the MetaTrader updater from taking a terminal down.
#
# On 2026-09-03 the 196,000 account stopped publishing for twenty minutes and
# nothing said so. The service read "active"; systemd was restarting it every
# ten seconds and the restart counter had reached fifteen. The terminal's own
# log had the whole story:
#
#   13:34:30  LiveUpdate  start "...\liveupdate\terminal64.exe" /upd
#   13:34:31  Terminal    stopped with 0
#
# MetaTrader had downloaded a new build, and every launch handed control to
# the updater and shut the terminal down. Under Wine the updater cannot
# complete, so it does that forever. The account was flat, unreadable and
# untradeable, and the only outward sign was a heartbeat growing older.
#
# This runs on a timer and does two separate things.
#
# DEFUSE is the important one, and it is prevention rather than repair. A
# downloaded payload only matters at the next launch, so a payload carrying a
# terminal64.exe can be moved aside while the terminal is running happily and
# nothing is interrupted. Three other terminals were holding partial
# downloads when this was written; they would each have hit the same wall on
# their own schedule, silently, one account at a time.
#
# RECOVER is for a terminal already in the loop. It is deliberately narrow:
# it needs a stale heartbeat AND the updater's own line in the log. A
# watchdog that restarts anything quiet would mask every other fault this
# system has - a broker disconnect, an evicted session, a hung expert - by
# turning them all into a restart, and the evidence would be gone.
#
# Nothing is deleted. The payload is moved to a dated name, so if a build
# ever does need to be applied by hand it is still there.

set -uo pipefail

STALE_SECONDS=${STALE_SECONDS:-420}
LOG=${LOG:-/var/log/molido-updater-guard.log}
COMMON_SUFFIX="drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files"

say() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

defused=0
recovered=0
checked=0

for prefix in /root/.mt5*; do
  [ -d "$prefix" ] || continue
  suffix=${prefix#/root/.mt5}
  unit=$([ -z "$suffix" ] && echo molido-mt5 || echo "molido-mt5${suffix}")
  systemctl list-unit-files "${unit}.service" >/dev/null 2>&1 || continue

  account="$prefix/$COMMON_SUFFIX/molido_account.json"
  heartbeat="$prefix/$COMMON_SUFFIX/molido_heartbeat.json"
  # A terminal nobody has logged into is meant to be silent. Restarting it
  # would be noise, and its silence is not a fault.
  grep -q '"login"' "$account" 2>/dev/null || continue
  checked=$((checked + 1))

  # --- DEFUSE: a payload that would take it down at the next launch --------
  # Depth 10, not 8. The real path is nine levels below the prefix -
  #   drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/<id>/liveupdate
  # - so a maxdepth of 8 found nothing, on the server and in the test alike.
  # The guard would have run every five minutes, reported "defused 0", and
  # been believed.
  payload=$(find "$prefix" -maxdepth 10 -type d -iname liveupdate 2>/dev/null | head -1)
  if [ -n "$payload" ] && [ -f "$payload/terminal64.exe" ]; then
    aside="${payload}.defused-$(date -u '+%Y%m%dT%H%M%SZ')"
    if mv "$payload" "$aside" 2>/dev/null; then
      say "$unit: moved an update payload aside before it could stop the terminal ($aside)"
      defused=$((defused + 1))
    else
      say "$unit: WARNING could not move $payload aside"
    fi
  fi

  # --- RECOVER: already in the loop ---------------------------------------
  now=$(date +%s)
  beat=$(stat -c %Y "$heartbeat" 2>/dev/null || echo 0)
  age=$((now - beat))
  [ "$age" -lt "$STALE_SECONDS" ] && continue

  # Only when the updater is what stopped it. Every other cause of silence
  # deserves to stay visible rather than being restarted into invisibility.
  log=$(ls -t "$prefix"/drive_c/Program\ Files/MetaTrader\ 5/logs/*.log 2>/dev/null | head -1)
  if [ -z "$log" ] || ! tail -c 200000 "$log" 2>/dev/null | tr -d '\000' | grep -q "LiveUpdate"; then
    say "$unit: heartbeat ${age}s old, but the log does not show the updater - left alone for a human"
    continue
  fi

  say "$unit: heartbeat ${age}s old and the updater is in its log - restarting"
  systemctl stop "$unit" >/dev/null 2>&1
  sleep 3
  systemctl reset-failed "$unit" >/dev/null 2>&1
  systemctl start "$unit" >/dev/null 2>&1
  recovered=$((recovered + 1))
done

say "checked ${checked} terminal(s): defused ${defused}, restarted ${recovered}"
