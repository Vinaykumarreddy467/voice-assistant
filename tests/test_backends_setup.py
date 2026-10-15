import pytest

from voice_assistant import setup
from voice_assistant.portal import keysym_for
from voice_assistant.sinks import KeyboardSink, make_keyboard, printable


@pytest.mark.parametrize(
    "char,keysym",
    [
        ("a", 0x61),
        ("A", 0x41),
        ("?", 0x3F),
        ("é", 0xE9),  # Latin-1 maps directly
        ("€", 0x010020AC),  # everything else: 0x01000000 + code point
        ("\n", 0xFF0D),
        ("\x07", None),
    ],
)
def test_keysym_for(char, keysym):
    assert keysym_for(char) == keysym


def test_printable_keeps_unicode_and_breaks():
    assert printable("café\n\x07ok") == "café\nok"


class FakeKeyboard:
    def __init__(self):
        self.typed, self.deleted = "", 0

    def type(self, text):
        self.typed += text

    def backspace(self, count):
        self.deleted += count

    def close(self):
        pass


def test_keyboard_sink_counts_what_it_typed():
    kb = FakeKeyboard()
    sink = KeyboardSink(kb)  # default: US-layout ASCII preparation
    assert sink.emit("Café “ok” ") == len('Cafe "ok" ')
    sink.delete(3)
    assert kb.typed == 'Cafe "ok" ' and kb.deleted == 3


def test_unknown_keyboard_backend():
    with pytest.raises(ValueError):
        make_keyboard("telepathy", 0.0)


@pytest.mark.parametrize(
    "gnome,kde",
    [
        ("<Shift><Super>v", "Meta+Shift+V"),
        ("<Control><Alt>d", "Ctrl+Alt+D"),
        ("<Primary>space", "Ctrl+SPACE"),
    ],
)
def test_gnome_to_kde_binding(gnome, kde):
    assert setup._gnome_to_kde(gnome) == kde


def test_dconf_list_roundtrip():
    paths = ["/a/custom0/", "/a/custom1/"]
    assert setup._dconf_list(setup._dconf_format(paths)) == paths
    assert setup._dconf_format([]) == "@as []"
    assert setup._dconf_list("@as []") == []


def test_service_unit_points_at_voice():
    unit = setup.SERVICE_TEMPLATE.format(voice="/home/u/.local/bin/voice")
    assert "ExecStart=/home/u/.local/bin/voice daemon" in unit
    assert "WantedBy=graphical-session.target" in unit
