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
_INLINE = re.compile(r"[,.]?\s*\bnew (line|paragraph)\b[.,!?]?\s*", re.IGNORECASE)


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
    return Parsed(text)


def split_breaks(text: str) -> list[str]:
    """Split around line breaks so prose and breaks can be handled separately."""
    return [part for part in re.split(r"(\n+)", text) if part]
