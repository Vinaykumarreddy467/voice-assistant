"""Speech-to-text engines behind one small interface.

- :class:`WhisperTranscriber` — faster-whisper; multilingual, supports a
  vocabulary prompt; output is filtered for Whisper's typical hallucinations.
- :class:`ParakeetTranscriber` — NVIDIA Parakeet TDT via onnx-asr; English
  only, more accurate and faster than Whisper models of similar cost, with
  punctuation and capitalisation built in.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Protocol

import numpy as np

from voice_assistant.config import AsrConfig, Config, VadConfig, WhisperConfig

log = logging.getLogger(__name__)

ENGINES = ("whisper", "parakeet")
MODELS = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v3",
    "large-v3-turbo",
    "distil-small.en",
    "distil-large-v3.5",
)

# Phrases Whisper tends to "hear" in noise; dropped when they are the whole output.
HALLUCINATIONS = frozenset(
    {
        "you",
        "so",
        ".",
        "...",
        "okay.",
        "bye.",
        "bye!",
        "thank you",
        "thank you.",
        "thanks for watching!",
        "thanks for watching.",
        "thank you for watching.",
    }
)

MIN_AUDIO_SECS = 0.3
PROMPT_CHARS = 200


class Segment(Protocol):
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float


def is_probably_noise(seg: Segment) -> bool:
    return (
        seg.no_speech_prob > 0.6
        or (seg.no_speech_prob > 0.3 and seg.avg_logprob < -0.5)
        or seg.compression_ratio > 2.4
    )  # looping / repeated output


def clean_segments(segments: Iterable[Segment]) -> str:
    """Join Whisper segments, dropping noise, repeats and stock hallucinations."""
    parts: list[str] = []
    for seg in segments:
        text = seg.text.strip()
        if not text or is_probably_noise(seg):
            continue
        if parts and text == parts[-1]:
            continue
        parts.append(text)
    joined = " ".join(parts)
    return "" if joined.lower() in HALLUCINATIONS else joined


def build_prompt(vocabulary: Iterable[str], context: str) -> str | None:
    """Whisper's initial prompt: custom vocabulary first, then recent text."""
    vocab = ", ".join(vocabulary)
    prompt = (f"Glossary: {vocab}. " if vocab else "") + context[-PROMPT_CHARS:]
    return prompt.strip() or None


class SpeechToText(Protocol):
    name: str

    def load(self) -> None: ...
    def transcribe(self, audio: np.ndarray, prompt: str = "", vad_filter: bool = False) -> str: ...


class WhisperTranscriber:
    def __init__(self, cfg: WhisperConfig, sample_rate: int = 16000):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self.name = f"whisper {cfg.model}"
        self._model: Any = None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        log.info("loading Whisper model %r", self.cfg.model)
        self._model = WhisperModel(
            self.cfg.model,
            device=self.cfg.device,
            compute_type=self.cfg.compute_type,
            download_root=str(self.cfg.model_dir),
        )

    def transcribe(self, audio: np.ndarray, prompt: str = "", vad_filter: bool = False) -> str:
        """Transcribe mono float32 audio. ``prompt`` is preceding text for context."""
        if len(audio) < self.sample_rate * MIN_AUDIO_SECS:
            return ""
        self.load()
        segments, _ = self._model.transcribe(
            audio,
            beam_size=self.cfg.beam_size,
            language=None if self.cfg.language == "auto" else self.cfg.language,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
            initial_prompt=build_prompt(self.cfg.vocabulary, prompt),
        )
        return clean_segments(segments)


class ParakeetTranscriber:
    """Parakeet has a ~24 min context, but utterances longer than this are
    split at pauses first to keep memory and latency flat (file mode)."""

    MAX_CHUNK_SECS = 30.0

    def __init__(self, cfg: AsrConfig, sample_rate: int = 16000):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self.name = cfg.parakeet_model
        self._model: Any = None

    def load(self) -> None:
        if self._model is not None:
            return
        import onnx_asr

        quantization = self.cfg.quantization or None
        if quantization in ("none", "fp32"):
            quantization = None
        log.info("loading %s (%s)", self.cfg.parakeet_model, quantization or "fp32")
        self._model = onnx_asr.load_model(self.cfg.parakeet_model, quantization=quantization)

    def _chunks(self, audio: np.ndarray) -> list[np.ndarray]:
        if len(audio) <= self.MAX_CHUNK_SECS * self.sample_rate:
            return [audio]
        from voice_assistant.vad import Segmenter

        seg = Segmenter(VadConfig(max_utterance_secs=self.MAX_CHUNK_SECS), self.sample_rate)
        return seg.feed(audio) + seg.flush()

    def transcribe(self, audio: np.ndarray, prompt: str = "", vad_filter: bool = False) -> str:
        """``prompt`` is accepted for interface compatibility; Parakeet ignores it."""
        if len(audio) < self.sample_rate * MIN_AUDIO_SECS:
            return ""
        self.load()
        parts = [
            str(self._model.recognize(chunk, sample_rate=self.sample_rate)).strip()
            for chunk in self._chunks(audio.astype(np.float32, copy=False))
        ]
        return " ".join(p for p in parts if p)


def make_transcriber(config: Config) -> SpeechToText:
    sr = config.audio.sample_rate
    if config.asr.engine == "parakeet":
        return ParakeetTranscriber(config.asr, sr)
    if config.asr.engine == "whisper":
        return WhisperTranscriber(config.whisper, sr)
    raise ValueError(f"unknown engine {config.asr.engine!r} (choose from {', '.join(ENGINES)})")


# Backwards-compatible name
Transcriber = WhisperTranscriber
