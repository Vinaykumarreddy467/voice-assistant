"""Audio input: live microphone capture, file decoding and device discovery.

All audio leaves this module as mono float32 in [-1, 1] at the configured
sample rate, which is what both the VAD and Whisper expect.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voice_assistant.config import AudioConfig

log = logging.getLogger(__name__)

BYTES_PER_SAMPLE = 2  # S16_LE


class AudioError(RuntimeError):
    pass


def pcm16_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, "<i2").astype(np.float32) / 32768.0


class HighPass:
    """One-pole high-pass filter whose state carries across chunks."""

    def __init__(self, cutoff_hz: float, sample_rate: int):
        self.alpha = 1.0 / (1.0 + 2 * np.pi * cutoff_hz / sample_rate)
        self._prev_x = 0.0
        self._prev_y = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x)
        a, px, py = self.alpha, self._prev_x, self._prev_y
        for i, xi in enumerate(x.tolist()):
            py = a * (py + xi - px)
            px = xi
            y[i] = py
        self._prev_x, self._prev_y = px, py
        return y


def _arecord_cmd(cfg: AudioConfig, extra: list[str] = ()) -> list[str]:
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(cfg.sample_rate),
           "-c", "1", "--file-type", "raw", *extra]
    if cfg.device:
        cmd += ["-D", cfg.device]
    return cmd


class MicrophoneStream:
    """Continuously captures the microphone through ``arecord``.

    A reader thread appends to an internal buffer, so no audio is lost while
    the consumer is busy (e.g. transcribing); :meth:`read` drains it.
    """

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._running = False
        self._skip = int(cfg.warmup_secs * cfg.sample_rate) * BYTES_PER_SAMPLE
        self._filter = HighPass(cfg.highpass_hz, cfg.sample_rate)

    def __enter__(self) -> "MicrophoneStream":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def alive(self) -> bool:
        return self._running

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                _arecord_cmd(self.cfg), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
        except FileNotFoundError as exc:
            raise AudioError("arecord not found (install alsa-utils)") from exc
        self._running = True
        threading.Thread(target=self._reader, name="mic-reader", daemon=True).start()

    def _reader(self) -> None:
        assert self._proc and self._proc.stdout
        while self._running:
            try:
                data = self._proc.stdout.read(4096)
            except (OSError, ValueError):
                break
            if not data:
                break
            if self._skip:
                drop = min(self._skip, len(data))
                self._skip -= drop
                data = data[drop:]
            with self._lock:
                self._buffer.extend(data)
        self._running = False
        log.debug("microphone reader stopped")

    def stop(self) -> None:
        self._running = False
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def read(self) -> np.ndarray:
        """Return (filtered) audio captured since the previous call."""
        with self._lock:
            n = len(self._buffer) - len(self._buffer) % BYTES_PER_SAMPLE
            data = bytes(self._buffer[:n])
            del self._buffer[:n]
        return self._filter(pcm16_to_float(data))


def record(cfg: AudioConfig, seconds: float) -> np.ndarray:
    """Blocking fixed-length recording (unfiltered), used by the mic test."""
    proc = subprocess.run(
        _arecord_cmd(cfg, ["-d", str(int(round(seconds)))]),
        capture_output=True, timeout=seconds + 10,
    )
    return pcm16_to_float(proc.stdout)


def load_file(path: Path, sample_rate: int) -> np.ndarray:
    """Decode any audio/video file to mono float32 via ffmpeg."""
    if not path.is_file():
        raise AudioError(f"file not found: {path}")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
             "-ar", str(sample_rate), "-ac", "1", "-f", "s16le", "-"],
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise AudioError("ffmpeg not found") from exc
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed: {proc.stderr.decode(errors='replace').strip()}")
    return pcm16_to_float(proc.stdout)


@dataclass(frozen=True)
class InputDevice:
    description: str
    node: str


def list_input_devices() -> list[InputDevice]:
    """PipeWire audio sources (best effort; empty if pw-cli is unavailable)."""
    try:
        out = subprocess.run(["pw-cli", "list-objects", "Node"],
                             capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    nodes: list[dict[str, str]] = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("id "):
            nodes.append({})
        elif nodes and "=" in s:
            key, value = (p.strip() for p in s.split("=", 1))
            nodes[-1][key] = value.strip('"')
    return [
        InputDevice(n.get("node.nick") or n.get("node.description") or n.get("node.name", "?"),
                    n.get("node.name", "?"))
        for n in nodes if n.get("media.class") == "Audio/Source"
    ]


def alsa_capture_hardware() -> str:
    try:
        return subprocess.run(["arecord", "-l"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
