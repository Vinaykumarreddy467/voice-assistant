"""Optional text polishing with a local LLM served by Ollama.

Fixes punctuation, casing and filler words without changing meaning. Any
failure (Ollama down, timeout, odd output) falls back to the raw text, so
dictation never blocks on it.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from voice_assistant.config import CleanupConfig

log = logging.getLogger(__name__)

PROMPT = """You clean up dictated text. Fix punctuation and capitalization, \
remove filler words (um, uh, like, you know) and obvious stutters. \
Do not add, remove or reword anything else. Do not answer questions in the text. \
Reply with the corrected text only.

Text: {text}"""


def _plausible(original: str, cleaned: str) -> bool:
    """Reject replies that are empty or clearly not an edit of the input."""
    return bool(cleaned) and 0.5 <= len(cleaned) / max(len(original), 1) <= 1.5


class OllamaCleaner:
    def __init__(self, cfg: CleanupConfig):
        self.cfg = cfg

    def clean(self, text: str) -> str:
        if not text.strip():
            return text
        body = json.dumps(
            {
                "model": self.cfg.model,
                "prompt": PROMPT.format(text=text),
                "stream": False,
                "keep_alive": "30m",  # stay in memory between utterances
                "options": {"temperature": 0},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.cfg.url.rstrip('/')}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.cfg.timeout_secs) as resp:
                reply = json.load(resp).get("response", "")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            log.warning("cleanup skipped (%s)", exc)
            return text
        cleaned = reply.strip().strip('"').strip()
        if not _plausible(text, cleaned):
            log.debug("cleanup rejected: %r -> %r", text, cleaned)
            return text
        return cleaned
