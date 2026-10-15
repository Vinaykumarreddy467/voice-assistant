#!/usr/bin/env bash
# Install voice-assistant for the current user (no root needed).
#
#   scripts/install.sh                 # venv + `voice` command + hotkey + service
#   scripts/install.sh --no-shortcut   # skip the hotkey
#
# Environment: PYTHON (default /usr/bin/python3), SHORTCUT (default Super+Shift+V)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
BIN="$HOME/.local/bin"
# System Python on purpose: a conda/pyenv python3 on PATH would build the venv
# against the wrong interpreter and hide the system PyGObject.
PYTHON="${PYTHON:-/usr/bin/python3}"
SHORTCUT="${SHORTCUT:-<Shift><Super>v}"
WITH_SHORTCUT=1
[[ "${1:-}" == "--no-shortcut" ]] && WITH_SHORTCUT=0

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
need() { command -v "$1" >/dev/null || { echo "missing '$1' — install: sudo apt install $2" >&2; exit 1; }; }

need arecord alsa-utils
need ffmpeg ffmpeg
need notify-send libnotify-bin
[[ -x "$PYTHON" ]] || { echo "Python not found at $PYTHON (set PYTHON=...)" >&2; exit 1; }

info "Creating virtualenv in $VENV"
[[ -x "$VENV/bin/python" ]] || "$PYTHON" -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet --editable "$ROOT[dev]"

info "Installing commands into $BIN"
mkdir -p "$BIN"
ln -sfn "$VENV/bin/voice" "$BIN/voice"
# Backwards-compatible name for existing hotkeys.
printf '#!/bin/sh\nexec "%s" toggle "$@"\n' "$BIN/voice" > "$BIN/voice-toggle"
chmod +x "$BIN/voice-toggle"

if ! id -nG | grep -qw input; then
    info "Not in the 'input' group: typing will use the desktop's RemoteDesktop portal"
    info "(GNOME asks once for permission). Push-to-talk needs the group."
fi

info "Setting up hotkey and background service"
if (( WITH_SHORTCUT )); then
    "$BIN/voice" setup --shortcut "$SHORTCUT"
else
    "$BIN/voice" setup --no-shortcut
fi

info "Done. Press the hotkey, or try:  voice test-mic   then   voice"
