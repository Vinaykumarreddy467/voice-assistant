"""Persisting finished dictation sessions as timestamped text files."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

SLUG_WORDS = 5
MAX_NAME = 120


def slugify(text: str, words: int = SLUG_WORDS) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())[:words]
    return "_".join(tokens) or "dictation"


def save_transcript(text: str, directory: Path, now: float | None = None) -> Path | None:
    """Write ``text`` to a new, private (0600) file; never overwrites an older one."""
    text = text.strip()
    if not text:
        return None
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
    base = f"{stamp}_{slugify(text)}"[: MAX_NAME - 8]
    data = (text + "\n").encode()
    for n in range(1000):
        path = directory / (f"{base}.txt" if n == 0 else f"{base}-{n}.txt")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return path
    raise FileExistsError(f"too many transcripts named {base}*")
