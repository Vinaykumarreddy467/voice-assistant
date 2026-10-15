"""Where transcribed text goes: the terminal, the focused app, or the clipboard.

``emit`` outputs text exactly as given and returns how many characters it
produced, so a later ``delete`` ("scratch that") can remove them again.
"""

from __future__ import annotations

import logging
from typing import Protocol

from voice_assistant import desktop
from voice_assistant.keyboard import to_typeable

log = logging.getLogger(__name__)


class Sink(Protocol):
    def emit(self, text: str) -> int: ...
    def delete(self, count: int) -> None: ...
    def close(self) -> None: ...


class TerminalSink:
    def emit(self, text: str) -> int:
        print(f"  {text.strip()}", flush=True)
        return len(text)

    def delete(self, count: int) -> None:
        print("  ✂️  (scratched)", flush=True)

    def close(self) -> None:
        pass


class KeyboardSink:
    """Types each utterance into the focused window."""

    def __init__(self, key_delay: float):
        from voice_assistant.keyboard import VirtualKeyboard

        self._keyboard = VirtualKeyboard(key_delay=key_delay)

    def emit(self, text: str) -> int:
        typed = to_typeable(text)
        self._keyboard.type(typed)
        print(f"  ⌨️  {text.strip()}", flush=True)
        return len(typed)

    def delete(self, count: int) -> None:
        self._keyboard.backspace(count)
        print("  ✂️  (scratched)", flush=True)

    def close(self) -> None:
        self._keyboard.close()


class ClipboardSink:
    """Fallback when no virtual keyboard is available."""

    def emit(self, text: str) -> int:
        desktop.copy_to_clipboard(text)
        desktop.notify(f"'{text.strip()[:60]}'  Press Ctrl+V to paste")
        print(f"  📋  {text.strip()}", flush=True)
        return 0

    def delete(self, count: int) -> None:
        pass

    def close(self) -> None:
        pass


def typing_sink(key_delay: float) -> Sink:
    try:
        return KeyboardSink(key_delay)
    except Exception as exc:  # no evdev / no /dev/uinput permission
        log.warning(
            "virtual keyboard unavailable (%s); falling back to clipboard. "
            "Is your user in the 'input' group?",
            exc,
        )
        return ClipboardSink()
