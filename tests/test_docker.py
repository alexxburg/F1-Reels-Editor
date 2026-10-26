"""Docker packaging tests (Task 3, TDD)."""

from __future__ import annotations

from pathlib import Path


def test_docker_files_publish_lan_port_with_ffmpeg():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "ffmpeg" in dockerfile
    assert "awscli" in dockerfile
    assert "8081" in dockerfile
    assert "0.0.0.0" in dockerfile
    assert "uvicorn" in dockerfile
    assert "f1_reels.webapp" in dockerfile

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "8082:8081" in compose
    assert "/app/data" in compose or "data" in compose


def test_web_deps_declared():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "fastapi" in pyproject
    assert "uvicorn" in pyproject
    assert "psycopg2" in pyproject


def test_moviepy_stack_pinned_compatible():
    """moviepy 1.0.3 needs imageio<2.37 (``metadata_errors`` was removed),
    numpy 1.x and Pillow<10 (``ANTIALIAS`` removed)."""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "moviepy==1.0.3" in pyproject
    assert "imageio==2.31.1" in pyproject
    assert "numpy==1.26.4" in pyproject
    assert "pillow==9.5.0" in pyproject


def test_readme_documents_lan_webapp():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "docker compose up --build" in readme
    assert "8082" in readme
    assert "OPENROUTER_API_KEY" in readme
