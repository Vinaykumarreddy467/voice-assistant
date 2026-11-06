"""Utterance segmentation with the Silero VAD bundled in faster-whisper.

The live stream is fed in arbitrary-sized chunks; :meth:`Segmenter.feed`
returns every utterance (speech followed by a pause) completed so far.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from voice_assistant.config import VadConfig

FRAME = 512  # samples per Silero frame (32 ms at 16 kHz)
CONTEXT = 64  # samples of the previous frame Silero sees with each frame
CONTEXT_FRAMES = 16  # warm-up history for stateless models (see Segmenter)
SPLIT_SEARCH_SECS = 1.5  # where to look for a pause when an utterance is too long

VadModel = Callable[[np.ndarray], np.ndarray]


class StreamingSileroVAD:
    """Silero VAD that carries its recurrent state across calls.

    faster-whisper's wrapper resets the model state on every call, which
    forces callers to re-feed history. Keeping ``h``/``c`` and the 64-sample
    context makes chunked processing identical to one long pass at a fraction
    of the cost.
    """

    stateful = True

    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model

        self._session = get_vad_model().session
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), np.float32)
        self._c = np.zeros((1, 1, 128), np.float32)
        self._context = np.zeros(CONTEXT, np.float32)

    def __call__(self, frames: np.ndarray) -> np.ndarray:
        batch = frames.astype(np.float32, copy=False).reshape(-1, FRAME)
        contexts = np.concatenate([self._context[None, :], batch[:-1, -CONTEXT:]], axis=0)
        inputs = np.concatenate([contexts, batch], axis=1)
        out, self._h, self._c = self._session.run(
            None, {"input": inputs, "h": self._h, "c": self._c}
        )
        self._context = batch[-1, -CONTEXT:].copy()
        return np.asarray(out).reshape(-1)


def default_vad_model() -> VadModel:
    return StreamingSileroVAD()


def _tail(audio: np.ndarray, n: int) -> np.ndarray:
    """Last ``n`` samples (``a[-0:]`` would be the whole array)."""
    return audio[len(audio) - n :] if n > 0 else audio[:0]


class Segmenter:
    def __init__(self, cfg: VadConfig, sample_rate: int, model: VadModel | None = None):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self.model = model or default_vad_model()
        self._stateful = bool(getattr(self.model, "stateful", False))
        self.frame_secs = FRAME / sample_rate
        self._pending = np.zeros(0, np.float32)  # not yet classified
        self._history = np.zeros(CONTEXT_FRAMES * FRAME, np.float32)
        self._pre_roll = np.zeros(0, np.float32)
        self._pre_roll_len = int(cfg.pre_roll_secs * sample_rate)
        self._max_frames = max(1, int(cfg.max_utterance_secs / self.frame_secs))
        self._reset()

    def _reset(self) -> None:
        self._lead = np.zeros(0, np.float32)  # pre-roll captured at speech onset
        self._frames: list[np.ndarray] = []
        self._probs: list[float] = []
        self._speaking = False
        self._speech_frames = 0
        self._silence_frames = 0

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _probabilities(self, frames: np.ndarray) -> np.ndarray:
        if self._stateful:
            return np.asarray(self.model(frames)).reshape(-1)
        # Stateless model: re-feed recent history so it isn't "cold" each call.
        audio = np.concatenate([self._history, frames])
        probs = np.asarray(self.model(audio)).reshape(-1)
        self._history = _tail(audio, len(self._history))
        return probs[-(len(frames) // FRAME) :]

    def _emit(self, frames: list[np.ndarray], speech_frames: int, out: list[np.ndarray]) -> None:
        if speech_frames * self.frame_secs >= self.cfg.min_speech_secs:
            out.append(np.concatenate([self._lead, *frames]))
        self._lead = np.zeros(0, np.float32)

    def _finish(self, out: list[np.ndarray]) -> None:
        """Close the utterance after a pause, keeping ~0.2 s of trailing silence."""
        keep_tail = int(0.2 * self.sample_rate / FRAME)
        drop = max(0, self._silence_frames - keep_tail)
        frames = self._frames[: len(self._frames) - drop]
        self._emit(frames, self._speech_frames, out)
        self._reset()

    def _split_long(self, out: list[np.ndarray]) -> None:
        """Utterance hit the length limit: cut at the quietest recent frame so
        words aren't split, and carry the rest into the next utterance."""
        window = min(len(self._probs), max(1, int(SPLIT_SEARCH_SECS / self.frame_secs)))
        start = len(self._probs) - window
        cut = start + int(np.argmin(self._probs[start:])) + 1
        head, rest = self._frames[:cut], self._frames[cut:]
        head_probs, rest_probs = self._probs[:cut], self._probs[cut:]
        speech = sum(p >= self.cfg.silence_prob for p in head_probs)
        self._emit(head, speech, out)
        self._frames, self._probs = rest, rest_probs
        self._speech_frames = sum(p >= self.cfg.silence_prob for p in rest_probs)
        silence = 0
        for p in reversed(rest_probs):
            if p >= self.cfg.silence_prob:
                break
            silence += 1
        self._silence_frames = silence

    def feed(self, audio: np.ndarray) -> list[np.ndarray]:
        done: list[np.ndarray] = []
        self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        n = len(self._pending) // FRAME * FRAME
        if n == 0:
            return done
        frames, self._pending = self._pending[:n], self._pending[n:]

        for i, p in enumerate(self._probabilities(frames)):
            frame = frames[i * FRAME : (i + 1) * FRAME]
            if not self._speaking:
                if p >= self.cfg.speech_prob:
                    self._speaking = True
                    self._lead = self._pre_roll
                    self._frames, self._probs = [frame], [float(p)]
                    self._speech_frames, self._silence_frames = 1, 0
                else:
                    self._pre_roll = _tail(
                        np.concatenate([self._pre_roll, frame]), self._pre_roll_len
                    )
                continue

            self._frames.append(frame)
            self._probs.append(float(p))
            if p < self.cfg.silence_prob:
                self._silence_frames += 1
            else:
                self._speech_frames += 1
                self._silence_frames = 0
            if self._silence_frames * self.frame_secs >= self.cfg.end_silence_secs:
                self._finish(done)
                self._pre_roll = _tail(frame, self._pre_roll_len)
            elif len(self._frames) >= self._max_frames:
                self._split_long(done)
        return done

    def flush(self) -> list[np.ndarray]:
        """Close any utterance in progress (call when the stream ends)."""
        done: list[np.ndarray] = []
        if self._speaking:
            self._finish(done)
        return done
