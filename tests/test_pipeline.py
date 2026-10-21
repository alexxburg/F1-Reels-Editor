"""Tests for pipeline SRT single-writer + bracket cursor (fakes only)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from f1_reels import pipeline
from f1_reels import subtitles
from f1_reels.endcard import EndcardConfig
from f1_reels.pipeline import PipelineConfig


def test_pipeline_uses_single_srt_writer():
    """pipeline must reuse subtitles.write_srt (no duplicated writer)."""
    assert pipeline.write_srt is subtitles.write_srt


def _install_moviepy_stub(monkeypatch):
    """Install a minimal fake moviepy.editor so edit_video needs no video deps."""

    class _FakeClip:
        def __init__(self, *args, **kwargs):
            self.w = 1080
            self.h = 1920
            self.duration = 10.0
            self.audio = None

        def close(self):
            return None

        def set_start(self, *args, **kwargs):
            return self

        def set_duration(self, *args, **kwargs):
            return self

        def set_audio(self, *args, **kwargs):
            return self

        def without_audio(self):
            return self

        def fadeout(self, *args, **kwargs):
            return self

        def fx(self, *args, **kwargs):
            return self

        def subclip(self, *args, **kwargs):
            return self

        def volumex(self, *args, **kwargs):
            return self

        def write_videofile(self, *args, **kwargs):
            return None

    editor = types.ModuleType("moviepy.editor")
    editor.AudioFileClip = _FakeClip
    editor.CompositeAudioClip = lambda *a, **k: _FakeClip()
    editor.CompositeVideoClip = lambda *a, **k: _FakeClip()
    editor.VideoFileClip = _FakeClip
    pkg = types.ModuleType("moviepy")
    pkg.editor = editor
    monkeypatch.setitem(sys.modules, "moviepy", pkg)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)


def test_pipeline_requests_wav_audio_path(tmp_path, monkeypatch):
    """Pipeline must request a .wav scratch file: OpenRouter returns raw
    PCM wrapped as WAV, so an .mp3 request never materializes on disk
    and the render wrongly aborts as 'TTS failed'."""
    _install_moviepy_stub(monkeypatch)

    seen: dict[str, str] = {}

    def fake_synthesize(text: str, audio_path: Path):
        seen["suffix"] = Path(audio_path).suffix
        assert Path(audio_path).suffix == ".wav", Path(audio_path)
        Path(audio_path).write_bytes(b"fake-wav-audio")
        words = [(w, float(i), float(i + 1)) for i, w in enumerate(text.split())]
        return words, float(len(words))

    class _FakeVideo:
        w = 1080
        h = 1920
        duration = 10.0
        audio = None

    class _FakeSelector:
        def __init__(self, config):
            self._config = config

        def build_broll(self, target_dur, seed=None):
            return _FakeVideo(), [], []

    monkeypatch.setattr(pipeline, "BrollSelector", _FakeSelector)

    config = PipelineConfig(
        output_dir=tmp_path / "out",
        bricks_dir=tmp_path / "bricks",
        generate_srt=False,
        endcard=EndcardConfig(active=False),
    )
    ok = pipeline.edit_video(
        "reel1",
        ["hello world"],
        tmp_path / "font.ttf",
        tmp_path / "tmp",
        config=config,
        synthesize_speech=fake_synthesize,
        subtitle_overlays=None,
    )
    assert ok is True
    assert seen["suffix"] == ".wav"


def test_bracket_lines_do_not_shift_cursor(tmp_path, monkeypatch):
    """[direction] lines must not shift word stamps across narrated blocks."""
    _install_moviepy_stub(monkeypatch)

    captured: dict[str, str] = {}
    overlay_calls: list[list[str]] = []

    def fake_synthesize(text: str, audio_path: Path):
        captured["text"] = text
        Path(audio_path).write_bytes(b"fake-audio")
        words = [(w, float(i), float(i + 1)) for i, w in enumerate(text.split())]
        return words, float(len(words))

    def fake_overlays(words, width, height, font_path):
        overlay_calls.append([t for t, _, _ in words])
        return []

    class _FakeVideo:
        w = 1080
        h = 1920
        duration = 10.0
        audio = None

    class _FakeSelector:
        def __init__(self, config):
            self._config = config

        def build_broll(self, target_dur, seed=None):
            return _FakeVideo(), [], []

    monkeypatch.setattr(pipeline, "BrollSelector", _FakeSelector)

    script = ["[whisper softly]", "hello world", "bye"]
    config = PipelineConfig(
        output_dir=tmp_path / "out",
        bricks_dir=tmp_path / "bricks",
        generate_srt=False,
        endcard=EndcardConfig(active=False),
    )
    ok = pipeline.edit_video(
        "reel1",
        script,
        tmp_path / "font.ttf",
        tmp_path / "tmp",
        config=config,
        synthesize_speech=fake_synthesize,
        subtitle_overlays=fake_overlays,
    )
    assert ok is True
    # Bracket direction lines are never narrated: they must not reach TTS.
    assert "[" not in captured["text"]
    assert "]" not in captured["text"]
    # Word stamps land on the right blocks (no cursor shift).
    assert overlay_calls == [["hello", "world"], ["bye"]]
