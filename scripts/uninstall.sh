#!/usr/bin/env bash
# Remove what install.sh set up: hotkey, background service and commands.
# Keeps the virtualenv, downloaded models and your ~/Transcripts.
set -euo pipefail

BIN="$HOME/.local/bin"
[[ -x "$BIN/voice" ]] && "$BIN/voice" setup --remove
rm -f "$BIN/voice" "$BIN/voice-toggle"
echo "Uninstalled. Delete .venv/ and ~/.cache/whisper-models to free disk space."
