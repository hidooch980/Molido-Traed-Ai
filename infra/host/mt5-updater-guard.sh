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
#: How long a terminal is left alone after it starts, before its silence
#: counts against it.
#:
#: A cold start on this host is not quick: the terminal authorises, syncs
#: symbols and loads the expert, and under load that took nearly seven
#: minutes on 2026-09-07 - longer than the five-minute timer that calls this
#: script. So a terminal restarted once was restarted again while it was
#: still legitimately starting, and again, and it never reached the point of
#: writing a heartbeat. Term-b spent an hour in that loop, and the loop was
#: the guard: the log read "restarted 1" every five minutes and looked like
#: recovery in progress.
#:
#: Fifteen minutes is a cold start with room, and it costs nothing: a
#: terminal that is genuinely stuck is still restarted, one timer later.
START_GRACE_SECONDS=${START_GRACE_SECONDS:-900}
LOG=${LOG:-/var/log/molido-updater-guard.log}
#: Where the monotonic clock is read from. Only the tests override it: a
#: fixture that says "this unit started 4000 seconds ago" cannot be written
#: honestly on a machine that booted 30 seconds ago, and a CI runner always
#: has. Left alone it is the real one.
UPTIME_FILE=${UPTIME_FILE:-/proc/uptime}
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
  # A terminal nobody has logged into is meant to be silent, so RECOVER skips
  # it below - restarting it would be noise and its silence is not a fault.
  #
  # DEFUSE does not skip it, and that distinction was learned the hard way.
  # This check used to sit here, before both halves, and a prefix nobody had
  # logged into could therefore never be defused. Terminal I was built by
  # copying another prefix, inherited its downloaded payload, and looped from
  # its very first start - handing control to the updater, exiting, being
  # restarted, forever - while the guard ran every five minutes and skipped
  # it for not having an account file. The one terminal that could never
  # recover on its own was the one terminal the guard would not look at.
  logged_in=0
  grep -q '"login"' "$account" 2>/dev/null && logged_in=1
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
  # Only for a terminal somebody has logged in. A terminal with no account is
  # meant to be quiet, and restarting it would turn its correct silence into
  # a fault report.
  [ "$logged_in" -eq 1 ] || continue

  # And only one that is actually running. A unit that is stopped is not
  # in a loop, it is stopped - and on 2026-09-08 the guard started one
  # that had been stopped that minute for holding a second session on an
  # account another terminal was already logged into. Stopping is how an
  # operator says no; a watchdog that starts things nobody asked for is
  # not watching, it is deciding.
  #
  # `is-enabled` was tried first and was wrong: these units are started
  # by hand and were never enabled, so it hid six terminals of nine.
  systemctl is-active --quiet "${unit}.service" || continue

  now=$(date +%s)
  beat=$(stat -c %Y "$heartbeat" 2>/dev/null || echo 0)
  age=$((now - beat))
  [ "$age" -lt "$STALE_SECONDS" ] && continue

  # Still coming up. A restart here would be the third one this terminal has
  # been given while doing exactly what it was asked to do.
  started=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$unit" 2>/dev/null)
  if [ -n "${started:-}" ] && [ "$started" -gt 0 ] 2>/dev/null; then
    uptime_us=$(awk '{printf "%d", $1 * 1000000}' "$UPTIME_FILE" 2>/dev/null || echo 0)
    running=$(( (uptime_us - started) / 1000000 ))
    if [ "$running" -ge 0 ] && [ "$running" -lt "$START_GRACE_SECONDS" ]; then
      say "$unit: heartbeat ${age}s old but it started ${running}s ago - still coming up"
      continue
    fi
  fi

  # Only when the updater is what stopped it. Every other cause of silence
  # deserves to stay visible rather than being restarted into invisibility.
  # Any build's log, not just a generic MetaTrader one: a white-label
  # terminal installs under its own name - "FTMO Global Markets MT5
  # Terminal", "FundedNext MT5 Terminal" - and the fixed path found
  # nothing for those, so neither prop terminal could ever be recovered.
  log=$(ls -t "$prefix"/drive_c/Program\ Files/*/logs/*.log 2>/dev/null | head -1)

  # Only what this launch wrote, and that is the whole of it.
  #
  # The check used to read the last 200 KB, which on an hourly log is
  # most of a day. A terminal that looped last night and is starting
  # normally now still carries "LiveUpdate" in that window, so it read as
  # looping and was restarted - at 916 seconds on 2026-09-08, while it
  # was authorising, and again five minutes later. Terminals B and G
  # spent an hour that way while the log said "restarted 1" each time,
  # which reads as recovery in progress.
  #
  # After the last "started for" line there is only this launch, so the
  # question becomes the right one: did the updater take *this* start
  # down, or is this a terminal still working through a slow one.
  recent=$(tr -cd '[:print:]
' < "$log" 2>/dev/null | awk '/started for/ {out=""} {out = out $0 ORS} END {printf "%s", out}')
  if [ -z "$log" ] || ! printf %s "$recent" | grep -q "LiveUpdate"; then
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
