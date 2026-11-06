from pathlib import Path

import pytest

from voice_assistant import config as config_module
from voice_assistant.config import Config, ConfigError, load_config


def test_missing_default_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", tmp_path / "nope.toml")
    assert load_config() == Config()


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_overrides_are_merged(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[whisper]\nmodel = "small"\n[output]\ntranscript_dir = "~/notes"\n')
    cfg = load_config(path)
    assert cfg.whisper.model == "small"
    assert cfg.whisper.beam_size == Config().whisper.beam_size
    assert cfg.output.transcript_dir == Path.home() / "notes"


@pytest.mark.parametrize("body", ['[whisper]\nmodle = "x"\n', "[nope]\na = 1\n", "not toml ["])
def test_bad_config_is_rejected(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body)
    with pytest.raises(ConfigError):
        load_config(path)
