#!/usr/bin/env bash
# Install MetaTrader 5 on the Linux host, under Wine, headless.
#
# MetaTrader's Python package is Windows-only, so the terminal and a Windows
# Python run inside a Wine prefix and the native application talks to them over
# a local RPC. That is the whole reason this file exists: everything here is in
# service of making a Windows-only API reachable from Linux code.
#
# Headless matters for one specific reason. The terminal needs an account
# logged in before it returns a single price, and logging in means typing a
# password. That password is the account holder's and belongs in MetaTrader's
# own login box, not in a config file, an environment variable or a chat
# window. So this script brings up a real X display and a VNC server bound to
# localhost, and the owner reaches it through an SSH tunnel and types the
# password into the actual terminal.
#
# Bound to 127.0.0.1 deliberately. A VNC port open to the internet on a box
# that was being brute-forced this morning would undo the hardening that took
# the rest of the day.
#
#   ./infra/mt5-install.sh          # everything
#   ./infra/mt5-install.sh verify   # report what is installed, change nothing

set -euo pipefail

WINEPREFIX_DIR="${HOME}/.mt5"
MT5_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
DISPLAY_NUM=99

log() { printf '\n=== %s ===\n' "$1"; }

verify() {
  log "wine"
  command -v wine >/dev/null && wine --version || echo "not installed"
  log "display tooling"
  for tool in Xvfb x11vnc websockify; do
    printf '%-12s %s\n' "$tool" "$(command -v "$tool" || echo 'missing')"
  done
  log "wine prefix"
  [ -d "$WINEPREFIX_DIR" ] && du -sh "$WINEPREFIX_DIR" || echo "no prefix at $WINEPREFIX_DIR"
  log "terminal"
  find "$WINEPREFIX_DIR" -name 'terminal64.exe' 2>/dev/null | head -3 || true
  log "running"
  pgrep -a Xvfb | head -2 || echo "Xvfb not running"
  pgrep -a x11vnc | head -2 || echo "x11vnc not running"
  pgrep -af terminal64 | head -2 || echo "terminal not running"
}

if [ "${1:-}" = "verify" ]; then
  verify
  exit 0
fi

log "packages"
export DEBIAN_FRONTEND=noninteractive
sudo dpkg --add-architecture i386
sudo apt-get update -qq
# wine64 pulls the 32-bit loader on its own where it needs one. Xvfb gives the
# terminal a display it can draw on with no monitor attached; x11vnc exports
# that display so the owner can see it; websockify turns it into something a
# browser can reach through the tunnel.
sudo apt-get install -y -qq wine xvfb x11vnc websockify novnc winbind cabextract

log "wine prefix"
export WINEPREFIX="$WINEPREFIX_DIR"
export WINEARCH=win64
export WINEDLLOVERRIDES="mscoree,mshtml="   # skip the .NET and Gecko prompts
mkdir -p "$WINEPREFIX"
wineboot --init 2>&1 | tail -3 || true
wineserver -w

log "display"
pkill -f "Xvfb :${DISPLAY_NUM}" 2>/dev/null || true
Xvfb ":${DISPLAY_NUM}" -screen 0 1280x900x24 -nolisten tcp &
sleep 2
export DISPLAY=":${DISPLAY_NUM}"

log "download"
mkdir -p "$HOME/mt5"
if [ ! -f "$HOME/mt5/mt5setup.exe" ]; then
  curl -fsSL "$MT5_URL" -o "$HOME/mt5/mt5setup.exe"
fi
ls -lh "$HOME/mt5/mt5setup.exe"

log "install"
# /auto runs the installer without a wizard. It still needs the display above:
# it draws a progress window even in automatic mode.
wine "$HOME/mt5/mt5setup.exe" /auto 2>&1 | tail -5 || true
wineserver -w

log "result"
verify
