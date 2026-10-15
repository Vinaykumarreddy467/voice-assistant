#!/usr/bin/env bash
# Remove the commands and GNOME hotkey created by install.sh.
# Keeps the virtualenv, downloaded models and your ~/Transcripts.
set -euo pipefail

BIN="$HOME/.local/bin"
rm -f "$BIN/voice" "$BIN/voice-toggle"

if command -v dconf >/dev/null; then
    base=/org/gnome/settings-daemon/plugins/media-keys
    list="$(dconf read "$base/custom-keybindings")"
    for p in $(grep -o "'[^']*'" <<<"$list" | tr -d "'"); do
        if [[ "$(dconf read "${p}command")" == *voice* ]]; then
            dconf reset -f "$p"
            list="$(sed -e "s|, '$p'||; s|'$p', ||; s|'$p'||" <<<"$list")"
        fi
    done
    [[ "$list" == "[]" ]] && list="@as []"
    dconf write "$base/custom-keybindings" "$list"
fi
echo "Uninstalled. Delete .venv/ and ~/.cache/whisper-models to free disk space."
