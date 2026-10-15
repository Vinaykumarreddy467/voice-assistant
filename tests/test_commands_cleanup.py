import io
import json
import threading

import numpy as np
import pytest

from voice_assistant import cleanup
from voice_assistant.commands import Action, parse
from voice_assistant.config import CleanupConfig, Config
from voice_assistant.session import DictationSession
from voice_assistant.transcriber import build_prompt

# ── voice commands ──


@pytest.mark.parametrize(
    "spoken,action",
    [
        ("Scratch that.", Action.UNDO),
        ("delete that", Action.UNDO),
        ("Stop dictation!", Action.STOP),
        ("Hello there.", Action.NONE),
    ],
)
def test_whole_utterance_commands(spoken, action):
    assert parse(spoken).action is action


def test_inline_line_breaks():
    assert parse("Dear team, new line. Thanks").text == "Dear team\nThanks"
    assert parse("Intro. New paragraph. Body.").text == "Intro\n\nBody."


# ── vocabulary prompt ──


def test_build_prompt():
    assert (
        build_prompt(["LangGraph", "MCP"], "previous text")
        == "Glossary: LangGraph, MCP. previous text"
    )
    assert build_prompt([], "") is None


# ── Ollama cleanup ──


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_ollama(reply):
    def urlopen(request, timeout):
        assert json.loads(request.data)["model"] == "llama3.2:3b"
        return FakeResponse(json.dumps({"response": reply}).encode())

    return urlopen


def test_cleanup_applies_reply(monkeypatch):
    monkeypatch.setattr(cleanup.urllib.request, "urlopen", fake_ollama(" So we ship it today. "))
    assert (
        cleanup.OllamaCleaner(CleanupConfig()).clean("um so we uh ship it today")
        == "So we ship it today."
    )


def test_cleanup_rejects_rambling_reply(monkeypatch):
    monkeypatch.setattr(
        cleanup.urllib.request,
        "urlopen",
        fake_ollama("Sure! Here is your corrected text with a long explanation " * 3),
    )
    assert cleanup.OllamaCleaner(CleanupConfig()).clean("ship it") == "ship it"


def test_cleanup_survives_ollama_down(monkeypatch):
    def down(*a, **k):
        raise cleanup.urllib.error.URLError("refused")

    monkeypatch.setattr(cleanup.urllib.request, "urlopen", down)
    assert cleanup.OllamaCleaner(CleanupConfig()).clean("hello") == "hello"


# ── session: commands applied to the sink ──


class ScriptedTranscriber:
    def __init__(self, lines):
        self.lines = iter(lines)

    def transcribe(self, audio, prompt=""):
        return next(self.lines)


class RecordingSink:
    def __init__(self):
        self.out = ""

    def emit(self, text):
        self.out += text
        return len(text)

    def delete(self, count):
        self.out = self.out[:-count]

    def close(self):
        pass


def test_session_handles_undo_newline_and_stop():
    stop = threading.Event()
    lines = ["Hello team.", "Wrong words.", "Scratch that.", "New line. Bye.", "Stop dictation."]
    session = DictationSession(Config(), ScriptedTranscriber(lines), stop, cleaner=str.upper)
    sink = RecordingSink()
    session._handle([np.zeros(10)] * len(lines), sink)
    assert sink.out == "HELLO TEAM. \nBYE. "
    assert stop.is_set()
    assert session.transcript == ["HELLO TEAM.", "\nBYE."]
