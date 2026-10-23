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
    status = _wait_status(client, job_id)
    assert status["status"] == "done", status
    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"fake-mp4"
    srt = client.get(f"/api/jobs/{job_id}/download", params={"format": "srt"})
    assert srt.status_code == 200
    assert "Hello" in srt.text


def test_explorer_row_has_download_reel_button(tmp_path, monkeypatch):
    from f1_reels import webapp

    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    js = client.get("/static/app.js").text
    assert "Download reel" in js
    assert "Delete" in js
    assert "reel-delete" in js or "delete" in js.lower()
    # XP details view: each row renders the video file-type icon (local PNG).
    assert "video-icon.png" in js
    assert "reel-file-icon" in js
    for icon in ("video-icon.png", "videos-folder-icon.png"):
        res = client.get(f"/static/{icon}")
        assert res.status_code == 200, res.text[:200]
        assert "image/png" in res.headers["content-type"]
    # Friendlier empty state points at the Reel Generator (JS-rendered path).
    assert "Reel Generator" in js
    assert "No reels yet" in js


def test_delete_job_removes_files_and_record(tmp_path, monkeypatch):
    from f1_reels import webapp

    app, _ = _make_client(tmp_path, monkeypatch)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    job_id = client.post("/api/jobs", data=_post_fields()).json()["job_id"]
    assert _wait_status(client, job_id)["status"] == "done"
    mp4 = tmp_path / "data" / "jobs" / job_id / "outputs" / "TestReel.mp4"
    assert mp4.exists()
    r = client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 200, r.text
    assert not mp4.exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get("/api/reels").json() == {"reels": []}
    # Unknown / malformed ids must not touch the filesystem.
    assert client.delete("/api/jobs/does-not-exist").status_code == 404
    assert client.delete("/api/jobs/../config").status_code in (404, 422)


def test_endpoints_survive_restart_from_disk(tmp_path, monkeypatch):
    """After a restart (empty in-memory store) status/download/delete
    must still work from the job files on disk."""
    from f1_reels import webapp

    app, _ = _make_client(tmp_path, monkeypatch)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    job_id = client.post("/api/jobs", data=_post_fields()).json()["job_id"]
    _wait_status(client, job_id)
    # Simulate a container restart: in-memory records are gone, files remain.
    app.state.jobs.clear()
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "done"
    dl = client.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"fake-mp4"
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


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
        'name="voice_direction"',
        'name="endcard"',
        'name="bricks"',
        'name="logo"',
        'name="font"',
    ):
        assert removed not in html, removed
    assert 'id="download-srt"' not in html
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
    for target in ("name", "script_lines", "speed", "punch", "margin", "seed"):
        assert f'<label for="{target}"' in html, target
        assert f'id="{target}"' in html, target
    assert 'name="voice_direction"' not in html
    assert 'id="voice_direction"' not in html
    # Status tray panel + app script (queue progress lives in Explorer).
    assert 'id="status"' in html
    assert 'id="download-srt"' not in html
    assert '<script src="/static/app.js"></script>' in html
    # Empty data-URI favicon silences /favicon.ico 404s on LAN.
    assert '<link rel="icon" href="data:,"' in html
    # XP CSS is served with the right content type.
    css = client.get("/static/style.css")
    assert css.status_code == 200, css.text[:200]
    assert "text/css" in css.headers["content-type"]
    # Window stays put: page never scrolls, only the window body does.
    assert "overflow: hidden" in css.text
    assert "overflow-y: auto" in css.text
    # XP Luna tokens (and the old pit-wall tokens must be gone).
    assert "--xp-desktop" in css.text
    # Speed slider: webkit thumb, dynamic fill var, Firefox progress parity.
    assert "::-webkit-slider-thumb" in css.text
    assert "--fill" in css.text
    assert "::-moz-range-progress" in css.text
    js = client.get("/static/app.js")
    assert js.status_code == 200, js.text[:200]
    assert "setProperty" in js.text and "--fill" in js.text
    assert "--xp-face" in css.text
    assert "#ece9d8" in css.text.lower()
    assert "Tahoma" in css.text
    assert "outset" in css.text
    assert "groove" in css.text
    assert "inset" in css.text
    assert "--f1-red" not in css.text
    assert "#e10600" not in css.text.lower()
    assert "@media (prefers-reduced-motion" in css.text
    # XP window chrome: fully rounded corners.
    assert "border-radius: 8px;" in css.text
    # Frame is a shaded blue gradient with a soft shadow, not flat + hard offset.
    assert "linear-gradient(to bottom, #3a93ff" in css.text
    assert "4px 4px 0 rgba(0, 0, 0" not in css.text
    # Desktop windows top-align to content height (no stretched empty chrome).
    assert "align-items: flex-start" in css.text
    # XP tray clock: white text on the blue taskbar, not a beige box.
    clock_rule = css.text.split("#tray-clock")[1].split("}")[0]
    assert "color: #fff" in clock_rule
    assert "--xp-tray-bg" not in clock_rule
    # Actual Bliss wallpaper served locally and used as the page background.
    assert "/static/bliss.jpg" in css.text
    bliss = client.get("/static/bliss.jpg")
    assert bliss.status_code == 200, bliss.text[:200]
    assert "image/jpeg" in bliss.headers["content-type"]


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


