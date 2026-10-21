"""Webapp job API tests (new contract: secrets from env, rendering from config.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_config(
    path: Path,
    *,
    bricks_dir: Path,
    logo: Path,
    font: Path,
    extra: dict | None = None,
) -> Path:
    payload: dict = {
        "openrouter_model": "google/gemini-3.8-flash-tts",
        "openrouter_voice": "Puck",
        "bricks_dir": str(bricks_dir),
        "endcard_logo": str(logo),
        "subtitle_font": str(font),
        "endcard_duration": 2.0,
        "endcard_logo_width_pct": 0.86,
        "endcard_black_fade": 1.2,
        "endcard_logo_delay": 0.3,
        "endcard_logo_fade": 1.0,
        "endcard_fade_out": 0.6,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _make_server_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    bricks = tmp_path / "server-bricks"
    bricks.mkdir(parents=True, exist_ok=True)
    (bricks / "brick1.mp4").write_bytes(b"fake-video-bytes")
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"fake-png")
    font = tmp_path / "font.ttf"
    font.write_bytes(b"fake-font-bytes")
    return bricks, logo, font


def _make_client(
    tmp_path: Path,
    monkeypatch,
    *,
    bricks: Path | None = None,
    logo: Path | None = None,
    font: Path | None = None,
    config_extra: dict | None = None,
):
    from f1_reels import webapp

    server_bricks, server_logo, server_font = _make_server_dirs(tmp_path)
    cfg = _write_config(
        tmp_path / "config.json",
        bricks_dir=bricks if bricks is not None else server_bricks,
        logo=logo if logo is not None else server_logo,
        font=font if font is not None else server_font,
        extra=config_extra,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    app = webapp.create_app(tmp_path / "data", config_path=cfg)
    return app, webapp


def _post_fields(**overrides):
    fields = {
        "name": "TestReel",
        "script_lines": "Hello world\nSecond line",
        "voice_direction": "",
        "speed": "1.05",
        "margin": "1.0",
        "punch": "on",
        "seed": "7",
    }
    fields.update(overrides)
    return fields


def test_create_job_and_download_with_fakes(tmp_path, monkeypatch):
    app, webapp = _make_client(tmp_path, monkeypatch)
    expected_font = Path(app.state.settings.subtitle_font)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        assert Path(font_path) == expected_font
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        (out_dir / f"{name}.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
        )
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["status"] == "done", status
    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"fake-mp4"
    srt = client.get(f"/api/jobs/{job_id}/download", params={"format": "srt"})
    assert srt.status_code == 200
    assert "Hello" in srt.text


def test_missing_key_returns_400(tmp_path, monkeypatch):
    from f1_reels import webapp

    server_bricks, server_logo, server_font = _make_server_dirs(tmp_path)
    cfg = _write_config(
        tmp_path / "config.json",
        bricks_dir=server_bricks,
        logo=server_logo,
        font=server_font,
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = webapp.create_app(tmp_path / "data", config_path=cfg)
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 400


def test_empty_script_returns_400(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields(script_lines="   \n  "))
    assert r.status_code == 400


def test_index_form_new_contract(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    # Kept fields.
    for kept in (
        'name="name"',
        'name="script_lines"',
        'name="voice_direction"',
        'name="speed"',
        'name="punch"',
        'name="margin"',
        'name="seed"',
    ):
        assert kept in html, kept
    # Removed inputs must be gone.
    for removed in (
        'name="openrouter_key"',
        'name="openrouter_model"',
        'name="openrouter_voice"',
        'name="endcard"',
        'name="bricks"',
        'name="logo"',
        'name="font"',
    ):
        assert removed not in html, removed
    assert 'id="download"' in html
    assert 'id="download-srt"' in html
    assert "/api/jobs" in html
    # Speed is a slider (0.5x-2x) with a live readout.
    assert 'type="range"' in html
    assert 'name="speed"' in html
    assert 'min="0.5"' in html
    assert 'max="2"' in html
    assert 'value="1.05"' in html
    assert 'id="speed-value"' in html
    # Seed row has a Random button that must not submit the form.
    assert 'id="random-seed"' in html
    assert 'type="button"' in html


def test_index_polished_structure(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    # Stylesheet link for the Windows XP (Luna) theme.
    assert '<link rel="stylesheet" href="/static/style.css"' in html
    # App window chrome: glossy title bar with decorative controls.
    assert 'class="window"' in html
    assert 'class="title-bar"' in html
    assert 'aria-hidden="true"' in html
    # Card-based form with grouped sections.
    assert html.count("<fieldset") >= 3
    assert html.count("<legend") >= 3
    assert "<legend>Reel</legend>" in html
    assert "<legend>Voice</legend>" in html
    assert "<legend>Output</legend>" in html
    # Semantic labels wired to inputs.
    for target in ("name", "script_lines", "voice_direction", "speed", "punch", "margin", "seed"):
        assert f'<label for="{target}"' in html, target
        assert f'id="{target}"' in html, target
    # Status tray panel + download actions + app script.
    assert 'id="status"' in html
    assert 'id="download"' in html
    assert 'id="download-srt"' in html
    assert '<script src="/static/app.js"></script>' in html
    # XP CSS is served with the right content type.
    css = client.get("/static/style.css")
    assert css.status_code == 200, css.text[:200]
    assert "text/css" in css.headers["content-type"]
    # XP Luna tokens (and the old pit-wall tokens must be gone).
    assert "--xp-desktop" in css.text
    assert "--xp-face" in css.text
    assert "#ece9d8" in css.text.lower()
    assert "Tahoma" in css.text
    assert "outset" in css.text
    assert "groove" in css.text
    assert "inset" in css.text
    assert "--f1-red" not in css.text
    assert "#e10600" not in css.text.lower()
    assert "@media (prefers-reduced-motion" in css.text


def test_speed_out_of_range_returns_400(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    for bad in ("2.5", "0.1", "not-a-float"):
        r = client.post("/api/jobs", data=_post_fields(speed=bad))
        assert r.status_code == 400, (bad, r.status_code, r.text)
        assert "invalid speed" in r.text.lower()


def test_speed_boundaries_accepted(tmp_path, monkeypatch):
    app, webapp = _make_client(tmp_path, monkeypatch)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    for good in ("0.5", "2.0"):
        r = client.post("/api/jobs", data=_post_fields(speed=good))
        assert r.status_code == 200, (good, r.status_code, r.text)


def test_secret_key_in_config_raises(tmp_path, monkeypatch):
    from f1_reels import webapp

    server_bricks, server_logo, _server_font = _make_server_dirs(tmp_path)
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "openrouter_model": "google/gemini-3.8-flash-tts",
                "openrouter_api_key": "sk-should-not-be-here",
                "bricks_dir": str(server_bricks),
                "endcard_logo": str(server_logo),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with pytest.raises(ValueError):
        webapp.create_app(tmp_path / "data", config_path=cfg)


def test_missing_bricks_dir_returns_400(tmp_path, monkeypatch):
    app, _ = _make_client(
        tmp_path, monkeypatch, bricks=tmp_path / "does-not-exist-bricks"
    )
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 400


def test_empty_bricks_dir_returns_400(tmp_path, monkeypatch):
    empty = tmp_path / "empty-bricks"
    empty.mkdir(parents=True, exist_ok=True)
    app, _ = _make_client(tmp_path, monkeypatch, bricks=empty)
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 400


def test_missing_logo_returns_400(tmp_path, monkeypatch):
    app, _ = _make_client(
        tmp_path, monkeypatch, logo=tmp_path / "does-not-exist-logo.png"
    )
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 400


def test_missing_font_returns_400(tmp_path, monkeypatch):
    app, _ = _make_client(
        tmp_path, monkeypatch, font=tmp_path / "does-not-exist-font.ttf"
    )
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 400
    assert "subtitle font not found" in r.text.lower()


def test_no_config_raises_runtime_error(tmp_path, monkeypatch):
    from f1_reels import webapp

    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    # Isolate from the repo's own <project-root>/config.json.
    monkeypatch.setattr(webapp, "_default_project_root", lambda: tmp_path / "noroot")
    with pytest.raises(RuntimeError):
        webapp.create_app(tmp_path / "data")
