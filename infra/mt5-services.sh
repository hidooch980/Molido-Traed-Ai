#!/usr/bin/env bash
# Make the MetaTrader stack survive a reboot, and give the bridge an interpreter.
#
# After `mt5-install.sh` the terminal runs, but every piece of it is a loose
# background process started by hand: Xvfb, x11vnc, websockify and the terminal
# itself. The first restart of this machine takes all four with it, silently,
# and the first anyone would know is a data feed that stopped answering.
#
# There is also no Python that can import MetaTrader5. The package is
# Windows-only, so it needs a Windows interpreter living inside the same Wine
# prefix as the terminal - the system's Linux python cannot import it at any
# price. That is what makes `mt5_bridge.py` runnable rather than merely written.
#
# Everything binds to 127.0.0.1. This stack can read an account and, once
# deliberately enabled, place orders on it, which makes it the most dangerous
# listener on the host. It is not on the firewall and not behind Caddy; the
# owner reaches the screen through an SSH tunnel.
#
#   ./infra/mt5-services.sh python     # Windows Python + MetaTrader5 only
#   ./infra/mt5-services.sh services   # systemd units only
#   ./infra/mt5-services.sh            # both, then report
#   ./infra/mt5-services.sh status     # report, change nothing

set -euo pipefail

PREFIX="${HOME}/.mt5"
DISPLAY_NUM=99
VNC_PORT=5999
WEB_PORT=6080
BRIDGE_PORT=18812
PYTHON_VERSION="3.12.7"
PYDIR="${PREFIX}/drive_c/python"
REPO="/opt/molidotrade"

log() { printf '\n=== %s ===\n' "$1"; }

wine_python() { printf '%s/python.exe' "$PYDIR"; }

status() {
  log "processes"
  for name in Xvfb x11vnc websockify terminal64 mt5_bridge; do
    printf '%-12s %s\n' "$name" "$(pgrep -f "$name" >/dev/null && echo running || echo 'not running')"
  done
  log "systemd"
  systemctl list-units --type=service --all --no-legend 'molido-*' 2>/dev/null |
    awk '{printf "%-26s %s %s\n", $1, $3, $4}' || echo "no units"
  log "windows python"
  # -f rather than -x: a Windows executable on a Linux filesystem carries no
  # exec bit and does not need one, so testing for it reports a working
  # interpreter as absent.
  if [ -f "$(wine_python)" ]; then
    WINEPREFIX="$PREFIX" WINEDEBUG=-all wine "$(wine_python)" -c \
      "import MetaTrader5 as m; print('MetaTrader5', m.__version__)" 2>/dev/null ||
      echo "python present, MetaTrader5 not importable"
  else
    echo "not installed"
  fi
  log "listeners"
  ss -tlnp 2>/dev/null | grep -E "${VNC_PORT}|${WEB_PORT}|${BRIDGE_PORT}" || echo "none"
}

install_python() {
  log "windows python ${PYTHON_VERSION}"
  export WINEPREFIX="$PREFIX"
  export WINEDEBUG=-all
  mkdir -p "$HOME/mt5"

  # The embeddable build rather than the installer: the installer runs a full
  # MSI under Wine and fails in ways that are tedious to diagnose, while the
  # embeddable zip is a directory of files that either extracted or did not.
  local zip="$HOME/mt5/python-embed.zip"
  if [ ! -f "$zip" ]; then
    curl -fsSL -o "$zip" \
      "https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip"
  fi
  mkdir -p "$PYDIR"
  unzip -oq "$zip" -d "$PYDIR"

  # The embeddable build ships with imports from site-packages switched off, so
  # a pip install appears to succeed and then nothing can be imported. This is
  # the line that makes the difference.
  local pth
  pth="$(find "$PYDIR" -maxdepth 1 -name 'python*._pth' | head -1)"
  if [ -n "$pth" ]; then
    sed -i 's/^#import site/import site/' "$pth"
    grep -q '^Lib\\site-packages' "$pth" || echo 'Lib\site-packages' >> "$pth"
  fi

  if [ ! -f "$HOME/mt5/get-pip.py" ]; then
    curl -fsSL -o "$HOME/mt5/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  fi
  wine "$(wine_python)" "$HOME/mt5/get-pip.py" --no-warn-script-location 2>&1 | tail -2

  log "MetaTrader5 package"
  wine "$(wine_python)" -m pip install --no-warn-script-location MetaTrader5 2>&1 | tail -3
  wine "$(wine_python)" -c "import MetaTrader5 as m; print('MetaTrader5', m.__version__)"
}

