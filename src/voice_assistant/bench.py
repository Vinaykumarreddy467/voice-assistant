"""Accuracy/speed benchmark: ``voice bench DIR``.

DIR holds audio files plus their correct transcripts, either as a
``refs.json`` mapping file name → text, or as ``<name>.txt`` next to each
audio file. Reports word error rate (WER), real-time factor and peak memory
for the configured engine — run it once per engine/model to compare.
"""

from __future__ import annotations

import json
import re
import resource
import time
from dataclasses import dataclass
from pathlib import Path

from voice_assistant.audio import load_file
from voice_assistant.transcriber import SpeechToText

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".webm"}


def normalize(text: str) -> list[str]:
    """Lower-case words without punctuation, so formatting isn't counted as errors."""
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return [w.strip("'") for w in text.split() if w.strip("'")]


def word_errors(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance over words (substitutions + insertions + deletions)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def load_dataset(directory: Path) -> list[tuple[Path, str]]:
    refs_file = directory / "refs.json"
    if refs_file.is_file():
        refs = json.loads(refs_file.read_text())
        return [(directory / name, text) for name, text in sorted(refs.items())]
    items = []
    for audio in sorted(directory.iterdir()):
        txt = audio.with_suffix(".txt")
        if audio.suffix.lower() in AUDIO_SUFFIXES and txt.is_file():
            items.append((audio, txt.read_text().strip()))
    return items


@dataclass
class Result:
    words: int = 0
    errors: int = 0
    audio_secs: float = 0.0
    compute_secs: float = 0.0
    load_secs: float = 0.0
    peak_mb: float = 0.0

    @property
    def wer(self) -> float:
        return self.errors / max(self.words, 1)

    @property
    def rtf(self) -> float:
        """Compute time per second of audio (lower is faster; <1 is faster than real time)."""
        return self.compute_secs / max(self.audio_secs, 1e-9)


def run(transcriber: SpeechToText, directory: Path, sample_rate: int, verbose: bool) -> Result:
    items = load_dataset(directory)
    if not items:
        raise FileNotFoundError(f"no audio with reference transcripts in {directory}")
    result = Result()
    t = time.perf_counter()
    transcriber.load()
    result.load_secs = time.perf_counter() - t
    for path, ref_text in items:
        audio = load_file(path, sample_rate)
        t = time.perf_counter()
        hyp_text = transcriber.transcribe(audio)
        result.compute_secs += time.perf_counter() - t
        result.audio_secs += len(audio) / sample_rate
        ref, hyp = normalize(ref_text), normalize(hyp_text)
        errors = word_errors(ref, hyp)
        result.words += len(ref)
        result.errors += errors
        if verbose and errors:
            print(f"  {path.name}: {errors} errors\n    ref: {ref_text}\n    got: {hyp_text}")
    result.peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return result
