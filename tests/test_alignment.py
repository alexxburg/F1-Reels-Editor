"""Tests for word-timing alignment helpers (no network, pure functions)."""

import pytest

from f1_reels.alignment import (
    WordTiming,
    align_script_words,
    split_words_fallback,
    word_weight,
)


def _det(words_with_times: list[tuple[str, float, float]]) -> list[WordTiming]:
    return [WordTiming(word=w, start=s, end=e) for w, s, e in words_with_times]


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


def test_align_exact_passthrough_uses_script_spelling() -> None:
    script = ["Hello,", "world!"]
    detected = _det([("hello", 0.0, 0.5), ("world", 0.5, 1.0)])
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == script
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(0.5)
    assert out[1].start == pytest.approx(0.5)
    assert out[1].end == pytest.approx(1.0)


def test_align_hyphen_split_covers_both() -> None:
    script = ["data-driven"]
    detected = _det([("data", 0.0, 0.4), ("-driven", 0.4, 0.9)])
    out = align_script_words(script, detected)
    assert out is not None
    assert len(out) == 1
    assert out[0].word == "data-driven"
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(0.9)


def test_align_merge_two_to_one_single_span() -> None:
    script = ["aero", "package"]
    detected = _det([("aeropackage?", 0.0, 1.0)])
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == ["aero", "package"]
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(1.0)
    assert out[1].start == pytest.approx(0.0)
    assert out[1].end == pytest.approx(1.0)


def test_align_substitution_keeps_positions() -> None:
    script = ["You're", "in", "trouble"]
    detected = _det([("Your", 0.0, 0.3), ("and", 0.3, 0.6), ("trouble", 0.6, 1.0)])
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == script
    for got, (_, s, e) in zip(out, [("Your", 0.0, 0.3), ("and", 0.3, 0.6), ("trouble", 0.6, 1.0)]):
        assert got.start == pytest.approx(s)
        assert got.end == pytest.approx(e)


def test_align_insertion_drops_extra_token() -> None:
    script = ["hello", "world"]
    detected = _det([("hello", 0.0, 0.3), ("oh", 0.3, 0.4), ("world", 0.4, 0.8)])
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == ["hello", "world"]
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(0.3)
    assert out[1].start == pytest.approx(0.4)
    assert out[1].end == pytest.approx(0.8)


def test_align_deletion_interpolated_between_anchors() -> None:
    script = ["one", "two", "three", "four", "five"]
    detected = _det(
        [("one", 0.0, 0.2), ("two", 0.2, 0.4), ("four", 0.6, 0.8), ("five", 0.8, 1.0)]
    )
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == script
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(0.2)
    assert out[3].start == pytest.approx(0.6)
    assert out[3].end == pytest.approx(0.8)
    assert out[4].start == pytest.approx(0.8)
    assert out[4].end == pytest.approx(1.0)
    assert out[2].start >= out[1].end
    assert out[2].end <= out[3].start
    assert out[2].end > out[2].start


def test_align_garbage_returns_none() -> None:
    script = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    detected = _det([("zzz1", 0.0, 0.3), ("zzz2", 0.3, 0.6), ("zzz3", 0.6, 0.9)])
    assert align_script_words(script, detected) is None


def test_align_aero_regression_split_merge_substitution() -> None:
    script = ["Be", "honest", "are", "you", "a", "data-driven", "problem"]
    detected = _det(
        [
            ("Be", 0.0, 0.2),
            ("honest.", 0.2, 0.5),
            ("Are", 0.5, 0.7),
            ("you", 0.7, 0.9),
            ("a", 0.9, 1.0),
            ("data", 1.0, 1.3),
            ("-driven", 1.3, 1.6),
            ("problem", 1.6, 2.0),
        ]
    )
    out = align_script_words(script, detected)
    assert out is not None
    assert [w.word for w in out] == script
    assert out[0].start == pytest.approx(0.0)
    assert out[0].end == pytest.approx(0.2)
    assert out[5].word == "data-driven"
    assert out[5].start == pytest.approx(1.0)
    assert out[5].end == pytest.approx(1.6)
    assert out[6].start == pytest.approx(1.6)
    assert out[6].end == pytest.approx(2.0)
