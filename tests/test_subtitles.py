"""Tests for f1_reels.subtitles: line grouping and SRT formatting."""

import sys
from pathlib import Path

import pytest
from PIL import ImageDraw, Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from f1_reels.subtitles import (
    SubtitleStyle,
    SrtEntry,
    WordTiming,
    font_sizes,
    format_srt_time,
    group_words_into_lines,
    load_font,
    write_srt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_CANDIDATES = [
    REPO_ROOT / "Montserrat-ExtraBold.ttf",
    Path("/Library/Fonts/Montserrat-ExtraBold.ttf"),
]


def find_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    pytest.skip("No Montserrat font available for measurement tests.")


def make_words(n: int, start: float = 0.0, step: float = 0.4) -> list[WordTiming]:
    return [
        WordTiming(f"word{i}", start + i * step, start + (i + 1) * step)
        for i in range(n)
    ]


def test_grouping_empty_input_returns_empty():
    assert group_words_into_lines([], 1080, find_font()) == []


def test_grouping_preserves_all_words_in_order():
    words = make_words(12)
    lines = group_words_into_lines(words, 1080, find_font())
    assert [w for line in lines for w in line] == words


def test_grouping_respects_width_limit():
    font_path = find_font()
    style = SubtitleStyle()
    words = make_words(30)
    lines = group_words_into_lines(words, 400, font_path, style)
    assert len(lines) > 1  # Narrow frame forces wrapping.

    _, big_size = font_sizes(400, style)
    big_font = load_font(font_path, big_size)
    base_font = load_font(font_path, font_sizes(400, style)[0])
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    space_w = probe.textlength(" ", font=base_font)
    max_w = 400 * style.max_width_pct
    for line in lines:
        if len(line) == 1:
            continue  # A single long word is allowed to overflow.
        total = sum(
            probe.textlength(w.text.strip().upper(), font=big_font) for w in line
        ) + space_w * (len(line) - 1)
        assert total <= max_w + 1e-6


def test_grouping_respects_max_words_per_line():
    font_path = find_font()
    style = SubtitleStyle(max_words_per_line=3)
    lines = group_words_into_lines(make_words(10), 1080, font_path, style)
    assert all(len(line) <= 3 for line in lines)
    assert sum(len(line) for line in lines) == 10


def test_grouping_accepts_plain_tuples():
    words = [(f"word{i}", i * 0.4, (i + 1) * 0.4) for i in range(5)]
    lines = group_words_into_lines(words, 1080, find_font())
    assert sum(len(line) for line in lines) == 5
    assert all(isinstance(w, WordTiming) for line in lines for w in line)


def test_render_line_clips_matches_legacy_calls():
    moviepy = pytest.importorskip("moviepy", reason="moviepy not installed")
    from f1_reels.subtitles import render_line_clips

    line = make_words(4)
    clips = render_line_clips(line, 1080, 1920, find_font())
    assert len(clips) == len(line)


def test_format_srt_time():
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_srt_time(61.5) == "00:01:01,500"
    assert format_srt_time(3661.25) == "01:01:01,250"
    assert format_srt_time(0.007) == "00:00:00,007"


def test_write_srt_exact_format(tmp_path):
    out = tmp_path / "subs.srt"
    result = write_srt([(0.0, 1.5, "Hello"), (1.5, 3.0, "World")], out)
    assert result == out
    assert out.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello\n"
        "\n"
        "2\n00:00:01,500 --> 00:00:03,000\nWorld\n"
        "\n"
    )


def test_write_srt_accepts_dataclass_entries(tmp_path):
    out = tmp_path / "subs.srt"
    write_srt([SrtEntry(61.5, 62.0, "Hi")], str(out))
    assert out.read_text(encoding="utf-8") == (
        "1\n00:01:01,500 --> 00:01:02,000\nHi\n\n"
    )


def test_write_srt_empty_entries(tmp_path):
    out = tmp_path / "empty.srt"
    write_srt([], out)
    assert out.read_text(encoding="utf-8") == ""
