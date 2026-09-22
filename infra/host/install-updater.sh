#!/bin/bash
# Install the timer that lets /update in Telegram deploy this host.
#
# Called by deploy.sh on every deploy (idempotent), so the one deploy a person
# runs by hand is the last one they need to.
#
#   sudo ./infra/host/install-updater.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="$ROOT/infra/host"

install -m 755 "$HOST/molido-update.sh" /usr/local/bin/molido-update
sed "s|@ROOT@|$ROOT|" "$HOST/molido-update.service" > /etc/systemd/system/molido-update.service
install -m 644 "$HOST/molido-update.timer" /etc/systemd/system/molido-update.timer
systemctl daemon-reload
systemctl enable --now molido-update.timer >/dev/null
echo "   molido-update.timer: $(systemctl is-active molido-update.timer)"
