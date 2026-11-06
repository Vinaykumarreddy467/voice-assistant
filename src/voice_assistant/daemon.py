"""Background service: keeps the speech model loaded so the hotkey starts instantly.

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
from collections.abc import Callable
from pathlib import Path

from voice_assistant import desktop
from voice_assistant.config import Config
from voice_assistant.sinks import Sink
from voice_assistant.toggle import runtime_dir
from voice_assistant.transcripts import save_transcript

log = logging.getLogger(__name__)

COMMANDS = ("toggle", "start", "stop", "status", "quit")
REPLY_TIMEOUT_SECS = 10.0  # every command answers immediately; this only catches hangs
SESSION_JOIN_SECS = 60.0  # how long start/quit wait for a session that is still finishing


class DaemonTimeout(RuntimeError):
    pass


def socket_path() -> Path:
    return runtime_dir() / "voice-assistant.sock"


def send(command: str, timeout: float = REPLY_TIMEOUT_SECS) -> str | None:
    """Send a command to a running daemon; None if no daemon is listening."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path()))
            sock.sendall(command.encode() + b"\n")
            return sock.makefile().readline().strip()
    except (FileNotFoundError, ConnectionRefusedError):
        return None
    except TimeoutError as exc:  # socket.timeout is an alias since 3.10
        raise DaemonTimeout(f"voice daemon did not answer within {timeout:.0f} s") from exc


class GatedSink:
    """Holds output back while a gate is closed (push-to-talk key held), so
    typed characters can't combine with the held key into shortcuts."""

    def __init__(self, sink: Sink, released: threading.Event):
        self._sink = sink
        self._released = released

    def emit(self, text: str) -> int:
        self._released.wait()
        return self._sink.emit(text)

    def delete(self, count: int) -> None:
        self._released.wait()
        self._sink.delete(count)

    def close(self) -> None:
        self._sink.close()


class Daemon:
    def __init__(self, config: Config):
        from voice_assistant.cleanup import OllamaCleaner
        from voice_assistant.sinks import typing_sink
        from voice_assistant.transcriber import make_transcriber

        self.config = config
        self.transcriber = make_transcriber(config)
        self.cleaner = OllamaCleaner(config.cleanup).clean if config.cleanup.enabled else None
        self.key_released = threading.Event()
        self.key_released.set()
        self.sink: Sink = GatedSink(
            typing_sink(config.output.key_delay_secs, config.output.keyboard), self.key_released
        )
        self.quit_event = threading.Event()
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._listeners: list[Callable[[bool], object]] = []

    # ── state ──
    @property
    def listening(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        if not self.listening:
            return "idle"
        return "stopping" if self._stop and self._stop.is_set() else "listening"

    def on_change(self, callback: Callable[[bool], object]) -> None:
        self._listeners.append(callback)

    def _notify_change(self) -> None:
        listening = self.state == "listening"
        for cb in self._listeners:
            try:
                cb(listening)
            except Exception:
                log.exception("state listener failed")

    def start(self) -> str:
        from voice_assistant.session import DictationSession

        with self._lock:
            if self.state == "listening":
                return "already listening"
            if self._thread is not None and self._thread.is_alive():
                # Previous session is still transcribing its last sentence.
                self._thread.join(timeout=SESSION_JOIN_SECS)
                if self._thread.is_alive():
                    return "busy: previous session is still finishing"
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
            text = " ".join(session.transcript)
        path = save_transcript(text, self.config.output.transcript_dir)
        desktop.notify(f"💾 Saved to {path.name}" if path else "⏹️  Stopped", 2000)
        threading.Thread(target=self._notify_change, daemon=True).start()

    def stop(self, wait: bool = False) -> str:
        """Request a stop. The session finishes its last sentence and saves on
        its own thread, so by default this returns immediately."""
        with self._lock:
            if self.state != "listening":
                return "not listening"
            assert self._stop and self._thread
            self._stop.set()
            thread = self._thread
        self._notify_change()
        if wait:
            thread.join(timeout=SESSION_JOIN_SECS)
        return "stopping"

    def toggle(self) -> str:
        return self.stop() if self.state == "listening" else self.start()

    def handle(self, command: str) -> str:
        if command == "toggle":
            return self.toggle()
        if command == "start":
            return self.start()
        if command == "stop":
            return self.stop()
        if command == "status":
            return self.state
        if command == "quit":
            self.quit_event.set()
            return "bye"
        return f"unknown command: {command!r} (expected one of {', '.join(COMMANDS)})"

    # ── lifecycle ──
    def serve(self) -> None:
        path = socket_path()
        try:
            already = send("status", timeout=2) is not None
        except DaemonTimeout:
            already = True
        if already:
            raise SystemExit("voice daemon is already running")
        path.unlink(missing_ok=True)

        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                try:
                    line = self.rfile.readline(256).decode(errors="replace").strip()
                    reply = daemon.handle(line)
                except Exception as exc:
                    log.exception("control command failed")
                    reply = f"error: {exc}"
                self.wfile.write(reply.encode() + b"\n")

        old_umask = os.umask(0o177)  # socket is created 0600 — no window for others
        try:
            server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
        finally:
            os.umask(old_umask)
        threading.Thread(target=server.serve_forever, name="control", daemon=True).start()

        print(f"  Loading {self.transcriber.name}…", flush=True)
        self.transcriber.load()
        if self.config.hotkey.push_to_talk:
            from voice_assistant.hotkey import PushToTalk

            def pressed() -> None:
                self.key_released.clear()
                self.start()

            def released() -> None:
                self.key_released.set()
                self.stop()

            PushToTalk(self.config.hotkey.push_to_talk, pressed, released).start()
        print(f"  Ready. Control socket: {path}", flush=True)

        try:
            from voice_assistant.indicator import run_with_indicator

            run_with_indicator(self)
        finally:
            self.stop(wait=True)
            server.shutdown()
            path.unlink(missing_ok=True)
            self.sink.close()
