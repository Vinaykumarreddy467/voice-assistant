"""Top-bar icon (AppIndicator) for the daemon, with a plain fallback.

Needs PyGObject with AyatanaAppIndicator3 and, on GNOME, the AppIndicator
shell extension (enabled by default on Ubuntu). Without them the daemon runs
headless and still reports state through notifications.
"""

from __future__ import annotations

import logging
import signal
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from voice_assistant.daemon import Daemon

log = logging.getLogger(__name__)

ICON_IDLE = "microphone-sensitivity-muted-symbolic"
ICON_LISTENING = "audio-input-microphone-symbolic"


def _run_headless(daemon: Daemon) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: daemon.quit_event.set())
    daemon.quit_event.wait()


def run_with_indicator(daemon: Daemon) -> None:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
        from gi.repository import GLib, Gtk
    except (ImportError, ValueError) as exc:
        log.info("no top-bar icon (%s); running headless", exc)
        _run_headless(daemon)
        return

    indicator = AppIndicator.Indicator.new(
        "voice-assistant", ICON_IDLE, AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    indicator.set_title("Voice Dictation")

    menu = Gtk.Menu()
    toggle_item = Gtk.MenuItem(label="Start dictation")
    # toggle() may block while the last utterance is transcribed: keep it off the UI thread
    toggle_item.connect(
        "activate", lambda *_: threading.Thread(target=daemon.toggle, daemon=True).start()
    )
    quit_item = Gtk.MenuItem(label="Quit")
    quit_item.connect("activate", lambda *_: daemon.quit_event.set())
    menu.append(toggle_item)
    menu.append(Gtk.SeparatorMenuItem())
    menu.append(quit_item)
    menu.show_all()
    indicator.set_menu(menu)

    def refresh(listening: bool) -> bool:
        indicator.set_icon_full(
            ICON_LISTENING if listening else ICON_IDLE, "Listening" if listening else "Idle"
        )
        toggle_item.set_label("Stop dictation" if listening else "Start dictation")
        return False

    daemon.on_change(lambda listening: GLib.idle_add(refresh, listening))

    loop = GLib.MainLoop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: daemon.quit_event.set() or True)

    def watch_quit() -> bool:
        if daemon.quit_event.is_set():
            loop.quit()
            return False
        return True

    GLib.timeout_add(200, watch_quit)
    loop.run()
