from dataclasses import dataclass

from voice_assistant.transcriber import clean_segments


@dataclass
class Seg:
    text: str
    no_speech_prob: float = 0.05
    avg_logprob: float = -0.2
    compression_ratio: float = 1.3


def test_joins_confident_segments():
    assert (
        clean_segments([Seg(" Hello there."), Seg(" How are you?")]) == "Hello there. How are you?"
    )


def test_drops_low_confidence_noise():
    assert (
        clean_segments(
            [Seg("How do you handle this stuff?", no_speech_prob=0.41, avg_logprob=-0.66)]
        )
        == ""
    )
    assert clean_segments([Seg("Anything", no_speech_prob=0.9)]) == ""


def test_drops_looping_output():
    assert clean_segments([Seg("4-3-4 4-3-4 4-3-4", compression_ratio=3.1)]) == ""


def test_drops_consecutive_repeats():
    assert (
        clean_segments([Seg("Okay, let's go."), Seg("Okay, let's go."), Seg("Done.")])
        == "Okay, let's go. Done."
    )


def test_drops_stock_hallucination():
    assert clean_segments([Seg("Thank you.")]) == ""
    assert (
        clean_segments([Seg("Thank you."), Seg("See you tomorrow.")])
        == "Thank you. See you tomorrow."
    )
