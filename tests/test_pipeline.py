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


def test_moviepy_progress_fraction_mapping():
    """_MoviepyProgress must map encode fraction f -> 50 + 45*f."""
    prog = pipeline._MoviepyProgress(lambda stage, pct: None)
    assert prog.encode_pct(0.0) == 50.0
    assert prog.encode_pct(0.5) == 72.5
    assert prog.encode_pct(1.0) == 95.0
    # Defensive clamping.
    assert prog.encode_pct(-1.0) == 50.0
    assert prog.encode_pct(2.0) == 95.0


def test_moviepy_progress_iter_bar_reports_encode():
    """iter_bar must yield items while reporting encode pct 50->95."""
    seen: list[tuple[str, float]] = []
    prog = pipeline._MoviepyProgress(lambda stage, pct: seen.append((stage, pct)))
    items = list(prog.iter_bar([1, 2, 3, 4], total=4))
    assert items == [1, 2, 3, 4]
    assert seen, "iter_bar must report progress"
    assert all(stage == "encode" for stage, _ in seen)
    pcts = [pct for _, pct in seen]
    assert pcts == sorted(pcts), pcts
    assert pcts[0] >= 50.0
    assert pcts[-1] == 95.0
    # Kwarg-shaped iterable + len-derived total must also work.
    seen.clear()
    items = list(prog.iter_bar(iterable=[10, 20]))
    assert items == [10, 20]
    assert seen and seen[-1][1] == 95.0


def test_moviepy_progress_never_goes_backwards_across_bars():
    """A second iter_bar (moviepy's temp-audio pass, then the video-frame
    pass) must not restart the bar at 50%."""
    seen: list[float] = []
    prog = pipeline._MoviepyProgress(lambda stage, pct: seen.append(pct))
    list(prog.iter_bar(range(4), total=4))
    list(prog.iter_bar(range(6), total=6))
    assert seen == sorted(seen), seen
    assert seen[-1] == 95.0


def _install_progress_stub(monkeypatch):
    """Fake moviepy.editor whose write_videofile drives logger.iter_bar."""

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
            logger = kwargs.get("logger")
            if logger is not None and hasattr(logger, "iter_bar"):
                for _ in logger.iter_bar(range(5), total=5):
                    pass
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


def test_edit_video_reports_monotonic_progress_ending_100(tmp_path, monkeypatch):
    """on_progress must see non-decreasing pcts ending at 100 on success."""
    _install_progress_stub(monkeypatch)

    def fake_synthesize(text: str, audio_path: Path):
        Path(audio_path).write_bytes(b"fake-audio")
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

    seen: list[tuple[str, float]] = []
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
        on_progress=lambda stage, pct: seen.append((stage, pct)),
    )
    assert ok is True
    assert seen, "expected progress callbacks"
    pcts = [pct for _, pct in seen]
    assert pcts == sorted(pcts), pcts
    assert pcts[-1] == 100.0
    stages = [stage for stage, _ in seen]
    assert "voice" in stages
    assert "finalize" in stages


def test_edit_video_progress_never_raises(tmp_path, monkeypatch):
    """A raising on_progress must not break the render."""
    _install_progress_stub(monkeypatch)

    def fake_synthesize(text: str, audio_path: Path):
        Path(audio_path).write_bytes(b"fake-audio")
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

    def bad_progress(stage, pct):
        raise RuntimeError("boom")

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
        on_progress=bad_progress,
    )
    assert ok is True


def test_edit_video_passes_codec_preset_crf_faststart(tmp_path, monkeypatch):
    """write_videofile must honor the configured codec/preset/CRF and
    faststart (moov at front), instead of hardcoded ultrafast."""
    from f1_reels import pipeline as _pipeline_mod

    _install_progress_stub(monkeypatch)
    import moviepy.editor as editor

    captured: dict = {}
    orig_composite = editor.CompositeVideoClip

    def capturing(*args, **kwargs):
        clip = orig_composite(*args, **kwargs)
        orig_write = clip.write_videofile

        def cap(*a, **k):
            captured.update(k)
            return orig_write(*a, **k)

        clip.write_videofile = cap
        return clip

    editor.CompositeVideoClip = capturing

    def fake_synthesize(text: str, audio_path: Path):
        Path(audio_path).write_bytes(b"fake-audio")
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

    monkeypatch.setattr(_pipeline_mod, "BrollSelector", _FakeSelector)

    from f1_reels.pipeline import EndcardConfig, PipelineConfig

    config = PipelineConfig(
        output_dir=tmp_path / "out",
        bricks_dir=tmp_path / "bricks",
        generate_srt=False,
        endcard=EndcardConfig(active=False),
        video_codec="libx265",
        video_preset="slow",
        video_crf=20,
    )
    ok = _pipeline_mod.edit_video(
        "reel1",
        ["hello world"],
        tmp_path / "font.ttf",
        tmp_path / "tmp",
        config=config,
        synthesize_speech=fake_synthesize,
        subtitle_overlays=None,
    )
    assert ok is True
    assert captured.get("codec") == "libx265", captured
    assert captured.get("preset") == "slow", captured
    params = captured.get("ffmpeg_params") or []
    assert "-movflags" in params and "+faststart" in params, params
    assert "-crf" in params and "20" in params, params
    assert "-pix_fmt" in params and "yuv420p" in params, params


def test_pipeline_config_encode_defaults(tmp_path):
    from f1_reels.pipeline import PipelineConfig

    config = PipelineConfig(output_dir=tmp_path / "o", bricks_dir=tmp_path / "b")
    assert config.fps == 30
    assert config.video_codec == "libx264"
    assert config.video_preset == "medium"
    assert config.video_crf == 18
