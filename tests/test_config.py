from pathlib import Path

import pytest

from voice_assistant.config import Config, ConfigError, load_config


def test_missing_file_gives_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_overrides_are_merged(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[whisper]\nmodel = "small"\n[output]\ntranscript_dir = "~/notes"\n')
    cfg = load_config(path)
    assert cfg.whisper.model == "small"
    assert cfg.whisper.beam_size == Config().whisper.beam_size
    assert cfg.output.transcript_dir == Path.home() / "notes"


@pytest.mark.parametrize("body", ['[whisper]\nmodle = "x"\n', '[nope]\na = 1\n', "not toml ["])
def test_bad_config_is_rejected(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body)
    with pytest.raises(ConfigError):
        load_config(path)
