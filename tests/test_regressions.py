"""One test per bug found in the v0.4 audit, so none of them can come back."""

import os
import socket
import stat
import threading
import time

import numpy as np
import pytest

from voice_assistant import audio, cleanup, daemon, setup, toggle
from voice_assistant.commands import parse
from voice_assistant.config import AudioConfig, ConfigError, VadConfig, load_config
from voice_assistant.transcripts import save_transcript
from voice_assistant.vad import FRAME, Segmenter

SR = 16000


# ── audio: the end of the last sentence must not be lost on stop ──


def test_microphone_keeps_audio_still_in_the_pipe_at_stop(monkeypatch, tmp_path):
    raw = tmp_path / "speech.raw"
    raw.write_bytes(np.arange(48000, dtype="<i2").tobytes())  # 3 s
    # Like arecord: produce audio, then keep running until terminated.
    cmd = ["sh", "-c", f"cat {raw}; exec sleep 30"]
    monkeypatch.setattr(audio, "_arecord_cmd", lambda cfg, extra=(): cmd)
    stream = audio.MicrophoneStream(AudioConfig(warmup_secs=0, highpass_hz=1))
    stream.start()
    time.sleep(0.3)
    stream.stop()
    assert len(stream.read()) == 48000


def test_microphone_reports_why_it_stopped(monkeypatch):
    cmd = ["sh", "-c", "echo 'audio open error: Device or resource busy' >&2"]
    monkeypatch.setattr(audio, "_arecord_cmd", lambda cfg, extra=(): cmd)
    stream = audio.MicrophoneStream(AudioConfig(warmup_secs=0))
    stream.start()
    deadline = time.monotonic() + 5
    while stream.alive and time.monotonic() < deadline:  # arecord failing on its own
        time.sleep(0.05)
    assert not stream.alive
    assert "Device or resource busy" in stream.error()


# ── vad ──


def silent_model(audio_):
    return np.zeros(len(audio_) // FRAME)


def test_zero_pre_roll_does_not_grow_without_bound():
    seg = Segmenter(VadConfig(pre_roll_secs=0), SR, model=silent_model)
    for _ in range(50):
        seg.feed(np.zeros(SR, np.float32))
    assert len(seg._pre_roll) == 0


class ScriptedProbs:
    """Stateful fake VAD returning a fixed probability per frame."""

    stateful = True

    def __init__(self, probs):
        self.probs = list(probs)

    def __call__(self, frames):
        n = len(frames) // FRAME
        out, self.probs = self.probs[:n], self.probs[n:]
        return np.array(out)


def test_long_utterance_is_cut_at_a_pause_not_mid_word():
    frames_per_sec = SR / FRAME
    n = int(20 * frames_per_sec)
    probs = [0.9] * n
    dip = int(14 * frames_per_sec)  # brief breath at 14 s, inside the search window
    probs[dip] = 0.36  # above silence_prob: not a pause that ends the utterance
    seg = Segmenter(VadConfig(max_utterance_secs=15), SR, model=ScriptedProbs(probs))
    marked = np.repeat(np.arange(n, dtype=np.float32), FRAME)  # sample value = frame index
    utts = seg.feed(marked) + seg.flush()
    first = utts[0]
    assert first[-1] == dip  # cut right after the quietest frame, not at exactly 15 s
    assert sum(len(u) for u in utts) == len(marked)  # nothing lost or duplicated


# ── commands ──


@pytest.mark.parametrize("text", ["We need a new line of products.", "Draw a new line, then stop."])
def test_new_line_inside_a_sentence_is_prose(text):
    assert parse(text).text == text


# ── config ──


@pytest.mark.parametrize(
    "body,message",
    [
        ('[whisper]\nvocabulary = "LangGraph"\n', "list of strings"),
        ('[whisper]\nbeam_size = "five"\n', "whole number"),
        ("[audio]\nsample_rate = 44100\n", "16000"),
        ("[vad]\nspeech_prob = 1.5\n", "between 0 and 1"),
        ('[output]\nkeyboard = "telepathy"\n', "output.keyboard"),
        ('[asr]\nengine = "siri"\n', "asr.engine"),
        ("[cleanup]\nenabled = 1\n", "true or false"),
    ],
)
def test_bad_values_are_rejected_with_a_clear_message(tmp_path, body, message):
    path = tmp_path / "config.toml"
    path.write_text(body)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_ints_are_accepted_for_float_settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[vad]\nend_silence_secs = 1\n")
    assert load_config(path).vad.end_silence_secs == 1.0


# ── transcripts ──


def test_transcripts_are_private_and_never_overwritten(tmp_path):
    first = save_transcript("Hello world.", tmp_path / "t", now=0)
    second = save_transcript("Hello world.", tmp_path / "t", now=0)  # same second, same words
    assert first != second
    assert first.read_text() == second.read_text() == "Hello world.\n"
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "t").stat().st_mode) == 0o700