install_services() {
  log "systemd units"

  # System units running as ubuntu rather than user units: user units need
  # lingering enabled to start at boot without a login, and one more thing that
  # has to be remembered is one more thing that gets forgotten.
  sudo tee /etc/systemd/system/molido-xvfb.service >/dev/null <<UNIT
[Unit]
Description=Virtual display for MetaTrader
After=network.target

[Service]
User=ubuntu
ExecStart=/usr/bin/Xvfb :${DISPLAY_NUM} -screen 0 1280x900x24 -nolisten tcp
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

  # A window manager, which is not decoration. Without one no window can take
  # focus, so every keystroke goes nowhere - including the ones the account
  # holder types into MetaTrader's login box over VNC.
  sudo tee /etc/systemd/system/molido-wm.service >/dev/null <<UNIT
[Unit]
Description=Window manager for the MetaTrader display
After=molido-xvfb.service
Requires=molido-xvfb.service

[Service]
User=ubuntu
Environment=DISPLAY=:${DISPLAY_NUM}
ExecStart=/usr/bin/openbox --sm-disable
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

  sudo tee /etc/systemd/system/molido-vnc.service >/dev/null <<UNIT
[Unit]
Description=VNC view of the MetaTrader display, loopback only
After=molido-xvfb.service
Requires=molido-xvfb.service

[Service]
User=ubuntu
# -localhost is the whole security posture here. A remote desktop reachable
# from the internet on a host that gets brute-forced would undo the rest.
ExecStart=/usr/bin/x11vnc -display :${DISPLAY_NUM} -rfbport ${VNC_PORT} -localhost -forever -shared -nopw -quiet
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

  sudo tee /etc/systemd/system/molido-novnc.service >/dev/null <<UNIT
[Unit]
Description=Browser view of the MetaTrader display, loopback only
After=molido-vnc.service
Requires=molido-vnc.service

[Service]
User=ubuntu
ExecStart=/usr/bin/websockify --web /usr/share/novnc 127.0.0.1:${WEB_PORT} 127.0.0.1:${VNC_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

  sudo tee /etc/systemd/system/molido-mt5.service >/dev/null <<UNIT
[Unit]
Description=MetaTrader 5 terminal under Wine
After=molido-wm.service
Requires=molido-wm.service

[Service]
User=ubuntu
Environment=DISPLAY=:${DISPLAY_NUM}
Environment=WINEPREFIX=${PREFIX}
Environment=WINEDEBUG=-all
# /config: names the startup file that both enables algorithmic trading
# and attaches the bridge expert. Doing it here rather than by hand is
# the point: the Navigator panel that would otherwise start it does not
# render its expanders under Wine, so there is no node to click.
# The config path is given in Windows form. Passed as a Unix path the
# terminal starts, ignores it in silence, and publishes nothing - which
# reads as a broken bridge rather than an unread argument.
WorkingDirectory=${PREFIX}/drive_c/Program Files/MetaTrader 5
ExecStart=/usr/bin/wine terminal64.exe "/config:C:\Program Files\MetaTrader 5\config\molido-startup.ini"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

  sudo tee /etc/systemd/system/molido-mt5-bridge.service >/dev/null <<UNIT
[Unit]
Description=Loopback HTTP bridge to MetaTrader 5
After=molido-mt5.service
Requires=molido-mt5.service

[Service]
User=ubuntu
Environment=DISPLAY=:${DISPLAY_NUM}
Environment=WINEPREFIX=${PREFIX}
Environment=WINEDEBUG=-all
Environment=MOLIDO_MT5_PORT=${BRIDGE_PORT}
# Orders stay refused until this is deliberately set to yes. Not caution for
# its own sake: this deployment has no proven edge and the decision chain
# currently produces zero intents, so an order path open by default is one
# edit away from automating a loss.
Environment=MOLIDO_MT5_ALLOW_ORDERS=no
ExecStart=/usr/bin/wine ${PYDIR}/python.exe ${REPO}/infra/mt5_bridge.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

  # The hand-started processes have to go first or the units fight them for the
  # display and the ports.
  pkill -f openbox 2>/dev/null || true
  pkill -f "Xvfb :${DISPLAY_NUM}" 2>/dev/null || true
  pkill -f "x11vnc -display :${DISPLAY_NUM}" 2>/dev/null || true
  pkill -f "websockify --web" 2>/dev/null || true
  pkill -f terminal64.exe 2>/dev/null || true
  sleep 2

  sudo systemctl daemon-reload
  sudo systemctl enable --now molido-xvfb molido-wm molido-vnc molido-novnc molido-mt5 2>&1 | tail -2
  # -f rather than -x: a Windows executable on a Linux filesystem carries no
  # exec bit and does not need one, so testing for it reports a working
  # interpreter as absent.
  if [ -f "$(wine_python)" ]; then
    sudo systemctl enable --now molido-mt5-bridge 2>&1 | tail -1
  else
    echo "bridge unit written but not started: no Windows python yet"
  fi
}

case "${1:-all}" in
  status) status ;;
  python) install_python; status ;;
  services) install_services; sleep 5; status ;;
  all) install_python; install_services; sleep 5; status ;;
  *) echo "usage: $0 [all|python|services|status]"; exit 2 ;;
esac
