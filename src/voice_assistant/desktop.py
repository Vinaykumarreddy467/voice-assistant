"""Desktop integration: notifications and clipboard (best effort, never raises)."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)


def notify(body: str, timeout_ms: int = 3000, title: str = "Voice Dictation") -> None:
    try:
        subprocess.run(["notify-send", "-t", str(timeout_ms), title, body],
                       timeout=5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.debug("notify-send unavailable")


def _gtk_copy(text: str) -> bool:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gtk

        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        clip.store()
        return True
    except Exception:  # PyGObject missing or no display
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text using wl-copy, xclip or GTK, whichever works first."""
    if not text.strip():
        return False
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        try:
            if subprocess.run(cmd, input=text, text=True, capture_output=True,
                              timeout=2).returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return _gtk_copy(text)
