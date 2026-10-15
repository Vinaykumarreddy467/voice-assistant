"""Where transcribed text goes: the terminal, the focused app, or the clipboard."""

from __future__ import annotations

import logging
from typing import Protocol

from voice_assistant import desktop

log = logging.getLogger(__name__)


class Sink(Protocol):
    def emit(self, text: str) -> None: ...
    def close(self) -> None: ...


class TerminalSink:
    def emit(self, text: str) -> None:
        print(f"  {text}", flush=True)

    def close(self) -> None:
        pass


class KeyboardSink:
    """Types each utterance into the focused window."""

    def __init__(self, key_delay: float):
        from voice_assistant.keyboard import VirtualKeyboard

        self._keyboard = VirtualKeyboard(key_delay=key_delay)

    def emit(self, text: str) -> None:
        self._keyboard.type(text + " ")
        print(f"  ⌨️  {text}", flush=True)

    def close(self) -> None:
        self._keyboard.close()


class ClipboardSink:
    """Fallback when no virtual keyboard is available."""

    def emit(self, text: str) -> None:
        desktop.copy_to_clipboard(text)
        desktop.notify(f"'{text[:60]}'  Press Ctrl+V to paste")
        print(f"  📋  {text}", flush=True)

    def close(self) -> None:
        pass


def typing_sink(key_delay: float) -> Sink:
    try:
        return KeyboardSink(key_delay)
    except Exception as exc:  # no evdev / no /dev/uinput permission
        log.warning("virtual keyboard unavailable (%s); falling back to clipboard. "
                    "Is your user in the 'input' group?", exc)
        return ClipboardSink()
