"""Docker packaging tests (Task 3, TDD)."""

from __future__ import annotations

from pathlib import Path


def test_docker_files_publish_lan_port_with_ffmpeg():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ffmpeg" in dockerfile
    assert "8001" in dockerfile
    assert "0.0.0.0" in dockerfile
    assert "uvicorn" in dockerfile
    assert "f1_reels.webapp" in dockerfile

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "8001:8001" in compose
    assert "/app/data" in compose or "data" in compose


def test_web_deps_declared():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "fastapi" in pyproject
    assert "uvicorn" in pyproject
