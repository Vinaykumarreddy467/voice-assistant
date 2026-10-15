import time

import numpy as np

from voice_assistant.audio import HighPass, pcm16_to_float
from voice_assistant.transcripts import save_transcript, slugify


def test_highpass_removes_dc_and_keeps_speech_band():
    sr = 16000
    t = np.arange(sr) / sr
    dc = np.full(sr, 0.3, np.float32)
    voice = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    hp = HighPass(100, sr)
    out = np.concatenate([hp(c) for c in np.split(dc + voice, 10)])   # chunked
    assert abs(out[sr // 2:].mean()) < 0.01
    assert 0.18 < out[sr // 2:].std() < 0.23


def test_pcm16_to_float():
    data = np.array([0, 16384, -32768], "<i2").tobytes()
    assert pcm16_to_float(data).tolist() == [0.0, 0.5, -1.0]


def test_slugify():
    assert slugify("Hello, this is a quick test today!") == "hello_this_is_a_quick"
    assert slugify("!!!") == "dictation"


def test_save_transcript(tmp_path):
    now = time.mktime((2026, 1, 2, 3, 4, 5, 0, 0, -1))
    path = save_transcript("  Hello world.  ", tmp_path, now=now)
    assert path.name == "2026-01-02_03-04-05_hello_world.txt"
    assert path.read_text() == "Hello world.\n"
    assert save_transcript("   ", tmp_path) is None
