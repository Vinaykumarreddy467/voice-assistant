"""The dictation pipeline:

    microphone → VAD segmenter → Whisper → voice commands → (LLM cleanup) → sink

Capture runs on its own thread and buffers continuously, so the loop below
can block on transcription without dropping audio.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from voice_assistant import commands
from voice_assistant.audio import AudioError, MicrophoneStream
from voice_assistant.config import Config
from voice_assistant.sinks import Sink
from voice_assistant.transcriber import Transcriber
from voice_assistant.vad import Segmenter

log = logging.getLogger(__name__)

POLL_SECS = 0.1
Cleaner = Callable[[str], str]


class DictationSession:
    def __init__(
        self,
        config: Config,
        transcriber: Transcriber,
        stop: threading.Event,
        cleaner: Cleaner | None = None,
        stream_factory: Callable[[], MicrophoneStream] | None = None,
        segmenter_factory: Callable[[], Segmenter] | None = None,
    ):
        self.config = config
        self.transcriber = transcriber
        self.stop = stop
        self.cleaner = cleaner
        sr = config.audio.sample_rate
        self._new_stream = stream_factory or (lambda: MicrophoneStream(config.audio))
        self._new_segmenter = segmenter_factory or (lambda: Segmenter(config.vad, sr))
        self.transcript: list[str] = []
        self._emitted: list[int] = []  # chars produced per utterance, for undo

    def run(self, sink: Sink, on_ready: Callable[[], None] = lambda: None) -> str:
        """Dictate until ``stop`` is set; returns the full transcript."""
        self.transcript, self._emitted = [], []
        segmenter = self._new_segmenter()
        with self._new_stream() as stream:
            stream.wait_ready()
            on_ready()
            while not self.stop.is_set():
                time.sleep(POLL_SECS)
                if not stream.alive:
                    raise AudioError("microphone stream ended unexpectedly")
                self._handle(segmenter.feed(stream.read()), sink)
            # Finish whatever was being said when stop was requested.
            stream.stop()
            self._handle(segmenter.feed(stream.read()) + segmenter.flush(), sink)
        return " ".join(self.transcript).replace(" \n", "\n").strip()

    def _polish(self, text: str) -> str:
        if not self.cleaner:
            return text
        return "".join(
            p if p.startswith("\n") else self.cleaner(p) for p in commands.split_breaks(text)
        )

    def _handle(self, utterances: list[np.ndarray], sink: Sink) -> None:
        for utterance in utterances:
            raw = self.transcriber.transcribe(utterance, prompt=" ".join(self.transcript))
            if not raw:
                continue
            parsed = commands.parse(raw)
            if parsed.action is commands.Action.UNDO:
                if self._emitted:
                    sink.delete(self._emitted.pop())
                    self.transcript.pop()
                continue
            if parsed.action is commands.Action.STOP:
                self.stop.set()
                continue
            text = self._polish(parsed.text).strip(" ")
            if not text.strip():
                continue
            out = text if text.endswith("\n") else text + " "
            self._emitted.append(sink.emit(out))
            self.transcript.append(text)

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
        if utterance is None:
            return ""
        return self._polish(self.transcriber.transcribe(utterance))
