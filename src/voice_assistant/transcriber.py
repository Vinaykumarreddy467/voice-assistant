"""Speech-to-text with faster-whisper, plus filtering of Whisper's
well-known hallucinations on noise and silence."""

from __future__ import annotations

import logging
from typing import Iterable, Protocol

import numpy as np

from voice_assistant.config import WhisperConfig

log = logging.getLogger(__name__)

MODELS = ("tiny", "base", "small", "medium", "large-v3")

# Phrases Whisper tends to "hear" in noise; dropped when they are the whole output.
HALLUCINATIONS = frozenset({
    "you", "so", ".", "...", "okay.", "bye.", "bye!", "thank you", "thank you.",
    "thanks for watching!", "thanks for watching.", "thank you for watching.",
})

MIN_AUDIO_SECS = 0.3
PROMPT_CHARS = 200


class Segment(Protocol):
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float


def is_probably_noise(seg: Segment) -> bool:
    return (seg.no_speech_prob > 0.6
            or (seg.no_speech_prob > 0.3 and seg.avg_logprob < -0.5)
            or seg.compression_ratio > 2.4)        # looping / repeated output


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


class Transcriber:
    def __init__(self, cfg: WhisperConfig, sample_rate: int = 16000):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self._model = None

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
            language=self.cfg.language,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
            initial_prompt=prompt[-PROMPT_CHARS:] or None,
        )
        return clean_segments(segments)
