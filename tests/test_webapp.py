"""Webapp job API tests (Task 1, TDD)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _post_fields(**overrides):
    fields = {
        "name": "TestReel",
        "script_lines": "Hello world\nSecond line",
        "voice": "Puck",
        "voice_direction": "",
        "openrouter_key": "test-key",
        "openrouter_model": "google/gemini-3.8-flash-tts",
        "openrouter_voice": "Puck",
        "speed": "1.05",
        "margin": "1.0",
        "seed": "7",
    }
    fields.update(overrides)
    return fields


def test_create_job_and_download_with_fakes(tmp_path):
    from f1_reels import webapp

    def fake_edit_video(name, lines, font_path, tmp_dir, **kwargs):
        config = kwargs.get("config")
        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.mp4").write_bytes(b"fake-mp4")
        (out_dir / f"{name}.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
        )
        return True

    app = webapp.create_app(tmp_path)
    webapp.edit_video = fake_edit_video
    client = TestClient(app)
    files = [("bricks", ("brick1.mp4", b"fake-video-bytes", "video/mp4"))]
    r = client.post("/api/jobs", data=_post_fields(), files=files)
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


def test_missing_key_returns_400(tmp_path):
    from f1_reels import webapp

    app = webapp.create_app(tmp_path)
    client = TestClient(app)
    files = [("bricks", ("brick1.mp4", b"fake-video-bytes", "video/mp4"))]
    fields = _post_fields()
    fields["openrouter_key"] = ""
    r = client.post("/api/jobs", data=fields, files=files)
    assert r.status_code == 400


def test_empty_script_returns_400(tmp_path):
    from f1_reels import webapp

    app = webapp.create_app(tmp_path)
    client = TestClient(app)
    files = [("bricks", ("brick1.mp4", b"fake-video-bytes", "video/mp4"))]
    r = client.post(
        "/api/jobs", data=_post_fields(script_lines="   \n  "), files=files
    )
    assert r.status_code == 400


def test_index_form_has_all_inputs_and_download_button(tmp_path):
    from f1_reels import webapp

    app = webapp.create_app(tmp_path)
    client = TestClient(app)
    html = client.get("/").text
    assert 'name="script_lines"' in html
    assert 'name="openrouter_key"' in html
    assert 'name="openrouter_model"' in html
    assert 'name="openrouter_voice"' in html
    assert 'name="name"' in html
    assert 'name="voice_direction"' in html
    assert 'name="speed"' in html
    assert 'name="punch"' in html
    assert 'name="margin"' in html
    assert 'name="seed"' in html
    assert 'name="endcard"' in html
    assert 'name="bricks"' in html
    assert 'name="logo"' in html
    assert 'name="font"' in html
    assert 'id="download"' in html
    assert "/api/jobs" in html
