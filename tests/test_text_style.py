"""Tests for viral-delivery text styling (no network, pure function)."""

from f1_reels.text_style import apply_reels_punch


def test_hook_turns_first_period_into_exclamation() -> None:
    text = "This film changed everything forever. Here is why it matters."
    styled = apply_reels_punch(text)
    assert styled.startswith("This film changed everything forever! ")
    assert len(styled.split()) == len(text.split())


def test_short_first_sentence_keeps_period() -> None:
    text = "Hi there. Here is why it matters today."
    assert apply_reels_punch(text) == text


def test_long_sentence_split_preserves_word_count() -> None:
    sentence = (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima, "
        "mike november oscar papa quebec, romeo sierra tango uniform victor"
    )
    assert sentence.count(" ") >= 15
    styled = apply_reels_punch(sentence)
    assert len(styled.split()) == len(sentence.split())
    assert ". " in styled


def test_empty_and_blank_input_pass_through() -> None:
    assert apply_reels_punch("") == ""
    assert apply_reels_punch("   ") == "   "
