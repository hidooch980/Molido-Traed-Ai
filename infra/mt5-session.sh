#!/usr/bin/env bash
# Bring the MetaTrader terminal up on a headless display and publish that
# display to a browser tab, over the loopback interface only.
#
# Why a visible terminal at all, on a server with no monitor: MetaTrader
# returns no price and accepts no order until an account is logged in, and
# logging in means typing a password. That password belongs to the account
# holder. Putting it in a config file, an environment variable or a chat
# message spreads it to places nobody can take it back from, so the terminal
# gets a real screen and the owner types it into MetaTrader's own login box.
#
# Everything binds to 127.0.0.1. Reaching it takes an SSH tunnel, which means
# it inherits the key-only authentication this host already enforces. A VNC
# port open to the internet, on a box that was being brute-forced this morning,
# would quietly undo a day of hardening - a remote desktop is a much larger
# door than the one we just locked.
#
#   ./infra/mt5-session.sh start
#   ./infra/mt5-session.sh status
#   ./infra/mt5-session.sh stop

set -uo pipefail

DISPLAY_NUM=99
VNC_PORT=5999      # loopback only
WEB_PORT=6080      # loopback only
WINEPREFIX_DIR="${HOME}/.mt5"
TERMINAL="${WINEPREFIX_DIR}/drive_c/Program Files/MetaTrader 5/terminal64.exe"
NOVNC_DIR=/usr/share/novnc

export WINEPREFIX="$WINEPREFIX_DIR"
export WINEARCH=win64
export WINEDLLOVERRIDES="mscoree,mshtml="
export DISPLAY=":${DISPLAY_NUM}"

log() { printf '\n=== %s ===\n' "$1"; }

running() { pgrep -f "$1" >/dev/null 2>&1; }

status() {
  log "processes"
  for pattern in "Xvfb :${DISPLAY_NUM}" "x11vnc" "websockify" "terminal64.exe"; do
    printf '%-22s %s\n' "$pattern" "$(running "$pattern" && echo running || echo stopped)"
  done
  log "listening (loopback only is the point)"
  ss -tlnp 2>/dev/null | grep -E ":(${VNC_PORT}|${WEB_PORT})\b" || echo "neither port is listening"
  log "memory"
  free -h | head -2
}

stop() {
  for pattern in terminal64.exe websockify x11vnc "Xvfb :${DISPLAY_NUM}"; do
    pkill -f "$pattern" 2>/dev/null && echo "stopped $pattern" || echo "$pattern was not running"
  done
}

start() {
  [ -f "$TERMINAL" ] || { echo "no terminal at $TERMINAL - run mt5-install.sh first"; exit 1; }

  log "display"
  running "Xvfb :${DISPLAY_NUM}" || {
    Xvfb ":${DISPLAY_NUM}" -screen 0 1280x900x24 -nolisten tcp >/dev/null 2>&1 &
    sleep 2
  }
  echo "display :${DISPLAY_NUM} up"

  log "terminal"
  running terminal64.exe || {
    nohup wine "$TERMINAL" >/tmp/mt5-terminal.log 2>&1 &
    # The first start unpacks and builds its data directory, which takes longer
    # than a health check would wait for.
    sleep 25
  }
  running terminal64.exe && echo "terminal running" || {
    echo "terminal failed to start - last lines:"; tail -5 /tmp/mt5-terminal.log
  }

  log "vnc"
  running x11vnc || {
    # -localhost is the security boundary, not -rfbauth: the tunnel already
    # authenticates, and a password stored on the host it protects is theatre.
    nohup x11vnc -display ":${DISPLAY_NUM}" -rfbport "$VNC_PORT" -localhost \
      -forever -shared -nopw -quiet >/tmp/mt5-x11vnc.log 2>&1 &
    sleep 2
  }

  log "browser bridge"
  running websockify || {
    nohup websockify --web "$NOVNC_DIR" "127.0.0.1:${WEB_PORT}" \
      "127.0.0.1:${VNC_PORT}" >/tmp/mt5-websockify.log 2>&1 &
    sleep 2
  }

  status

  cat <<INSTRUCTIONS

To open the terminal in a browser tab, from your own machine:

  ssh -N -L ${WEB_PORT}:127.0.0.1:${WEB_PORT} molido

then visit  http://localhost:${WEB_PORT}/vnc.html

Leave the ssh command running while you use the tab; closing it closes the
tunnel. Nothing here is reachable from the internet.
INSTRUCTIONS
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}"; exit 2 ;;
esac
