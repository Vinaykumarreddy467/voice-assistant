"""Where transcribed text goes: the terminal, the focused app, or the clipboard.

``emit`` outputs text exactly as given and returns how many characters it
produced, so a later ``delete`` ("scratch that") can remove them again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
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


class Keyboard(Protocol):
    def type(self, text: str) -> None: ...
    def backspace(self, count: int) -> None: ...
    def close(self) -> None: ...


def printable(text: str) -> str:
    """For layout-aware backends: keep Unicode, drop control characters."""
    return "".join(c for c in text if c.isprintable() or c in "\n\t")


class KeyboardSink:
    """Types each utterance into the focused window."""

    def __init__(self, keyboard: Keyboard, prepare: Callable[[str], str] = to_typeable):
        self._keyboard = keyboard
        self._prepare = prepare

    def emit(self, text: str) -> int:
        typed = self._prepare(text)
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


def make_keyboard(backend: str, key_delay: float) -> KeyboardSink:
    """Build the requested keyboard backend ("auto", "uinput" or "portal")."""
    if backend not in ("auto", "uinput", "portal"):
        raise ValueError(f"unknown keyboard backend {backend!r}")
    if backend in ("auto", "uinput"):
        try:
            from voice_assistant.keyboard import VirtualKeyboard

            return KeyboardSink(VirtualKeyboard(key_delay=key_delay))
        except Exception as exc:  # no evdev / no /dev/uinput permission
            if backend == "uinput":
                raise
            log.info("uinput unavailable (%s); trying the RemoteDesktop portal", exc)
    from voice_assistant.portal import PortalKeyboard

    return KeyboardSink(PortalKeyboard(key_delay=key_delay), prepare=printable)


def typing_sink(key_delay: float, backend: str = "auto") -> Sink:
    try:
        return make_keyboard(backend, key_delay)
    except Exception as exc:
        log.warning("no way to type into apps (%s); falling back to the clipboard", exc)
        return ClipboardSink()