def test_api_reels_empty(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    r = client.get("/api/reels")
    assert r.status_code == 200, r.text
    assert r.json() == {"reels": []}


def test_api_reels_lists_done_job(tmp_path, monkeypatch):
    app, webapp = _make_client(tmp_path, monkeypatch)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4-bytes")
        (out_dir / f"{name}.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
        )
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    # Filesystem scan must survive restarts: drop the in-memory record.
    _wait_status(client, job_id)
    app.state.jobs.clear()
    r = client.get("/api/reels")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "reels" in payload
    assert len(payload["reels"]) == 1
    entry = payload["reels"][0]
    assert entry["job_id"] == job_id
    assert entry["name"] == "TestReel"
    assert entry["mp4"] is True
    assert entry["srt"] is True
    assert entry["size"] > 0
    assert entry["modified"]
    from datetime import datetime

    datetime.fromisoformat(entry["modified"])


def test_desktop_chrome(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    # Generator window keeps the exact form contract.
    assert 'id="win-generator"' in html
    assert 'id="reel-form"' in html
    assert 'action="/api/jobs"' in html
    assert 'method="post"' in html.lower()
    assert 'enctype="multipart/form-data"' in html
    for kept in (
        'name="name"',
        'name="script_lines"',
        'name="speed"',
        'name="punch"',
        'name="margin"',
        'name="seed"',
    ):
        assert kept in html, kept
    assert 'name="voice_direction"' not in html
    assert 'id="voice_direction"' not in html
    assert 'min="0.5"' in html
    assert 'max="2"' in html
    for did in (
        'id="speed-value"',
        'id="random-seed"',
        'id="status"',
    ):
        assert did in html, did
    assert 'id="download-srt"' not in html
    assert '<link rel="stylesheet" href="/static/style.css"' in html
    assert '<script src="/static/app.js"></script>' in html
    # Explorer window.
    assert 'id="win-explorer"' in html
    assert "Windows Explorer — Reels" in html
    assert 'id="explorer-refresh"' in html
    assert 'id="reel-list"' in html
    for col in ("Name", "Size", "Modified"):
        assert col in html, col
    assert "No reels yet" in html
    assert "Render one from Reel Generator." in html
    # XP details view: header columns carry a divider styling hook.
    assert "reel-col" in html
    # Friendlier empty state: watermark + title + Reel Generator hint.
    assert "reel-empty" in html
    assert "No reels yet" in html
    assert "Reel Generator" in html
    assert "reel-empty-title" in html
    assert "reel-empty-hint" in html
    # Taskbar + start menu.
    assert 'id="taskbar"' in html
    assert 'id="start-btn"' in html
    assert 'id="task-buttons"' in html
    assert 'data-win="win-generator"' in html
    assert 'data-win="win-explorer"' in html
    assert "aria-pressed" in html
    assert 'id="tray-clock"' in html
    assert 'id="start-menu"' in html
    # User profile picture served locally (non-square source is
    # center-cropped to the square tile via CSS).
    avatar = client.get("/static/profile-picture.jpg")
    assert avatar.status_code == 200, avatar.text[:200]
    assert "image/jpeg" in avatar.headers["content-type"]
    # JS hooks: reels fetch, clock, window toggles.
    js = client.get("/static/app.js").text
    assert "/api/reels" in js
    assert "reel-list" in js
    assert "explorer-refresh" in js
    assert "tray-clock" in js
    assert "start-menu" in js
    assert "aria-pressed" in js
    # CSS hooks: fixed taskbar, start pill, explorer list.
    css = client.get("/static/style.css").text
    assert "#taskbar" in css
    assert "#start-btn" in css
    assert "#tray-clock" in css
    assert "#start-menu" in css
    assert "#reel-list" in css or ".reel-list" in css
    # XP details-view styling hooks: header dividers, file icon,
    # tabular-nums size column, red-tinted Delete hover.
    assert "reel-col" in css
    assert "reel-file-icon" in css
    assert "reel-size" in css
    assert "tabular-nums" in css
    assert "reel-delete" in css
    assert ".reel-row:hover" in css
    # App icons live in the taskbar buttons and start menu items
    # (no desktop icons).
    assert 'id="desktop-icons"' not in html
    assert "desk-icon" not in html
    assert ".desk-icon" not in css
    assert "#desktop-icons" not in css
    taskbar = html.split('id="task-buttons"')[1].split('id="tray-clock"')[0]
    assert taskbar.count("<svg") >= 1, taskbar[:200]
    assert "videos-folder-icon.png" in taskbar
    # Two-column menu nests divs, so slice to the taskbar footer instead of
    # the first inner </div> (old single-column assumption).
    menu = html.split('id="start-menu"')[1].split('<footer id="taskbar"')[0]
    assert menu.count("<svg") >= 2, menu[:200]
    # Windows flag image on the start button (bundled locally, user-supplied).
    start_btn = html.split('id="start-btn"')[1].split("</button>")[0]
    assert "start-xp.webp" in start_btn
    # Single-visible contract: exactly one window visible, generator first.
    assert 'id="win-generator"' in html
    assert 'id="win-explorer" hidden' in html or 'id="win-explorer"\n' in html
    assert "showWindow" in js
    assert "hidden = " in js
    # Two-column XP Start menu: header with avatar tile.
    assert "start-menu-header" in html
    assert "avatar" in html.lower()
    assert "F1 Reels" in menu
    # Left white column: both app rows keep icons + add one-line descriptions.
    assert "Render reels from the pit wall." in menu
    assert "Browse and download finished reels." in menu
    assert menu.count('data-win="win-generator"') >= 1
    # Right blue places column: "My Reels" place with live count badge that
    # routes to the Explorer like the existing data-win buttons.
    assert "My Reels" in menu
    assert 'id="menu-reel-count"' in html
    assert "menu-reel-count" in menu
    assert menu.count('data-win="win-explorer"') >= 2
    # Footer: exactly one orange "Log Off", never "Turn Off Computer".
    assert "Log Off" in menu
    assert "Turn Off Computer" not in html
    # Menu carries its own icons: generator (svg), Explorer rows
    # (local folder image), log-off door (svg), photo avatar tile.
    assert menu.count("<svg") >= 2, menu[:500]
    assert menu.count("videos-folder-icon.png") >= 2, menu[:500]
    assert "profile-picture" in menu
    # JS wiring: count badge populated from /api/reels, log-off handler,
    # plus preserved showWindow / close-on-outside-click / Escape logic.
    assert "menu-reel-count" in js
    assert "/api/reels" in js
    assert "showWindow" in js
    # Explorer per-row contract: Download reel + Delete controls in JS.
    assert "Download reel" in js
    assert "Delete" in js
    assert "closeMenu" in js or "close-menu" in js.lower()
    assert "Escape" in js
    assert "aria-expanded" in js
    assert "logoff" in js.lower()
    # CSS hooks: two-column header/body/places/footer rules, orange Log Off
    # gradient, popup above the taskbar.
    assert "start-menu-header" in css
    assert "start-menu-apps" in css
    assert "start-menu-places" in css
    assert "start-menu-footer" in css
    assert "logoff" in css.lower()
    assert "360px" in css
    assert "z-index: 101" in css


def test_finished_job_reports_progress_100(tmp_path, monkeypatch):
    app, webapp = _make_client(tmp_path, monkeypatch)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        on_progress = kwargs.get("on_progress")
        if callable(on_progress):
            on_progress("voice", 5)
            on_progress("b-roll", 30)
            on_progress("subtitles", 50)
            on_progress("encode", 95)
            on_progress("finalize", 100)
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    job_id = client.post("/api/jobs", data=_post_fields()).json()["job_id"]
    status = _wait_status(client, job_id)
    assert status["status"] == "done", status
    assert status["progress"] == 100
    assert status["stage"] == "finalize"


def test_job_uses_configured_voice_direction(tmp_path, monkeypatch):
    custom = "Custom direction XYZ"
    app, webapp = _make_client(tmp_path, monkeypatch, config_extra={"voice_direction": custom})
    assert app.state.settings.voice_direction == custom
    captured: dict = {}

    def fake_generate_voiceover(text, audio_path, **kwargs):
        from f1_reels.alignment import Voiceover, WordTiming

        captured["generate_instructions"] = kwargs.get("instructions")
        words = [WordTiming(word=w, start=0.0, end=0.1) for w in text.split()]
        return Voiceover(words=words, duration=0.5)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        captured["edit_instructions"] = kwargs.get("instructions")
        synthesize = kwargs.get("synthesize_speech")
        if callable(synthesize):
            synthesize("Hello world", Path(tmp_dir) / "voice.wav")
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.generate_voiceover = fake_generate_voiceover
    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    status = _wait_status(client, job_id)
    assert status["status"] == "done", status
    assert captured.get("generate_instructions") == custom
    assert captured.get("edit_instructions") == custom


def test_job_uses_default_voice_direction(tmp_path, monkeypatch):
    from f1_reels.config import Settings

    app, webapp = _make_client(tmp_path, monkeypatch)
    expected = Settings().voice_direction
    captured: dict = {}

    def fake_generate_voiceover(text, audio_path, **kwargs):
        from f1_reels.alignment import Voiceover, WordTiming

        captured["generate_instructions"] = kwargs.get("instructions")
        words = [WordTiming(word=w, start=0.0, end=0.1) for w in text.split()]
        return Voiceover(words=words, duration=0.5)

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        captured["edit_instructions"] = kwargs.get("instructions")
        synthesize = kwargs.get("synthesize_speech")
        if callable(synthesize):
            synthesize("Hello world", Path(tmp_dir) / "voice.wav")
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.generate_voiceover = fake_generate_voiceover
    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    status = _wait_status(client, job_id)
    assert status["status"] == "done", status
    assert captured.get("generate_instructions") == expected
    assert captured.get("edit_instructions") == expected


def test_generator_queue_resets_without_private_progress(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    assert ">Queue<" in html and ">Render<" not in html
    assert 'id="progress"' not in html and 'id="download"' not in html
    js = client.get("/static/app.js").text
    assert "clearInterval(poll)" not in js
    assert "job.progress" not in js
    css = client.get("/static/style.css").text
    assert "xp-progress" not in css


def test_brand_toggle_form_and_behavior(tmp_path, monkeypatch):
    app, webapp = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    assert 'name="brand"' in html
    assert 'value="careers"' in html
    assert 'value="dynamics"' in html
    assert 'class="output-row"' in html

    captured: dict = {}

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        captured["logo_path"] = str(config.endcard.logo_path)
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    # Default (no brand field) renders with the configured Careers logo.
    r = client.post("/api/jobs", data=_post_fields())
    assert r.status_code == 200, r.text
    _wait_status(client, r.json()["job_id"])
    assert captured["logo_path"] == str(app.state.settings.endcard_logo), captured
    # Dynamics brand renders with the bundled RD logo.
    fields = _post_fields(brand="dynamics")
    r = client.post("/api/jobs", data=fields)
    assert r.status_code == 200, r.text
    _wait_status(client, r.json()["job_id"])
    assert captured["logo_path"].endswith("RD-Logo-White-Full.png"), captured
    # Unknown brands are rejected like other invalid inputs.
    r = client.post("/api/jobs", data=_post_fields(brand="nope"))
    assert r.status_code == 400, (r.status_code, r.text)
    assert "invalid brand" in r.text.lower()


def test_dynamics_brand_subtitle_color(tmp_path, monkeypatch):
    from f1_reels import webapp

    app, _ = _make_client(tmp_path, monkeypatch)
    settings = app.state.settings
    assert webapp.brand_active_color("dynamics", settings) == (0xFF, 0x7E, 0x10, 255)
    assert webapp.brand_active_color("careers", settings) == settings.subtitle_active_color
    assert webapp.brand_active_color("", settings) == settings.subtitle_active_color


def _wait_status(client, job_id, want=("done", "error"), timeout=30):
    import time

    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json()["status"] in want:
            return r.json()
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} not in {want} within {timeout}s")


def test_queue_is_fifo_with_positions(tmp_path, monkeypatch):
    import threading

    app, webapp = _make_client(tmp_path, monkeypatch)
    release = threading.Event()
    completed = []

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        release.wait(timeout=30)
        completed.append(name)
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    ids = [
        client.post("/api/jobs", data=_post_fields(name=n)).json()["job_id"]
        for n in ("ReelA", "ReelB", "ReelC")
    ]
    try:
        assert client.get(f"/api/jobs/{ids[0]}").json()["status"] == "running"
        assert client.get(f"/api/jobs/{ids[1]}").json()["status"] == "queued"
        assert client.get(f"/api/jobs/{ids[2]}").json()["status"] == "queued"
        active = {j["job_id"]: j for j in client.get("/api/jobs").json()["jobs"]}
        assert active[ids[1]]["queue_position"] == 1, active
        assert active[ids[2]]["queue_position"] == 2, active
        assert active[ids[0]]["queue_position"] is None, active
    finally:
        release.set()
    for job_id in ids:
        _wait_status(client, job_id)
    assert completed == ["ReelA", "ReelB", "ReelC"], completed


def test_active_jobs_endpoint(tmp_path, monkeypatch):
    import threading

    app, webapp = _make_client(tmp_path, monkeypatch)
    release = threading.Event()

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        release.wait(timeout=30)
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    first = client.post("/api/jobs", data=_post_fields(name="First")).json()["job_id"]
    _wait_status(client, first, want=("running",))
    second = client.post("/api/jobs", data=_post_fields(name="Second")).json()["job_id"]
    try:
        payload = client.get("/api/jobs").json()
        assert set(payload.keys()) == {"jobs"}, payload
        by_id = {j["job_id"]: j for j in payload["jobs"]}
        assert set(by_id) == {first, second}, by_id
        assert by_id[first]["status"] == "running"
        assert by_id[first]["queue_position"] is None
        assert by_id[second]["status"] == "queued"
        assert by_id[second]["queue_position"] == 1
        assert {"job_id", "name", "status", "progress", "stage", "queue_position"} <= set(
            by_id[first]
        )
    finally:
        release.set()
    _wait_status(client, first)
    _wait_status(client, second)
    assert client.get("/api/jobs").json() == {"jobs": []}
    names = [e["name"] for e in client.get("/api/reels").json()["reels"]]
    assert {"First", "Second"} <= set(names)


def test_delete_queued_job_never_renders(tmp_path, monkeypatch):
    import threading

    app, webapp = _make_client(tmp_path, monkeypatch)
    release = threading.Event()
    completed = []

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        release.wait(timeout=30)
        completed.append(name)
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        return True

    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    first = client.post("/api/jobs", data=_post_fields(name="First")).json()["job_id"]
    _wait_status(client, first, want=("running",))
    second = client.post("/api/jobs", data=_post_fields(name="Second")).json()["job_id"]
    assert client.delete(f"/api/jobs/{second}").status_code == 200
    release.set()
    _wait_status(client, first)
    assert completed == ["First"], completed
    assert client.get(f"/api/jobs/{second}").status_code == 404


def test_explorer_contract_covers_active_rows(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    js = client.get("/static/app.js").text
    assert "/api/jobs" in js and "reel-progress" in js
    assert "Queued #" in js
    css = client.get("/static/style.css").text
    assert ".reel-progress" in css
