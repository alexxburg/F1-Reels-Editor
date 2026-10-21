"""Tests for the brick logo/trim tables (no video needed)."""

from f1_reels import brick_config
from f1_reels.brick_config import LOGO_POR_VIDEO, TRIM_POR_TAKE, logo_for_video, trim_for_take


def test_tables_are_typed_dicts():
    assert isinstance(LOGO_POR_VIDEO, dict)
    assert isinstance(TRIM_POR_TAKE, dict)
    assert all(isinstance(k, int) for k in LOGO_POR_VIDEO)
    assert all(v in ("TL", "BL", None) for v in LOGO_POR_VIDEO.values())
    assert all(isinstance(k, str) for k in TRIM_POR_TAKE)
    assert all(isinstance(v, float) for v in TRIM_POR_TAKE.values())


def test_spot_check_logo_values():
    assert LOGO_POR_VIDEO[1] == "TL"
    assert LOGO_POR_VIDEO[7] is None
    assert LOGO_POR_VIDEO[9] == "BL"
    assert LOGO_POR_VIDEO[16] == "BL"
    assert LOGO_POR_VIDEO[19] is None


def test_spot_check_trim_values():
    assert TRIM_POR_TAKE["Video_4_take01.mp4"] == 6.0
    assert TRIM_POR_TAKE["Video_21_take01.mp4"] == 2.3
    assert all(v >= 0.0 for v in TRIM_POR_TAKE.values())


def test_helpers():
    assert logo_for_video(1) == "TL"
    assert logo_for_video(9) == "BL"
    assert logo_for_video(12) is None
    assert logo_for_video(999) is None  # unknown group -> no crop
    assert logo_for_video(None) is None
    assert trim_for_take("Video_4_take01.mp4") == 6.0
    assert trim_for_take("Video_1_take01.mp4") == 0.0  # unlisted take


def test_module_documents_tables():
    assert brick_config.__doc__ and "LOGO_POR_VIDEO" in brick_config.__doc__
    assert "TRIM_POR_TAKE" in brick_config.__doc__
