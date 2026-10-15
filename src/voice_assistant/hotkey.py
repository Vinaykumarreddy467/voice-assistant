"""Push-to-talk: hold a key on any physical keyboard to dictate.

Reads keyboards through evdev (needs the ``input`` group), so it works on
Wayland where applications cannot grab global keys. The key still reaches
the focused app, so pick one that is harmless on its own (e.g. Right Ctrl).
"""

from __future__ import annotations

import logging
import selectors
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class PushToTalk:
    def __init__(
        self, key_name: str, on_press: Callable[[], object], on_release: Callable[[], object]
    ):
        from evdev import ecodes

        if not hasattr(ecodes, key_name):
            raise ValueError(f"unknown key {key_name!r} (see `python -m evdev.evtest`)")
        self.code = getattr(ecodes, key_name)
        self.key_name = key_name
        self.on_press = on_press
        self.on_release = on_release

    def _keyboards(self):
        from evdev import InputDevice, ecodes, list_devices

        found = []
        for path in list_devices():
            try:
                dev = InputDevice(path)
            except OSError:
                continue
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            if self.code in keys and "voice-assistant" not in (dev.phys or ""):
                found.append(dev)
            else:
                dev.close()
        return found

    def start(self) -> None:
        keyboards = self._keyboards()
        if not keyboards:
            log.warning("push-to-talk: no keyboard with %s found (input group?)", self.key_name)
            return
        threading.Thread(
            target=self._loop, args=(keyboards,), name="push-to-talk", daemon=True
        ).start()
        log.info("push-to-talk on %s (%d keyboards)", self.key_name, len(keyboards))

    def _loop(self, keyboards) -> None:
        from evdev import ecodes

        sel = selectors.DefaultSelector()
        for dev in keyboards:
            sel.register(dev, selectors.EVENT_READ, data=dev)
        while True:
            for key, _ in sel.select():
                try:
                    events = list(key.data.read())
                except OSError:  # keyboard unplugged
                    sel.unregister(key.data)
                    continue
                for ev in events:
                    if ev.type != ecodes.EV_KEY or ev.code != self.code:
                        continue
                    if ev.value == 1:
                        self.on_press()
                    elif ev.value == 0:
                        self.on_release()
