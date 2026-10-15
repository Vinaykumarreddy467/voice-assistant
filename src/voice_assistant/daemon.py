"""Background service: keeps Whisper loaded so the hotkey starts instantly.

    voice daemon            # run (normally via the systemd user unit)
    voice toggle|start|stop|status|quit   # talk to it over a Unix socket

Threads: the GTK main loop (top-bar icon) or a plain wait owns the main
thread; one thread serves the control socket; one runs the active
dictation session; an optional one watches the push-to-talk key.
"""

from __future__ import annotations

import logging
import os
import socket
import socketserver
import threading
from pathlib import Path

from voice_assistant import desktop
from voice_assistant.config import Config
from voice_assistant.toggle import runtime_dir
from voice_assistant.transcripts import save_transcript

log = logging.getLogger(__name__)

COMMANDS = ("toggle", "start", "stop", "status", "quit")


def socket_path() -> Path:
    return runtime_dir() / "voice-assistant.sock"


def send(command: str, timeout: float = 15.0) -> str | None:
    """Send a command to a running daemon; None if no daemon is listening."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path()))
            sock.sendall(command.encode() + b"\n")
            return sock.makefile().readline().strip()
    except (FileNotFoundError, ConnectionRefusedError):
        return None


class Daemon:
    def __init__(self, config: Config):
        from voice_assistant.cleanup import OllamaCleaner
        from voice_assistant.sinks import typing_sink
        from voice_assistant.transcriber import Transcriber

        self.config = config
        self.transcriber = Transcriber(config.whisper, config.audio.sample_rate)
        self.cleaner = OllamaCleaner(config.cleanup).clean if config.cleanup.enabled else None
        self.sink = typing_sink(config.output.key_delay_secs, config.output.keyboard)
        self.quit_event = threading.Event()
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._listeners: list = []  # callables(bool listening)

    # ── state ──
    @property
    def listening(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def on_change(self, callback) -> None:
        self._listeners.append(callback)

    def _notify_change(self) -> None:
        for cb in self._listeners:
            cb(self.listening)

    def start(self) -> str:
        from voice_assistant.session import DictationSession

        with self._lock:
            if self.listening:
                return "already listening"
            self._stop = threading.Event()
            session = DictationSession(self.config, self.transcriber, self._stop, self.cleaner)
            self._thread = threading.Thread(
                target=self._run, args=(session,), name="dictation", daemon=True
            )
            self._thread.start()
        return "started"

    def _run(self, session) -> None:
        def ready() -> None:
            self._notify_change()
            desktop.notify("🎤 Listening…", 1200)

        try:
            text = session.run(self.sink, on_ready=ready)
        except Exception as exc:
            log.exception("dictation failed")
            desktop.notify(f"❌ {exc}")
            text = ""
        path = save_transcript(text, self.config.output.transcript_dir)
        desktop.notify(f"💾 Saved to {path.name}" if path else "⏹️  Stopped", 2000)
        threading.Thread(target=self._notify_change, daemon=True).start()

    def stop(self, wait: bool = True) -> str:
        with self._lock:
            if not self.listening:
                return "not listening"
            assert self._stop and self._thread
            self._stop.set()
            thread = self._thread
        if wait:
            thread.join(timeout=30)
        return "stopped"

    def toggle(self) -> str:
        return self.stop() if self.listening else self.start()

    def handle(self, command: str) -> str:
        if command == "toggle":
            return self.toggle()
        if command == "start":
            return self.start()
        if command == "stop":
            return self.stop()
        if command == "status":
            return "listening" if self.listening else "idle"
        if command == "quit":
            self.stop()
            self.quit_event.set()
            return "bye"
        return f"unknown command: {command}"

    # ── lifecycle ──
    def serve(self) -> None:
        path = socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if send("status", timeout=1) is not None:
            raise SystemExit("voice daemon is already running")
        path.unlink(missing_ok=True)

        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                command = self.rfile.readline().decode().strip()
                self.wfile.write(daemon.handle(command).encode() + b"\n")

        server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        os.chmod(path, 0o600)
        threading.Thread(target=server.serve_forever, name="control", daemon=True).start()

        print(f"  Loading model '{self.config.whisper.model}'…", flush=True)
        self.transcriber.load()
        if self.config.hotkey.push_to_talk:
            from voice_assistant.hotkey import PushToTalk

            PushToTalk(
                self.config.hotkey.push_to_talk, self.start, lambda: self.stop(wait=False)
            ).start()
        print(f"  Ready. Control socket: {path}", flush=True)

        try:
            from voice_assistant.indicator import run_with_indicator

            run_with_indicator(self)
        finally:
            self.stop()
            server.shutdown()
            path.unlink(missing_ok=True)
            self.sink.close()
