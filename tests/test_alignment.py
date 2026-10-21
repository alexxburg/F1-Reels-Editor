"""Tests for word-timing alignment helpers (no network, pure functions)."""

import pytest

from f1_reels.alignment import split_words_fallback, word_weight


def test_word_weight_punctuation_bonus() -> None:
    assert word_weight("hello.") > word_weight("hello")
    assert word_weight("hello,") > word_weight("hello")
    assert word_weight("hello") > word_weight("hi")
    # Empty string hits the `"" in ",;:"` quirk, same as the legacy helper.
    assert word_weight("") == 4.0


def test_split_fallback_spans_full_duration() -> None:
    words = split_words_fallback("one two three four five", 5.0, start=1.0)
    assert [item.word for item in words] == ["one", "two", "three", "four", "five"]
    assert words[0].start == pytest.approx(1.0)
    assert words[-1].end == pytest.approx(6.0)
    for prev, current in zip(words, words[1:]):
        assert current.start >= prev.end
        assert current.end > current.start


def test_split_fallback_shrinks_gaps_on_short_span() -> None:
    text = " ".join(f"word{i}" for i in range(20))
    words = split_words_fallback(text, 1.0)
    assert len(words) == 20
    assert words[0].start == pytest.approx(0.0)
    assert words[-1].end == pytest.approx(1.0)


def test_split_fallback_empty_or_nonpositive() -> None:
    assert split_words_fallback("", 5.0) == []
    assert split_words_fallback("hello", 0.0) == []
    assert split_words_fallback("hello", -1.0) == []
