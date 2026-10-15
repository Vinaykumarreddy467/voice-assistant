"""Start/stop a background dictation process — meant for a global hotkey.

First call starts ``voice type`` detached; the next call sends it SIGINT so
it can finish the current utterance and save the transcript.
"""

from __future__ import annotations

import fcntl
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from voice_assistant import desktop

log = logging.getLogger(__name__)

STOP_TIMEOUT_SECS = 10.0
_MARKER = "voice_assistant"


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/voice-assistant-{os.getuid()}")


def _paths() -> tuple[Path, Path, Path]:
    d = runtime_dir()
    return d / "voice-dictation.pid", d / "voice-dictation.lock", d / "voice-dictation.log"


def _running_pid(pid_file: Path) -> int | None:
    """PID of our dictation process, guarding against stale/reused PIDs."""
    try:
        pid = int(pid_file.read_text().strip())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    return pid if _MARKER.encode() in cmdline else None


def _stop(pid: int) -> None:
    os.kill(pid, signal.SIGINT)
    desktop.notify("⏹️  Stopping…", 1500)
    deadline = time.monotonic() + STOP_TIMEOUT_SECS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    log.warning("dictation did not stop in time; killing pid %d", pid)
    os.kill(pid, signal.SIGKILL)


def _start(child_args: list[str], log_file: Path) -> int:
    with open(log_file, "wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "voice_assistant", *child_args, "type"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    desktop.notify("⏳ Loading… (press the shortcut again to stop)", 2000)
    return proc.pid


def toggle(child_args: list[str]) -> str:
    """Toggle dictation; returns "started", "stopped" or "busy"."""
    pid_file, lock_file, log_file = _paths()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "busy"
        pid = _running_pid(pid_file)
        if pid is not None:
            _stop(pid)
            pid_file.unlink(missing_ok=True)
            return "stopped"
        pid_file.write_text(str(_start(child_args, log_file)))
        return "started"
