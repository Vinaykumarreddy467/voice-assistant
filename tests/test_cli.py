import pytest

from voice_assistant.cli import build_parser


def test_default_command_is_listen():
    assert build_parser().parse_args([]).command == "listen"


@pytest.mark.parametrize("argv", [
    ["--model", "tiny", "type"],
    ["type", "--model", "tiny"],
])
def test_options_before_or_after_command(argv):
    args = build_parser().parse_args(argv)
    assert args.command == "type"
    assert args.model == "tiny"


def test_file_requires_path():
    args = build_parser().parse_args(["file", "talk.mp3"])
    assert args.path == "talk.mp3"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["file"])
