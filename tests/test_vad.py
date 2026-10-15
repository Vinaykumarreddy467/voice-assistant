import numpy as np
import pytest

from voice_assistant.config import VadConfig
from voice_assistant.vad import FRAME, Segmenter

SR = 16000


def energy_vad(audio: np.ndarray) -> np.ndarray:
    """Fake Silero: a frame is 'speech' when it is loud."""
    frames = audio.reshape(-1, FRAME)
    return (np.abs(frames).mean(axis=1) > 0.1).astype(np.float32)


def tone(secs: float) -> np.ndarray:
    t = np.arange(int(secs * SR)) / SR
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def silence(secs: float) -> np.ndarray:
    return np.zeros(int(secs * SR), np.float32)


def feed_in_chunks(seg: Segmenter, audio: np.ndarray, chunk: int = 1600):
    out = []
    for i in range(0, len(audio), chunk):
        out += seg.feed(audio[i : i + chunk])
    return out


@pytest.fixture
def seg():
    return Segmenter(VadConfig(), SR, model=energy_vad)


def test_two_utterances_separated_by_pause(seg):
    audio = np.concatenate([silence(1), tone(1.5), silence(1.2), tone(2.0), silence(1.2)])
    utts = feed_in_chunks(seg, audio)
    assert len(utts) == 2
    assert 1.5 <= len(utts[0]) / SR <= 2.3
    assert 2.0 <= len(utts[1]) / SR <= 2.8


def test_silence_produces_nothing(seg):
    assert feed_in_chunks(seg, silence(5)) == []
    assert seg.flush() == []


def test_short_blip_is_ignored(seg):
    audio = np.concatenate([silence(0.5), tone(0.1), silence(1.5)])
    assert feed_in_chunks(seg, audio) == []


def test_flush_returns_utterance_in_progress(seg):
    assert feed_in_chunks(seg, np.concatenate([silence(0.5), tone(1.0)])) == []
    assert seg.speaking
    assert len(seg.flush()) == 1
    assert not seg.speaking


def test_long_monologue_is_cut(seg):
    utts = feed_in_chunks(seg, np.concatenate([tone(35), silence(1.0)]))
    assert len(utts) >= 3
    assert all(len(u) / SR <= VadConfig().max_utterance_secs + 1 for u in utts)


def test_chunk_size_does_not_matter():
    audio = np.concatenate([silence(0.7), tone(1.0), silence(1.0), tone(1.0), silence(1.0)])
    a = feed_in_chunks(Segmenter(VadConfig(), SR, model=energy_vad), audio, 333)
    b = feed_in_chunks(Segmenter(VadConfig(), SR, model=energy_vad), audio, 4096)
    assert [len(u) for u in a] == [len(u) for u in b]
