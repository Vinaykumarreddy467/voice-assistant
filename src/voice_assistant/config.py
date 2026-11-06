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
class AsrConfig:
    """Which speech-recognition engine to use."""

    # "parakeet": English, most accurate and fastest (WER 2.9% vs 10.3% for
    # whisper base on LibriSpeech, see `voice bench`). "whisper": multilingual.
    engine: str = "parakeet"
    parakeet_model: str = "nemo-parakeet-tdt-0.6b-v2"
    quantization: str | None = "int8"  # parakeet ONNX weights; None for full precision


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
    asr: AsrConfig = field(default_factory=AsrConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)


class ConfigError(ValueError):
    pass


# Fields whose default is None but which take a string when set.
_OPTIONAL_STR = {("audio", "device"), ("hotkey", "push_to_talk"), ("asr", "quantization")}


def _coerce_value(where: str, key: str, current: Any, value: Any) -> Any:
    """Check a TOML value against the type of the field's default."""
    name = f"{where}.{key}"

    def bad(expected: str) -> ConfigError:
        return ConfigError(f"'{name}' must be {expected}, got {value!r}")

    if (where, key) in _OPTIONAL_STR:
        if not isinstance(value, str):
            raise bad("a string")
        return value
    if isinstance(current, bool):  # before int: bool is an int subclass
        if not isinstance(value, bool):
            raise bad("true or false")
        return value
    if isinstance(current, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad("a whole number")
        return value
    if isinstance(current, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise bad("a number")
        return float(value)
    if isinstance(current, Path):
        if not isinstance(value, str):
            raise bad("a path string")
        return Path(value).expanduser()
    if isinstance(current, tuple):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise bad('a list of strings, e.g. ["LangGraph", "MCP"]')
        return tuple(value)
    if isinstance(current, str):
        if not isinstance(value, str):
            raise bad("a string")
        return value
    return value


def _coerce(section: Any, values: dict[str, Any], where: str) -> Any:
    known = {f.name for f in fields(section)}
    updates = {}
    for key, value in values.items():
        if key not in known:
            raise ConfigError(f"unknown setting '{where}.{key}'")
        updates[key] = _coerce_value(where, key, getattr(section, key), value)
    return replace(section, **updates)


def validate(config: Config) -> Config:
    """Reject values that would fail later in confusing ways."""
    problems = []
    if config.audio.sample_rate != 16000:
        problems.append("audio.sample_rate must be 16000 (what the VAD and models expect)")
    v = config.vad
    for name in ("speech_prob", "silence_prob"):
        if not 0.0 < getattr(v, name) < 1.0:
            problems.append(f"vad.{name} must be between 0 and 1")
    if v.silence_prob > v.speech_prob:
        problems.append("vad.silence_prob must not be above vad.speech_prob")
    for name in ("end_silence_secs", "max_utterance_secs"):
        if getattr(v, name) <= 0:
            problems.append(f"vad.{name} must be positive")
    for name in ("min_speech_secs", "pre_roll_secs"):
        if getattr(v, name) < 0:
            problems.append(f"vad.{name} must not be negative")
    if config.audio.warmup_secs < 0:
        problems.append("audio.warmup_secs must not be negative")
    if not 0 < config.audio.highpass_hz < config.audio.sample_rate / 2:
        problems.append("audio.highpass_hz must be between 0 and half the sample rate")
    if config.asr.engine not in ("whisper", "parakeet"):
        problems.append('asr.engine must be "whisper" or "parakeet"')
    if config.whisper.beam_size < 1:
        problems.append("whisper.beam_size must be at least 1")
    if config.output.keyboard not in ("auto", "uinput", "portal"):
        problems.append('output.keyboard must be "auto", "uinput" or "portal"')
    if config.output.key_delay_secs < 0:
        problems.append("output.key_delay_secs must not be negative")
    if config.cleanup.timeout_secs <= 0:
        problems.append("cleanup.timeout_secs must be positive")
    if problems:
        raise ConfigError("; ".join(problems))
    return config


def load_config(path: Path | None = None) -> Config:
    """Return defaults merged with the TOML file at ``path``.

    The default location may be absent; an explicitly given ``path`` must exist.
    """
    explicit = path is not None
    path = path or DEFAULT_CONFIG_PATH
    config = Config()
    if not path.is_file():
        if explicit:
            raise ConfigError(f"config file not found: {path}")
        return config
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    updates = {}
    for name, values in data.items():
        section = getattr(config, name, None)
        if not is_dataclass(section) or not isinstance(values, dict):
            raise ConfigError(f"{path}: unknown section [{name}]")
        updates[name] = _coerce(section, values, name)
    try:
        return validate(replace(config, **updates))
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
