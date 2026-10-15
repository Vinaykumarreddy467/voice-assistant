#!/usr/bin/env bash
# Install voice-assistant for the current user (no root needed).
#
#   scripts/install.sh                 # venv + `voice` command + GNOME hotkey
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
    warn "typing into apps needs /dev/uinput access: sudo usermod -aG input $USER (then log out/in)"
fi

setup_gnome_shortcut() {
    command -v dconf >/dev/null || { warn "dconf not found; set the hotkey manually"; return; }
    local base=/org/gnome/settings-daemon/plugins/media-keys
    local list path="" p i=0
    list="$(dconf read "$base/custom-keybindings")"
    for p in $(grep -o "'[^']*'" <<<"$list" | tr -d "'"); do
        if [[ "$(dconf read "${p}command")" == *voice* ]]; then path="$p"; break; fi
    done
    if [[ -z "$path" ]]; then
        while grep -q "custom$i/" <<<"$list"; do i=$((i + 1)); done
        path="$base/custom-keybindings/custom$i/"
        if [[ -z "$list" || "$list" == "@as []" ]]; then list="['$path']"
        else list="${list%]}, '$path']"; fi
        dconf write "$base/custom-keybindings" "$list"
    fi
    dconf write "${path}name" "'Voice Dictation'"
    dconf write "${path}command" "'$BIN/voice toggle'"
    dconf write "${path}binding" "'$SHORTCUT'"
    info "Hotkey $SHORTCUT → voice toggle"
}
(( WITH_SHORTCUT )) && setup_gnome_shortcut

info "Done. Try:  voice test-mic   then   voice"
