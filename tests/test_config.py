"""Tests for ``f1_reels.config.Settings.from_env``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from f1_reels.config import Settings, _default_project_root

DEFAULT_VOICE_DIRECTION = (
    "[Young British professional, mid-20s, contemporary Southern English accent, "
    "medium pitch, slightly textured voice, intelligent, confident, approachable, "
    "natural conversational pacing, subtle enthusiasm, authentic and unpolished.]"
)

ENV_KEYS = (
    "PROJECT_ROOT",
    "VIDEOS_DIR",
    "BRICKS_DIR",
    "OUTPUT_DIR",
    "SCRIPT_FILE",
    "VIDEO_INPUT",
    "CROP_TOP_PCT",
    "CROP_RESCALE_TO_ORIGINAL",
    "FINAL_MARGIN_SEC",
    "BRICK_SPEED_MIN",
    "BRICK_SPEED_MAX",
    "BRICK_MIN_FRAGMENT_SEC",
    "BRICK_EXTENSIONS",
    "ENDCARD_ENABLED",
    "ENDCARD_LOGO",
    "ENDCARD_DURATION_SEC",
    "ENDCARD_LOGO_WIDTH_PCT",
    "ENDCARD_BLACK_FADE_SEC",
    "ENDCARD_LOGO_DELAY_SEC",
    "ENDCARD_LOGO_FADE_SEC",
    "ENDCARD_FADE_OUT_SEC",
    "OPENROUTER_API_KEY",
    "OPENROUTER_TTS_MODEL",
    "OPENROUTER_VOICE",
    "VOICE_DIRECTION",
    "OPENROUTER_RESPONSE_FORMAT",
    "ORIGINAL_VIDEO_VOLUME",
    "GENERATE_SRT",
    "VOICE_SPEED",
    "REELS_PUNCH",
    "SUBTITLE_Y_PCT",
    "SUBTITLE_FONT_SIZE_PCT",
    "SUBTITLE_MAX_WORDS_PER_LINE",
    "SUBTITLE_ACTIVE_SCALE",
    "SUBTITLE_LEAD_SEC",
    "SUBTITLE_BASE_COLOR",
    "SUBTITLE_ACTIVE_COLOR",
    "SUBTITLE_USE_GRADIENT",
    "SUBTITLE_GRADIENT_TOP",
    "SUBTITLE_GRADIENT_BOTTOM",
    "SUBTITLE_STROKE_COLOR",
    "SUBTITLE_STROKE_WIDTH",
    "SUBTITLE_SHADOW_ENABLED",
    "SUBTITLE_SHADOW_COLOR",
    "SUBTITLE_SHADOW_DX",
    "SUBTITLE_SHADOW_DY",
    "SUBTITLE_SHADOW_BLUR",
    "SUBTITLE_MAX_WIDTH_PCT",
    "SUBTITLE_BLOCK_GAP_SEC",
    "MONTSERRAT_FONTS",
    "THREADS",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every Settings-related env var."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_from_env_defaults(clean_env):
    settings = Settings.from_env()
    root = _default_project_root()
    assert settings.project_root == root
    assert settings.videos_dir == root / "Videos"
    assert settings.bricks_dir == root / "bricks"
    assert settings.output_dir == root / "Videos_Editados"
    assert settings.script_file == root / "textos.txt"
    assert settings.video_input == ""
    assert settings.crop_top_pct == 0.22
    assert settings.crop_rescale_to_original is True
    assert settings.final_margin_sec == 1.0
    assert settings.brick_speed_min == 0.95
    assert settings.brick_speed_max == 1.05
    assert settings.brick_min_fragment_sec == 1.0
    assert settings.brick_extensions == (".mp4", ".mov", ".m4v")
    assert settings.endcard_enabled is True
    assert settings.endcard_duration_sec == 2.0
    assert settings.endcard_logo_width_pct == 0.86
    assert settings.openrouter_api_key == ""
    assert settings.openrouter_tts_model == "google/gemini-3.8-flash-tts"
    assert settings.openrouter_voice == "Puck"
    assert settings.voice_direction == DEFAULT_VOICE_DIRECTION
    assert settings.generate_srt is True
    assert settings.voice_speed == 1.05
    assert settings.reels_punch is True
    assert settings.subtitle_base_color == (255, 255, 255, 255)
    assert settings.subtitle_active_color == (0x01, 0xAB, 0xFE, 255)
    assert settings.subtitle_stroke_width == 0
    assert settings.threads == 4


def test_from_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("CROP_TOP_PCT", "0.5")
    monkeypatch.setenv("ENDCARD_ENABLED", "false")
    monkeypatch.setenv("SUBTITLE_MAX_WORDS_PER_LINE", "10")
    monkeypatch.setenv("VOICE_SPEED", "1.2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_VOICE", "Zephyr")
    monkeypatch.setenv("VOICE_DIRECTION", "Custom direction")
    monkeypatch.setenv("THREADS", "8")
    monkeypatch.setenv("GENERATE_SRT", "0")
    settings = Settings.from_env()
    assert settings.crop_top_pct == 0.5
    assert settings.endcard_enabled is False
    assert settings.subtitle_max_words_per_line == 10
    assert settings.voice_speed == 1.2
    assert settings.openrouter_api_key == "test-key"
    assert settings.openrouter_voice == "Zephyr"
    assert settings.voice_direction == "Custom direction"
    assert settings.threads == 8
    assert settings.generate_srt is False


def test_voice_direction_default_exact(clean_env):
    assert Settings.from_env().voice_direction == DEFAULT_VOICE_DIRECTION
    assert Settings().voice_direction == DEFAULT_VOICE_DIRECTION


def test_voice_direction_env_override(clean_env, monkeypatch):
    monkeypatch.setenv("VOICE_DIRECTION", "Urgent, whispered")
    assert Settings.from_env().voice_direction == "Urgent, whispered"


def test_bool_parsing_variants(clean_env, monkeypatch):
    for truthy in ("1", "true", "YES", "y", "On"):
        monkeypatch.setenv("ENDCARD_ENABLED", truthy)
        assert Settings.from_env().endcard_enabled is True
    for falsy in ("0", "false", "NO", "n", "off"):
        monkeypatch.setenv("ENDCARD_ENABLED", falsy)
        assert Settings.from_env().endcard_enabled is False


@pytest.mark.parametrize("key", ["ENDCARD_ENABLED", "GENERATE_SRT", "REELS_PUNCH"])
def test_invalid_bool_raises(clean_env, monkeypatch, key):
    monkeypatch.setenv(key, "maybe")
    with pytest.raises(ValueError, match="Invalid boolean"):
        Settings.from_env()


@pytest.mark.parametrize(
    "key", ["SUBTITLE_BASE_COLOR", "SUBTITLE_ACTIVE_COLOR", "SUBTITLE_SHADOW_COLOR"]
)
def test_invalid_color_raises(clean_env, monkeypatch, key):
    monkeypatch.setenv(key, "not-a-color")
    with pytest.raises(ValueError, match="Invalid RGBA"):
        Settings.from_env()


def test_invalid_color_wrong_parts_raises(clean_env, monkeypatch):
    monkeypatch.setenv("SUBTITLE_BASE_COLOR", "255,255,255")
    with pytest.raises(ValueError, match="Invalid RGBA"):
        Settings.from_env()


def test_valid_color_override(clean_env, monkeypatch):
    monkeypatch.setenv("SUBTITLE_BASE_COLOR", "1,2,3,4")
    assert Settings.from_env().subtitle_base_color == (1, 2, 3, 4)


def test_relative_path_resolution(clean_env, monkeypatch):
    monkeypatch.setenv("VIDEOS_DIR", "custom_vids")
    settings = Settings.from_env()
    assert settings.videos_dir == _default_project_root() / "custom_vids"
    assert settings.videos_dir.is_absolute()


def test_absolute_path_preserved(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEOS_DIR", str(tmp_path / "vids"))
    settings = Settings.from_env()
    assert settings.videos_dir == tmp_path / "vids"


def test_project_root_override_absolute(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    settings = Settings.from_env()
    assert settings.project_root == tmp_path


def test_str_tuple_override(clean_env, monkeypatch):
    monkeypatch.setenv("BRICK_EXTENSIONS", ".mp4, .avi")
    assert Settings.from_env().brick_extensions == (".mp4", ".avi")


def test_invalid_int_raises(clean_env, monkeypatch):
    monkeypatch.setenv("THREADS", "not-an-int")
    with pytest.raises(ValueError):
        Settings.from_env()
