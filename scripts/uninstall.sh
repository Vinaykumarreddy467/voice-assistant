#!/usr/bin/env bash
# Remove the commands and GNOME hotkey created by install.sh.
# Keeps the virtualenv, downloaded models and your ~/Transcripts.
set -euo pipefail

BIN="$HOME/.local/bin"
if command -v systemctl >/dev/null; then
    systemctl --user disable --now voice-assistant.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/voice-assistant.service"
    systemctl --user daemon-reload 2>/dev/null || true
fi
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
