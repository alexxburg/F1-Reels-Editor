"""Config-file loading tests (TDD: secrets from env, rendering from config.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from f1_reels.config import Settings, _default_project_root, load_config_file


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_config_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config_file(tmp_path / "nope.json")


def test_load_config_file_bad_json_raises(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config_file(bad)


@pytest.mark.parametrize("banned", ["openrouter_api_key", "OPENROUTER_API_KEY", "OpenRouter_Api_Key"])
def test_load_config_file_banned_secret_key_raises(tmp_path, banned):
    cfg = tmp_path / "config.json"
    _write(cfg, {"openrouter_model": "m", banned: "sk-secret"})
    with pytest.raises(ValueError):
        load_config_file(cfg)


def test_load_config_file_unknown_key_raises(tmp_path):
    cfg = tmp_path / "config.json"
    _write(cfg, {"openrouter_model": "m", "nope_unknown": 1})
    with pytest.raises(ValueError):
        load_config_file(cfg)


def test_load_config_file_returns_dict(tmp_path):
    cfg = tmp_path / "config.json"
    payload = {"openrouter_model": "google/gemini-3.8-flash-tts"}
    assert load_config_file(_write(cfg, payload)) == payload


def test_from_config_unknown_key_raises():
    with pytest.raises(ValueError):
        Settings.from_config({"bogus_key": 1})


def test_from_config_banned_secret_key_raises():
    with pytest.raises(ValueError):
        Settings.from_config({"OPENROUTER_API_KEY": "sk-x"})


def test_from_config_defaults_match_settings():
    settings = Settings.from_config({})
    defaults = Settings()
    assert settings.openrouter_tts_model == defaults.openrouter_tts_model == "google/gemini-3.8-flash-tts"
    assert settings.openrouter_voice == defaults.openrouter_voice == "Puck"
    assert settings.endcard_enabled is True
    assert settings.endcard_duration_sec == defaults.endcard_duration_sec == 2.0


def test_from_config_overrides_rendering_choices():
    settings = Settings.from_config(
        {
            "openrouter_model": "google/gemini-2.5-flash-tts",
            "openrouter_voice": "Zephyr",
            "endcard_duration": 3.5,
            "endcard_logo_width_pct": 0.5,
            "endcard_black_fade": 0.9,
            "endcard_logo_delay": 0.1,
            "endcard_logo_fade": 0.8,
            "endcard_fade_out": 0.4,
        }
    )
    assert settings.openrouter_tts_model == "google/gemini-2.5-flash-tts"
    assert settings.openrouter_voice == "Zephyr"
    assert settings.endcard_duration_sec == 3.5
    assert settings.endcard_logo_width_pct == 0.5
    assert settings.endcard_black_fade_sec == 0.9
    assert settings.endcard_logo_delay_sec == 0.1
    assert settings.endcard_logo_fade_sec == 0.8
    assert settings.endcard_fade_out_sec == 0.4
    assert settings.endcard_enabled is True


def test_from_config_relative_path_resolution():
    root = _default_project_root()
    settings = Settings.from_config(
        {"bricks_dir": "my-bricks", "endcard_logo": "my-logo.png"}
    )
    assert settings.bricks_dir == root / "my-bricks"
    assert settings.bricks_dir.is_absolute()
    assert settings.endcard_logo == root / "my-logo.png"
    assert settings.endcard_logo.is_absolute()


def test_from_config_absolute_path_preserved(tmp_path):
    bricks = tmp_path / "bricks"
    logo = tmp_path / "logo.png"
    settings = Settings.from_config(
        {"bricks_dir": str(bricks), "endcard_logo": str(logo)}
    )
    assert settings.bricks_dir == bricks
    assert settings.endcard_logo == logo
