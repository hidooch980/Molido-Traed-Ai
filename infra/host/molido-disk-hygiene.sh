#!/bin/bash
# Keep the volume clear enough for the trading gate to stay open.
#
# `readiness.disk_headroom` blocks every order below 15% free, and on
# 2026-09-08 that is exactly what happened: the volume reached 90%, the
# autopilot reported `authorized: false` on every cycle, and the cause was
# not data - it was 10.8 GB of Docker build cache left behind by rebuilds.
#
# Build cache only. Images, volumes and containers are left alone: an
# aggressive `system prune` on a host whose migrate image is built separately
# would remove the one thing the next deploy needs, and a script that runs
# unattended must not be able to do that.
set -uo pipefail

LOG=${LOG:-/var/log/molido-disk-hygiene.log}
#: Prune when free space falls below this. Twenty percent, not fifteen: the
#: gate closes at fifteen and a hygiene job that waits for the gate to close
#: has already failed at its job.
MIN_FREE_PERCENT=${MIN_FREE_PERCENT:-20}

say() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
free=$((100 - used))

if [ "$free" -ge "$MIN_FREE_PERCENT" ]; then
  say "${free}% free, above the ${MIN_FREE_PERCENT}% mark - nothing to do"
  exit 0
fi

before=$(df -h --output=avail / | tail -1 | tr -d ' ')
reclaimed=$(docker builder prune -af 2>/dev/null | grep -i "reclaimed" | tail -1)
after=$(df -h --output=avail / | tail -1 | tr -d ' ')
say "${free}% free: pruned the build cache. ${before} -> ${after}. ${reclaimed:-nothing reclaimed}"

# Journald too, which had grown to 369 MB by the same date.
journalctl --vacuum-size=150M >/dev/null 2>&1 && say "journal vacuumed to 150M"

used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
free=$((100 - used))
if [ "$free" -lt 15 ]; then
  # Said loudly rather than fixed: everything left is data somebody chose to
  # keep - downloaded history, database backups - and a script deciding which
  # of those to delete unattended is worse than a full disk.
  say "STILL ONLY ${free}% FREE after pruning - the trading gate closes at 15%, and what remains is data a person has to choose about"
fi
