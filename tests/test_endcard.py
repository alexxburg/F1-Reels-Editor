"""Tests for ``f1_reels.endcard`` gating and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from f1_reels.endcard import EndcardConfig, build_endcard


def test_disabled_config_returns_none(tmp_path):
    config = EndcardConfig(active=False, logo_path=tmp_path / "logo.png")
    assert build_endcard(1080, 1920, tmp_path / "logo.png", config) is None


def test_disabled_config_no_logo_needed():
    config = EndcardConfig(active=False)
    assert build_endcard(1080, 1920, None, config) is None


def test_missing_logo_returns_none(tmp_path):
    config = EndcardConfig(active=True, logo_path=tmp_path / "missing.png")
    assert build_endcard(1080, 1920, None, config) is None
    assert build_endcard(1080, 1920, tmp_path / "also-missing.png", config) is None


def test_none_logo_returns_none():
    config = EndcardConfig(active=True, logo_path=None)
    assert build_endcard(1080, 1920, None, config) is None


@pytest.mark.parametrize("pct", [0.0, -0.5, 1.5, 2.0])
def test_invalid_width_pct_raises(pct):
    with pytest.raises(ValueError, match="width_pct"):
        EndcardConfig(width_pct=pct)


def test_invalid_duration_raises():
    with pytest.raises(ValueError, match="duration"):
        EndcardConfig(duration=0.0)
    with pytest.raises(ValueError, match="duration"):
        EndcardConfig(duration=-1.0)


@pytest.mark.parametrize("field", ["fade_black", "logo_delay", "logo_fade", "fade_out"])
def test_invalid_fade_raises(field):
    with pytest.raises(ValueError, match=field):
        EndcardConfig(**{field: -0.1})


def test_valid_config_defaults():
    config = EndcardConfig()
    assert config.active is True
    assert config.duration == 2.0
    assert config.width_pct == 0.86


def test_build_endcard_real_clip(tmp_path):
    moviepy = pytest.importorskip("moviepy")
    pytest.importorskip("PIL.Image")
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(logo)
    config = EndcardConfig(active=True, logo_path=logo)
    clip = build_endcard(320, 480, None, config)
    try:
        assert clip is not None
        assert float(clip.duration) == pytest.approx(config.duration)
        assert clip.size == (320, 480)
    finally:
        try:
            clip.close()
        except Exception:
            pass
