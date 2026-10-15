"""The dictation pipeline: microphone → VAD segmenter → Whisper → sink.

Capture runs on its own thread and buffers continuously, so the loop below
can block on transcription without dropping audio.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from voice_assistant.audio import AudioError, MicrophoneStream
from voice_assistant.config import Config
from voice_assistant.sinks import Sink
from voice_assistant.transcriber import Transcriber
from voice_assistant.vad import Segmenter

log = logging.getLogger(__name__)

POLL_SECS = 0.1


class DictationSession:
    def __init__(
        self,
        config: Config,
        transcriber: Transcriber,
        stop: threading.Event,
        stream_factory: Callable[[], MicrophoneStream] | None = None,
        segmenter_factory: Callable[[], Segmenter] | None = None,
    ):
        self.config = config
        self.transcriber = transcriber
        self.stop = stop
        sr = config.audio.sample_rate
        self._new_stream = stream_factory or (lambda: MicrophoneStream(config.audio))
        self._new_segmenter = segmenter_factory or (lambda: Segmenter(config.vad, sr))
        self.transcript: list[str] = []

    def _transcribe(self, utterance: np.ndarray) -> str:
        return self.transcriber.transcribe(utterance, prompt=" ".join(self.transcript))

    def run(self, sink: Sink, on_ready: Callable[[], None] = lambda: None) -> str:
        """Dictate until ``stop`` is set; returns the full transcript."""
        segmenter = self._new_segmenter()
        with self._new_stream() as stream:
            on_ready()
            while not self.stop.is_set():
                time.sleep(POLL_SECS)
                if not stream.alive:
                    raise AudioError("microphone stream ended unexpectedly")
                self._handle(segmenter.feed(stream.read()), sink)
            # Finish whatever was being said when stop was requested.
            stream.stop()
            self._handle(segmenter.feed(stream.read()) + segmenter.flush(), sink)
        return " ".join(self.transcript)

    def _handle(self, utterances: list[np.ndarray], sink: Sink) -> None:
        for utterance in utterances:
            text = self._transcribe(utterance)
            if text:
                self.transcript.append(text)
                sink.emit(text)

    def record_once(self, timeout_secs: float = 15.0) -> str:
        """Capture a single utterance (ends at the first pause) and transcribe it."""
        segmenter = self._new_segmenter()
        deadline = time.monotonic() + timeout_secs
        utterance = None
        with self._new_stream() as stream:
            while utterance is None and not self.stop.is_set():
                time.sleep(POLL_SECS)
                done = segmenter.feed(stream.read())
                if done:
                    utterance = done[0]
                elif not segmenter.speaking and time.monotonic() > deadline:
                    return ""
            if utterance is None:
                stream.stop()
                done = segmenter.feed(stream.read()) + segmenter.flush()
                utterance = done[0] if done else None
        return self.transcriber.transcribe(utterance) if utterance is not None else ""
