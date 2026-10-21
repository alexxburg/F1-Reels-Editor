"""Tests for f1_reels.script_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from f1_reels.script_parser import SINGLE_VIDEO_NAME, parse_script_file


def _write_script(tmp_path: Path, content: str) -> Path:
    script: Path = tmp_path / "textos.txt"
    script.write_text(content, encoding="utf-8")
    return script


def test_multi_video_process_filtering(tmp_path: Path) -> None:
    """Blocks keep their Y/N flags; empty Y blocks stay empty."""
    path: Path = _write_script(
        tmp_path,
        "Video_1 | process: Y\n"
        "First line.\n"
        "Second line.\n"
        "\n"
        "Video_2 | process: N\n"
        "This block is skipped.\n"
        "\n"
        "Video_3 | process: Y\n",
    )
    blocks = parse_script_file(path)
    assert list(blocks) == ["Video_1", "Video_2", "Video_3"]
    assert blocks["Video_1"].process is True
    assert blocks["Video_1"].lines == ["First line.", "Second line."]
    assert blocks["Video_2"].process is False
    assert blocks["Video_2"].lines == ["This block is skipped."]
    assert blocks["Video_3"].process is True
    assert blocks["Video_3"].lines == []


def test_legacy_single_mode(tmp_path: Path) -> None:
    """A file without headers becomes one __SINGLE__ block."""
    path: Path = _write_script(
        tmp_path,
        "# a comment\n"
        "\n"
        "Just a single script line.\n"
        "Another line here.\n",
    )
    blocks = parse_script_file(path)
    assert list(blocks) == [SINGLE_VIDEO_NAME]
    assert blocks[SINGLE_VIDEO_NAME].process is True
    assert blocks[SINGLE_VIDEO_NAME].lines == [
        "Just a single script line.",
        "Another line here.",
    ]


def test_voice_direction_extraction(tmp_path: Path) -> None:
    """Bracketed lines are stored as direction, not narration."""
    path: Path = _write_script(
        tmp_path,
        "Video_1 | process: Y\n"
        "[Young British professional, confident tone.]\n"
        "[Second direction note.]\n"
        "Hello world.\n",
    )
    blocks = parse_script_file(path)
    assert blocks["Video_1"].lines == ["Hello world."]
    assert blocks["Video_1"].voice_direction == (
        "Young British professional, confident tone. Second direction note."
    )


def test_voice_direction_single_mode(tmp_path: Path) -> None:
    """Single mode also separates voice direction from script lines."""
    path: Path = _write_script(
        tmp_path,
        "[Calm narrator.]\n"
        "Hello world.\n",
    )
    blocks = parse_script_file(path)
    assert blocks[SINGLE_VIDEO_NAME].voice_direction == "Calm narrator."
    assert blocks[SINGLE_VIDEO_NAME].lines == ["Hello world."]


def test_time_prefix_stripping(tmp_path: Path) -> None:
    """Leading start-end time ranges are removed from script lines."""
    path: Path = _write_script(
        tmp_path,
        "Video_1 | process: Y\n"
        "0.0-2.5 | Hello world.\n"
        "10.25 - 12.75|Second line.\n"
        "Fish | chips stays intact.\n",
    )
    blocks = parse_script_file(path)
    assert blocks["Video_1"].lines == [
        "Hello world.",
        "Second line.",
        "Fish | chips stays intact.",
    ]


def test_header_variants(tmp_path: Path) -> None:
    """Comma, bare-process, two-line, .mp4 and lowercase variants parse."""
    path: Path = _write_script(
        tmp_path,
        "Video_1, process=Y\n"
        "Line one.\n"
        "\n"
        "Video_2\n"
        "process: y\n"
        "Line two.\n"
        "\n"
        "MyVideo.mp4 | process: Y\n"
        "Line three.\n",
    )
    blocks = parse_script_file(path)
    assert blocks["Video_1"].process is True
    assert blocks["Video_1"].lines == ["Line one."]
    assert blocks["Video_2"].process is True
    assert blocks["Video_2"].lines == ["Line two."]
    # The .mp4 suffix is normalized away.
    assert blocks["MyVideo"].process is True
    assert blocks["MyVideo"].lines == ["Line three."]


def test_header_without_marker_defaults_to_not_processed(tmp_path: Path) -> None:
    """A bare Video_N header defaults to process=False."""
    path: Path = _write_script(
        tmp_path,
        "Video_9\n"
        "Some line.\n",
    )
    blocks = parse_script_file(path)
    assert blocks["Video_9"].process is False
    assert blocks["Video_9"].lines == ["Some line."]


def test_comments_blank_lines_and_pre_header_text_ignored(tmp_path: Path) -> None:
    """Comments, blanks and text before the first header are dropped."""
    path: Path = _write_script(
        tmp_path,
        "# leading comment\n"
        "Orphan line before any header.\n"
        "\n"
        "Video_1 | process: Y\n"
        "# inner comment\n"
        "\n"
        "Kept line.\n",
    )
    blocks = parse_script_file(path)
    assert list(blocks) == ["Video_1"]
    assert blocks["Video_1"].lines == ["Kept line."]


def test_repeated_header_updates_flag(tmp_path: Path) -> None:
    """A repeated header updates the process flag for that block."""
    path: Path = _write_script(
        tmp_path,
        "Video_1 | process: N\n"
        "Line one.\n"
        "Video_1 | process: Y\n"
        "Line two.\n",
    )
    blocks = parse_script_file(path)
    assert blocks["Video_1"].process is True
    assert blocks["Video_1"].lines == ["Line one.", "Line two."]


def test_missing_file_raises(tmp_path: Path) -> None:
    """A missing script path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_script_file(tmp_path / "does-not-exist.txt")