# ── runtime dir ──


def test_runtime_dir_refuses_a_directory_others_can_access(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    target = f"/tmp/voice-assistant-{os.getuid()}"
    created = not os.path.exists(target)
    os.makedirs(target, exist_ok=True)
    original = stat.S_IMODE(os.stat(target).st_mode)
    try:
        os.chmod(target, 0o777)
        with pytest.raises(RuntimeError, match="not a private directory"):
            toggle.runtime_dir()
        os.chmod(target, 0o700)
        assert str(toggle.runtime_dir()) == target
    finally:
        os.chmod(target, original)
        if created:
            os.rmdir(target)


# ── setup ──


def test_setup_only_claims_its_own_gnome_shortcut(monkeypatch):
    store = {
        "/k/custom0/name": "'Voice Recorder'",
        "/k/custom0/command": "'gnome-sound-recorder --voice'",
        "/k/custom1/name": "'Voice Dictation'",
        "/k/custom1/command": "'/home/u/.local/bin/voice toggle'",
    }

    class Done:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    monkeypatch.setattr(setup, "_run", lambda *cmd: Done(store.get(cmd[-1], "")))
    assert not setup._is_ours("/k/custom0/")
    assert setup._is_ours("/k/custom1/")


def test_quoting_survives_awkward_paths():
    path = "/home/o'brien/my apps/50%/voice"
    assert setup.gvariant_str(path) == "'/home/o\\'brien/my apps/50%/voice'"
    assert setup.systemd_quote(path) == '"/home/o\'brien/my apps/50%%/voice"'
    assert setup.desktop_exec(path) == '"/home/o\'brien/my apps/50%%/voice" toggle'


# ── cleanup: the LLM must never add a newline (= Enter in a terminal) ──


def test_cleanup_output_has_no_line_breaks(monkeypatch):
    import io
    import json

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    reply = json.dumps({"response": "ls -la\nrm -rf ~"}).encode()
    monkeypatch.setattr(cleanup.urllib.request, "urlopen", lambda *a, **k: Resp(reply))
    out = cleanup.OllamaCleaner(cleanup.CleanupConfig()).clean("list the files and remove home")
    assert "\n" not in out


# ── daemon ──


def test_send_reports_a_hung_daemon_instead_of_crashing(monkeypatch, tmp_path):
    path = tmp_path / "s.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)  # accepts, never answers
    monkeypatch.setattr(daemon, "socket_path", lambda: path)
    try:
        with pytest.raises(daemon.DaemonTimeout):
            daemon.send("toggle", timeout=0.3)
    finally:
        server.close()


def test_send_returns_none_when_no_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon, "socket_path", lambda: tmp_path / "missing.sock")
    assert daemon.send("status") is None


def test_gated_sink_waits_for_key_release():
    typed = []

    class Sink:
        def emit(self, text):
            typed.append(text)
            return len(text)

        def delete(self, count):
            pass

        def close(self):
            pass

    released = threading.Event()
    gated = daemon.GatedSink(Sink(), released)
    worker = threading.Thread(target=gated.emit, args=("hello",))
    worker.start()
    worker.join(0.2)
    assert typed == []  # key still held: nothing typed
    released.set()
    worker.join(1)
    assert typed == ["hello"]
