"""Utterance segmentation with the Silero VAD bundled in faster-whisper.

The live stream is fed in arbitrary-sized chunks; :meth:`Segmenter.feed`
returns every utterance (speech followed by a pause) completed so far.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from voice_assistant.config import VadConfig

FRAME = 512             # samples per Silero frame (32 ms at 16 kHz)
CONTEXT_FRAMES = 16     # history re-fed with each call so the model is warmed up

VadModel = Callable[[np.ndarray], np.ndarray]


def default_vad_model() -> VadModel:
    from faster_whisper.vad import get_vad_model

    return get_vad_model()


class Segmenter:
    def __init__(self, cfg: VadConfig, sample_rate: int, model: VadModel | None = None):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self.model = model or default_vad_model()
        self.frame_secs = FRAME / sample_rate
        self._pending = np.zeros(0, np.float32)            # not yet classified
        self._history = np.zeros(CONTEXT_FRAMES * FRAME, np.float32)
        self._pre_roll = np.zeros(0, np.float32)
        self._pre_roll_len = int(cfg.pre_roll_secs * sample_rate)
        self._max_frames = int(cfg.max_utterance_secs / self.frame_secs)
        self._reset()

    def _reset(self) -> None:
        self._frames: list[np.ndarray] = []
        self._speaking = False
        self._speech_frames = 0
        self._silence_frames = 0

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _probabilities(self, frames: np.ndarray) -> np.ndarray:
        audio = np.concatenate([self._history, frames])
        probs = np.asarray(self.model(audio)).reshape(-1)
        self._history = audio[-len(self._history):]
        return probs[-(len(frames) // FRAME):]

    def _finish(self, out: list[np.ndarray]) -> None:
        audio = np.concatenate(self._frames)
        tail = self._silence_frames * FRAME - int(0.2 * self.sample_rate)
        if tail > 0:
            audio = audio[:-tail]          # keep ~0.2 s of trailing silence
        if self._speech_frames * self.frame_secs >= self.cfg.min_speech_secs:
            out.append(audio)
        self._reset()

    def feed(self, audio: np.ndarray) -> list[np.ndarray]:
        done: list[np.ndarray] = []
        self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        n = len(self._pending) // FRAME * FRAME
        if n == 0:
            return done
        frames, self._pending = self._pending[:n], self._pending[n:]

        for i, p in enumerate(self._probabilities(frames)):
            frame = frames[i * FRAME:(i + 1) * FRAME]
            if not self._speaking:
                if p >= self.cfg.speech_prob:
                    self._speaking = True
                    self._frames = [self._pre_roll, frame]
                    self._speech_frames = 1
                else:
                    self._pre_roll = np.concatenate([self._pre_roll, frame])[-self._pre_roll_len:]
                continue

            self._frames.append(frame)
            if p < self.cfg.silence_prob:
                self._silence_frames += 1
            else:
                self._speech_frames += 1
                self._silence_frames = 0
            if (self._silence_frames * self.frame_secs >= self.cfg.end_silence_secs
                    or len(self._frames) >= self._max_frames):
                self._finish(done)
                self._pre_roll = frame[-self._pre_roll_len:]
        return done

    def flush(self) -> list[np.ndarray]:
        """Close any utterance in progress (call when the stream ends)."""
        done: list[np.ndarray] = []
        if self._speaking:
            self._finish(done)
        return done
