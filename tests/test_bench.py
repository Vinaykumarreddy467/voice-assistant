import json

import pytest

from voice_assistant.bench import load_dataset, normalize, word_errors


def test_normalize_ignores_case_and_punctuation():
    assert normalize("Hello, World! It's well-known.") == [
        "hello",
        "world",
        "it's",
        "well",
        "known",
    ]


@pytest.mark.parametrize(
    "ref,hyp,errors",
    [
        ("a b c", "a b c", 0),
        ("a b c", "a x c", 1),  # substitution
        ("a b c", "a c", 1),  # deletion
        ("a b c", "a b b c", 1),  # insertion
        ("a b c", "", 3),
        ("", "a b", 2),
    ],
)
def test_word_errors(ref, hyp, errors):
    assert word_errors(ref.split(), hyp.split()) == errors


def test_load_dataset_from_refs_json_or_sidecar_txt(tmp_path):
    (tmp_path / "refs.json").write_text(json.dumps({"b.wav": "two", "a.wav": "one"}))
    assert [(p.name, t) for p, t in load_dataset(tmp_path)] == [("a.wav", "one"), ("b.wav", "two")]

    other = tmp_path / "other"
    other.mkdir()
    (other / "x.flac").write_bytes(b"")
    (other / "x.txt").write_text("hello\n")
    (other / "y.flac").write_bytes(b"")  # no transcript: skipped
    assert [(p.name, t) for p, t in load_dataset(other)] == [("x.flac", "hello")]
