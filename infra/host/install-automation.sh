#!/bin/bash
# Install every unattended job this host needs, in one idempotent command.
#
# Each of these existed in the repository and none was installed by anything:
# the updater guard had no timer, the digest/weekly/disk timers were never
# copied, and the checkpoint and evidence crons lived only in comments. On
# 11 September the evidence cron was missing and four days passed with zero
# orders while the health report said fresh. So the list is here, run once,
# and safe to run again.
#
#   sudo ./infra/host/install-automation.sh
#
# It changes nothing about trading. It only schedules checks and reports, and
# enables the MetaTrader units that already exist so they return after a reboot.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="$ROOT/infra/host"
PROJECT=${COMPOSE_PROJECT_NAME:-molidotrade}

echo "-> scripts into /usr/local/bin"
install -m 755 "$HOST/mt5-updater-guard.sh" /usr/local/bin/molido-updater-guard
install -m 755 "$HOST/molido-disk-hygiene.sh" /usr/local/bin/molido-disk-hygiene
install -m 755 "$HOST/molido-autoheal.sh" /usr/local/bin/molido-autoheal

echo "-> systemd timers"
for unit in molido-digest molido-weekly molido-disk-hygiene molido-updater-guard molido-autoheal; do
  install -m 644 "$HOST/$unit.service" "/etc/systemd/system/$unit.service"
  install -m 644 "$HOST/$unit.timer" "/etc/systemd/system/$unit.timer"
done
systemctl daemon-reload
for unit in molido-digest molido-weekly molido-disk-hygiene molido-updater-guard molido-autoheal; do
  systemctl enable --now "$unit.timer" >/dev/null
  echo "   $unit.timer: $(systemctl is-active "$unit.timer")"
done

echo "-> MetaTrader units come back after a reboot"
for unit in $(systemctl list-unit-files --type=service --no-legend 'molido-*' | awk '{print $1}'); do
  case "$unit" in
    molido-digest.service|molido-weekly.service|molido-disk-hygiene.service|molido-updater-guard.service|molido-autoheal.service) continue ;;
  esac
  if [ "$(systemctl is-enabled "$unit" 2>/dev/null)" = "disabled" ]; then
    systemctl enable "$unit" >/dev/null 2>&1 && echo "   enabled $unit"
  fi
done

echo "-> crontab (checkpoint, evidence, backup with an alert on failure)"
ALERT="docker exec ${PROJECT}-api-1 python -m app.ops.host_alert"
LINES=$(cat <<CRON
17 */6 * * * $ROOT/infra/checkpoint.sh >> /var/log/molido-checkpoint.log 2>&1
37 17 * * * $ROOT/infra/checkpoint.sh --scorecard >> /var/log/molido-checkpoint.log 2>&1
*/15 * * * * $ROOT/infra/readiness-evidence.sh >> /var/log/molido-evidence.log 2>&1 || $ALERT "evidence failed" "readiness-evidence.sh exited non-zero; orders stop when the note goes stale." evidence
15 3 * * * $ROOT/infra/backup.sh >> /var/log/molido-backup.log 2>&1 || $ALERT "backup failed" "The nightly verified backup failed; see /var/log/molido-backup.log." backup
CRON
)
( crontab -l 2>/dev/null | grep -vE 'infra/(checkpoint|readiness-evidence|backup)\.sh' ; echo "$LINES" ) | crontab -
crontab -l | grep -E 'infra/(checkpoint|readiness-evidence|backup)\.sh' | sed 's/^/   /'

echo "-> done"
