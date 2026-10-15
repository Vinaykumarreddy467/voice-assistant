"""Configuration: typed defaults, optionally overridden by a TOML file.

The file lives at ``$XDG_CONFIG_HOME/voice-assistant/config.toml`` and mirrors
the dataclasses below, one table per section::

    [whisper]
    model = "small"

    [vad]
    end_silence_secs = 1.0
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


DEFAULT_CONFIG_PATH = _xdg("XDG_CONFIG_HOME", ".config") / "voice-assistant" / "config.toml"


@dataclass(frozen=True)
class AudioConfig:
    device: str | None = None  # ALSA device for arecord, e.g. "hw:0,0"
    sample_rate: int = 16000  # Whisper's native rate
    warmup_secs: float = 1.0  # discard the mic "pop" after waking from suspend
    highpass_hz: float = 100.0  # remove DC offset and low-frequency hum


@dataclass(frozen=True)
class VadConfig:
    speech_prob: float = 0.5  # frame counts as speech at/above this
    silence_prob: float = 0.35  # frame counts as silence below this
    end_silence_secs: float = 0.7  # pause that ends an utterance
    max_utterance_secs: float = 15.0
    min_speech_secs: float = 0.3  # ignore blips shorter than this
    pre_roll_secs: float = 0.3  # audio kept from before speech onset


@dataclass(frozen=True)
class WhisperConfig:
    model: str = "base"
    language: str = "en"  # or "auto" to detect per utterance
    vocabulary: tuple[str, ...] = ()  # names/jargon Whisper should spell right
    beam_size: int = 5
    device: str = "cpu"
    compute_type: str = "int8"
    model_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "whisper-models")


@dataclass(frozen=True)
class OutputConfig:
    transcript_dir: Path = field(default_factory=lambda: Path.home() / "Transcripts")
    key_delay_secs: float = 0.004  # per key press/release on the virtual keyboard
    # "auto": uinput if permitted, else the RemoteDesktop portal; or "uinput" / "portal"
    keyboard: str = "auto"


@dataclass(frozen=True)
class CleanupConfig:
    """Optional local-LLM pass (Ollama) that fixes punctuation and fillers."""

    enabled: bool = False
    model: str = "llama3.2:3b"
    url: str = "http://localhost:11434"
    timeout_secs: float = 20.0


@dataclass(frozen=True)
class HotkeyConfig:
    # evdev key name held for push-to-talk in `voice daemon`, e.g. "KEY_RIGHTCTRL"
    push_to_talk: str | None = None


@dataclass(frozen=True)
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)


class ConfigError(ValueError):
    pass


def _coerce(section: Any, values: dict[str, Any], where: str) -> Any:
    known = {f.name: f for f in fields(section)}
    updates = {}
    for key, value in values.items():
        if key not in known:
            raise ConfigError(f"unknown setting '{where}.{key}'")
        current = getattr(section, key)
        if isinstance(current, Path):
            value = Path(value).expanduser()
        elif isinstance(current, tuple):
            value = tuple(value)
        updates[key] = value
    return replace(section, **updates)


def load_config(path: Path | None = None) -> Config:
    """Return defaults merged with the TOML file at ``path`` (if it exists)."""
    path = path or DEFAULT_CONFIG_PATH
    config = Config()
    if not path.is_file():
        return config
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    updates = {}
    for name, values in data.items():
        section = getattr(config, name, None)
        if not is_dataclass(section) or not isinstance(values, dict):
            raise ConfigError(f"{path}: unknown section [{name}]")
        updates[name] = _coerce(section, values, name)
    return replace(config, **updates)
