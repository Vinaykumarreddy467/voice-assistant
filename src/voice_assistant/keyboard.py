"""Virtual keyboard that types text into whatever window has focus.

Uses /dev/uinput, so it works on Wayland and X11 alike; the user must be in
the ``input`` group. Keys are mapped for the US layout.
"""

from __future__ import annotations

import time
import unicodedata

_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "MINUS", "+": "EQUAL",
    "{": "LEFTBRACE", "}": "RIGHTBRACE", "|": "BACKSLASH", ":": "SEMICOLON",
    '"': "APOSTROPHE", "<": "COMMA", ">": "DOT", "?": "SLASH", "~": "GRAVE",
}
_PLAIN = {
    " ": "SPACE", "-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE",
    "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON",
    "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH", "`": "GRAVE",
    "\n": "ENTER", "\t": "TAB",
}
_ASCII_FIXUPS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": " - ", "…": "...", " ": " ",
}


def to_typeable(text: str) -> str:
    """Reduce text to characters the US virtual keyboard can produce."""
    for src, dst in _ASCII_FIXUPS.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isascii() and (c.isprintable() or c in "\n\t"))


def key_for(char: str) -> tuple[str, bool] | None:
    """Return (evdev key name, needs shift) for a typeable character."""
    if char.isascii() and char.isalpha():
        return f"KEY_{char.upper()}", char.isupper()
    if char.isascii() and char.isdigit():
        return f"KEY_{char}", False
    if char in _PLAIN:
        return f"KEY_{_PLAIN[char]}", False
    if char in _SHIFTED:
        return f"KEY_{_SHIFTED[char]}", True
    return None


class VirtualKeyboard:
    def __init__(self, key_delay: float = 0.004, settle_secs: float = 0.5):
        from evdev import UInput, ecodes

        self._e = ecodes
        self._ui = UInput(name="Voice Assistant Keyboard", phys="voice-assistant")
        self._delay = key_delay
        time.sleep(settle_secs)   # let the compositor pick up the new device

    def type(self, text: str) -> None:
        e, ui = self._e, self._ui
        for char in to_typeable(text):
            key = key_for(char)
            if key is None:
                continue
            code, shift = getattr(e, key[0]), key[1]
            if shift:
                ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
            ui.write(e.EV_KEY, code, 1)
            ui.syn()
            time.sleep(self._delay)
            ui.write(e.EV_KEY, code, 0)
            if shift:
                ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
            ui.syn()
            time.sleep(self._delay)

    def close(self) -> None:
        try:
            self._ui.close()
        except OSError:
            pass
