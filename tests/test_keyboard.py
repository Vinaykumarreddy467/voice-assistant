import pytest

from voice_assistant.keyboard import key_for, to_typeable


def test_to_typeable_normalises_unicode():
    assert to_typeable("It’s “great” — café…") == 'It\'s "great"  -  cafe...'


def test_to_typeable_drops_untypeable():
    assert to_typeable("naïve 日本 ok") == "naive  ok"


@pytest.mark.parametrize(
    "char,expected",
    [
        ("a", ("KEY_A", False)),
        ("A", ("KEY_A", True)),
        ("7", ("KEY_7", False)),
        ("?", ("KEY_SLASH", True)),
        (",", ("KEY_COMMA", False)),
        (" ", ("KEY_SPACE", False)),
        ('"', ("KEY_APOSTROPHE", True)),
    ],
)
def test_key_for(char, expected):
    assert key_for(char) == expected


def test_every_typeable_ascii_char_has_a_key():
    evdev = pytest.importorskip("evdev")
    for code in range(32, 127):
        key = key_for(chr(code))
        assert key is not None, repr(chr(code))
        assert hasattr(evdev.ecodes, key[0]), key
