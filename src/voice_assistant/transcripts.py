"""Persisting finished dictation sessions as timestamped text files."""

from __future__ import annotations

import re
import time
from pathlib import Path

SLUG_WORDS = 5
MAX_NAME = 120


def slugify(text: str, words: int = SLUG_WORDS) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())[:words]
    return "_".join(tokens) or "dictation"


def save_transcript(text: str, directory: Path, now: float | None = None) -> Path | None:
    text = text.strip()
    if not text:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
    name = f"{stamp}_{slugify(text)}"[:MAX_NAME - 4] + ".txt"
    path = directory / name
    path.write_text(text + "\n")
    return path
