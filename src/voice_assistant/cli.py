"""Command-line interface: ``voice <command>``."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

import numpy as np

from voice_assistant import __version__, audio, desktop
from voice_assistant.config import Config, ConfigError, load_config
from voice_assistant.transcriber import MODELS, Transcriber
from voice_assistant.transcripts import save_transcript

log = logging.getLogger("voice_assistant")


# ── commands ───────────────────────────────────────────────────────────────

def _finish(config: Config, text: str, notify: bool = False) -> None:
    """Print, copy and save the final transcript."""
    if not text:
        return
    print(f"\n  📝  {text}\n")
    if desktop.copy_to_clipboard(text):
        print("  📋  Copied to clipboard")
    path = save_transcript(text, config.output.transcript_dir)
    if path:
        print(f"  💾  Saved: {path}")
        if notify:
            desktop.notify(f"💾 Saved to {path.name}")


def _session(config: Config, stop: threading.Event):
    from voice_assistant.session import DictationSession

    transcriber = Transcriber(config.whisper, config.audio.sample_rate)
    print(f"  Loading model '{config.whisper.model}'…", end=" ", flush=True)
    transcriber.load()
    print("✅", flush=True)
    return DictationSession(config, transcriber, stop)


def cmd_listen(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    from voice_assistant import sinks

    typing = args.command == "type"
    session = _session(config, stop)
    sink = sinks.typing_sink(config.output.key_delay_secs) if typing else sinks.TerminalSink()

    def ready() -> None:
        if typing:
            desktop.notify("🎤 Listening…", 1500)
            print("\n  ⚡ Speak — text is typed into the focused window.")
        else:
            print("\n  ⚡ Speak now.")
        print("  Press Ctrl+C to stop.\n", flush=True)

    try:
        text = session.run(sink, on_ready=ready)
    finally:
        sink.close()
    _finish(config, text, notify=typing)
    return 0


def cmd_once(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    session = _session(config, stop)
    print("\n  🎙️  Recording… speak, then pause.\n", flush=True)
    text = session.record_once()
    if not text:
        print("  No speech detected.")
        return 1
    _finish(config, text)
    return 0


def cmd_file(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    samples = audio.load_file(Path(args.path), config.audio.sample_rate)
    transcriber = Transcriber(config.whisper, config.audio.sample_rate)
    print(f"  Transcribing {args.path} with '{config.whisper.model}'…", flush=True)
    text = transcriber.transcribe(samples, vad_filter=True)
    if not text:
        print("  No speech found.")
        return 1
    _finish(config, text)
    return 0


def cmd_test_mic(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    print("\n  🎤 Stay quiet for 2 s, then talk for 2 s…\n", flush=True)
    samples = audio.record(config.audio, 4)
    if len(samples) < config.audio.sample_rate:
        print("  ❌ No audio captured — check the device with `voice devices`.")
        return 1
    half = len(samples) // 2
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)))  # noqa: E731
    quiet, talk, peak = rms(samples[:half]), rms(samples[half:]), float(np.abs(samples).max())
    print(f"  Background RMS {quiet:.4f}   Speech RMS {talk:.4f}   Peak {peak:.3f}")
    if peak >= 0.99:
        print("  ⚠️  Clipping — lower the input volume (Settings → Sound).")
    elif talk < 0.005:
        print("  ❌ Very little sound — raise the input volume.")
    elif talk < quiet * 2:
        print("  ⚠️  Speech is barely louder than the background noise.")
    else:
        print("  ✅ Good.")
    return 0


def cmd_devices(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    print("\n  Audio input devices (PipeWire):\n")
    for dev in audio.list_input_devices():
        print(f"  • {dev.description}\n    {dev.node}")
    hw = audio.alsa_capture_hardware()
    if hw:
        print("\n  ALSA capture hardware:\n")
        print("\n".join(f"    {line}" for line in hw.splitlines()))
    print()
    return 0


def cmd_toggle(config: Config, args: argparse.Namespace, stop: threading.Event) -> int:
    from voice_assistant.toggle import toggle

    child = []
    for flag in ("model", "device", "config"):
        value = getattr(args, flag, None)
        if value:
            child += [f"--{flag}", str(value)]
    print(toggle(child))
    return 0


COMMANDS = {
    "listen": (cmd_listen, "live dictation printed to the terminal (default)"),
    "type": (cmd_listen, "live dictation typed into the focused window"),
    "once": (cmd_once, "record one utterance, then transcribe it"),
    "file": (cmd_file, "transcribe an audio or video file"),
    "test-mic": (cmd_test_mic, "check microphone levels"),
    "devices": (cmd_devices, "list microphones"),
    "toggle": (cmd_toggle, "start/stop background typing (bind to a hotkey)"),
}
GRACEFUL_STOP = {"listen", "type", "once"}


# ── argument parsing ───────────────────────────────────────────────────────

def _common_options(parser: argparse.ArgumentParser, suppress: bool) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--model", choices=MODELS, default=default,
                        help="Whisper model (default: base)")
    parser.add_argument("--device", default=default,
                        help="ALSA capture device, e.g. hw:0,0")
    parser.add_argument("--config", type=Path, default=default,
                        help="path to config.toml")
    parser.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS if suppress else False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice", description="Offline real-time dictation powered by Whisper.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _common_options(parser, suppress=False)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        _common_options(p, suppress=True)   # allow options after the command too
        if name == "file":
            p.add_argument("path", help="audio/video file to transcribe")
    parser.set_defaults(command="listen")
    return parser


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    from dataclasses import replace

    if args.model:
        config = replace(config, whisper=replace(config.whisper, model=args.model))
    if args.device:
        config = replace(config, audio=replace(config.audio, device=args.device))
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        config = _apply_overrides(load_config(args.config), args)
    except ConfigError as exc:
        print(f"voice: config error: {exc}", file=sys.stderr)
        return 2

    # Streaming commands stop gracefully (finish the utterance, save the
    # transcript); everything else keeps the default Ctrl+C behaviour.
    stop = threading.Event()
    if args.command in GRACEFUL_STOP:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())

    handler, _ = COMMANDS[args.command]
    try:
        return handler(config, args, stop)
    except audio.AudioError as exc:
        print(f"voice: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
