"""Tests for f1_reels.crop: top/bottom window math, aspect, even width."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from f1_reels.crop import (
    BOTTOM_CUT_PCT,
    TOP_CUT_PCT,
    CropBox,
    apply_crop_top,
    compute_crop_window,
    crop_ffmpeg_filter,
)

W, H = 1080, 1920


def test_top_cut_removes_22_percent():
    box = compute_crop_window(W, H, "top")
    expected_cut = int(round(H * TOP_CUT_PCT))
    assert expected_cut == 422
    assert box.y == expected_cut
    assert box.h2 == H - expected_cut == 1498


def test_bottom_cut_removes_18_percent_from_bottom():
    box = compute_crop_window(W, H, "bottom")
    expected_cut = int(round(H * BOTTOM_CUT_PCT))
    assert expected_cut == 346
    assert box.y == 0
    assert box.h2 == H - expected_cut == 1574


def test_nine_sixteen_preserved():
    for position in ("top", "bottom"):
        box = compute_crop_window(W, H, position)
        assert box.w2 / box.h2 == pytest.approx(9.0 / 16.0, abs=0.005)
    # Other common vertical sizes.
    for w, h in ((720, 1280), (1080, 1920), (1440, 2560), (540, 960)):
        for position in ("top", "bottom"):
            box = compute_crop_window(w, h, position)
            assert box.w2 / box.h2 == pytest.approx(9.0 / 16.0, abs=0.01)


def test_width_is_even_and_window_inside_frame():
    for w, h in ((720, 1280), (1080, 1920), (1440, 2560), (1000, 1800)):
        for position in ("top", "bottom"):
            box = compute_crop_window(w, h, position)
            assert box.w2 % 2 == 0
            assert box.h2 % 2 == 0
            assert 0 <= box.x <= w - box.w2
            assert 0 <= box.y <= h - box.h2
            assert isinstance(box, CropBox)
            assert (box.x, box.y, box.w2, box.h2) == (
                box.x,
                box.y,
                box.width,
                box.height,
            )


def test_window_is_horizontally_centered():
    box = compute_crop_window(W, H, "top")
    assert box.x == (W - box.w2) // 2 == 119


def test_invalid_position_raises():
    with pytest.raises(ValueError):
        compute_crop_window(W, H, "middle")


def test_invalid_dimensions_raise():
    with pytest.raises(ValueError):
        compute_crop_window(0, H, "top")


def test_ffmpeg_filter_string_format():
    box = compute_crop_window(W, H, "top")
    vf = crop_ffmpeg_filter(box, W, H)
    assert vf == f"crop={box.w2}:{box.h2}:{box.x}:{box.y},scale={W}:{H}"


def test_apply_crop_top_keeps_output_size():
    moviepy = pytest.importorskip("moviepy", reason="moviepy not installed")
    from moviepy.editor import ColorClip

    clip = ColorClip(size=(W, H), color=(0, 0, 0)).set_duration(0.5)
    try:
        result = apply_crop_top(clip)
        assert (result.w, result.h) == (W, H)
    finally:
        clip.close()
