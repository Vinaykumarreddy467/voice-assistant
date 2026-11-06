"""Spoken editing commands recognised in dictated text.

Inline:  "new line", "new paragraph"            → line breaks
Whole utterance:  "scratch that" / "delete that" → remove the previous utterance
                  "stop dictation" / "stop listening" → end the session
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Action(Enum):
    NONE = "none"
    UNDO = "undo"
    STOP = "stop"


_WHOLE = {
    "scratch that": Action.UNDO,
    "delete that": Action.UNDO,
    "undo that": Action.UNDO,
    "stop dictation": Action.STOP,
    "stop listening": Action.STOP,
}
# "new line" only counts as a command when it stands alone between pauses —
# start of the utterance or after punctuation, and followed by punctuation or
# the end — so "a new line of products" stays prose.
_INLINE = re.compile(
    r"(?:^|(?<=[.,!?;:]))\s*new (line|paragraph)\s*(?:[.,!?;:]+\s*|$)", re.IGNORECASE
)


@dataclass(frozen=True)
class Parsed:
    text: str
    action: Action = Action.NONE


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def parse(text: str) -> Parsed:
    action = _WHOLE.get(_normalise(text))
    if action:
        return Parsed("", action)
    text = _INLINE.sub(lambda m: "\n" if m.group(1).lower() == "line" else "\n\n", text)
    # The command's own punctuation is gone; drop the comma it leaves before it.
    text = re.sub(r"[,;:]\s*(?=\n)", "", text)
    return Parsed(text)


def split_breaks(text: str) -> list[str]:
    """Split around line breaks so prose and breaks can be handled separately."""
    return [part for part in re.split(r"(\n+)", text) if part]
