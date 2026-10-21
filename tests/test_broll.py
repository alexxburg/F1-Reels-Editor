"""Tests for ``f1_reels.broll`` selection and validation."""

from __future__ import annotations

import random
import sys
import types
from pathlib import Path

import pytest

from f1_reels.broll import BrollConfig, BrollSelector


def _make_bricks(directory: Path) -> list[Path]:
    names = ["b_clip.mp4", "a_clip.mov", "c_clip.m4v"]
    for name in names:
        (directory / name).write_bytes(b"fake-video")
    return [directory / n for n in names]


def test_list_bricks_filters_dotfiles_and_non_video(tmp_path):
    (tmp_path / ".hidden.mp4").write_bytes(b"x")
    (tmp_path / "good.mp4").write_bytes(b"x")
    (tmp_path / "good2.MP4").write_bytes(b"x")
    (tmp_path / "note.txt").write_bytes(b"x")
    (tmp_path / "clip.avi").write_bytes(b"x")
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    names = [p.name for p in selector.list_bricks()]
    assert names == ["good.mp4", "good2.MP4"]


def test_list_bricks_sorted(tmp_path):
    _make_bricks(tmp_path)
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    names = [p.name for p in selector.list_bricks()]
    assert names == sorted(names)


def test_list_bricks_missing_dir_returns_empty(tmp_path):
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path / "nope"))
    assert selector.list_bricks() == []


def test_evaluate_bricks_skips_unreadable(tmp_path, monkeypatch):
    _make_bricks(tmp_path)
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))

    def fake_probe(path):
        if Path(path).name.startswith("a_"):
            raise OSError("corrupt")
        return 5.0

    monkeypatch.setattr(selector, "probe_duration", fake_probe)
    info = selector.evaluate_bricks()
    assert len(info) == 2
    assert all(not p.name.startswith("a_") for p, _ in info)


def test_evaluate_bricks_skips_short_clips(tmp_path, monkeypatch):
    _make_bricks(tmp_path)
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    monkeypatch.setattr(selector, "probe_duration", lambda path: 0.1)
    assert selector.evaluate_bricks() == []


def _install_fake_moviepy(monkeypatch, durations: dict[str, float]):
    """Stub moviepy.editor so build_broll runs without video deps."""
    fake_editor = types.ModuleType("moviepy.editor")

    class FakeClip:
        def __init__(self, path=""):
            self.path = str(path)
            self.duration = durations.get(Path(str(path)).name, 5.0)

        def subclip(self, start, end):
            out = FakeClip(self.path)
            out.duration = end - start
            return out

        def close(self):
            return None

    def fake_concat(pieces, method="chain"):
        out = FakeClip("concat")
        out.duration = sum(p.duration for p in pieces)
        return out

    fake_editor.VideoFileClip = FakeClip
    fake_editor.concatenate_videoclips = fake_concat
    monkeypatch.setitem(sys.modules, "moviepy.editor", fake_editor)
    monkeypatch.setitem(sys.modules, "moviepy", types.ModuleType("moviepy"))
    return FakeClip


def test_build_broll_empty_dir_raises(tmp_path, monkeypatch):
    _install_fake_moviepy(monkeypatch, {})
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    with pytest.raises(RuntimeError, match="No usable clips"):
        selector.build_broll(5.0)


def test_build_broll_no_usable_clips_raises(tmp_path, monkeypatch):
    _make_bricks(tmp_path)
    _install_fake_moviepy(monkeypatch, {})
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    monkeypatch.setattr(selector, "probe_duration", lambda path: (_ for _ in ()).throw(OSError("bad")))
    with pytest.raises(RuntimeError, match="No usable clips"):
        selector.build_broll(5.0)


def test_build_broll_invalid_target_raises(tmp_path, monkeypatch):
    _install_fake_moviepy(monkeypatch, {})
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    with pytest.raises(ValueError, match="target_dur"):
        selector.build_broll(0.0)


def test_seed_determinism_random_order():
    items_a = [1, 2, 3, 4, 5]
    items_b = list(items_a)
    random.Random(42).shuffle(items_a)
    random.Random(42).shuffle(items_b)
    assert items_a == items_b


def test_build_broll_seed_determinism(tmp_path, monkeypatch):
    _make_bricks(tmp_path)
    durations = {"a_clip.mov": 5.0, "b_clip.mp4": 5.0, "c_clip.m4v": 5.0}
    _install_fake_moviepy(monkeypatch, durations)
    selector = BrollSelector(BrollConfig(bricks_dir=tmp_path))
    monkeypatch.setattr(selector, "probe_duration", lambda p: durations[Path(p).name])
    _, _, info_one = selector.build_broll(8.0, seed=123)
    _, _, info_two = selector.build_broll(8.0, seed=123)
    assert info_one == info_two
    assert len(info_one) > 0


def test_broll_config_invalid_speed_range():
    with pytest.raises(ValueError, match="Invalid speed range"):
        BrollConfig(bricks_dir=Path("."), speed_min=1.1, speed_max=1.0)
    with pytest.raises(ValueError, match="Invalid speed range"):
        BrollConfig(bricks_dir=Path("."), speed_min=0.0, speed_max=1.0)
    with pytest.raises(ValueError, match="Invalid speed range"):
        BrollConfig(bricks_dir=Path("."), speed_min=-1.0, speed_max=1.0)


def test_broll_config_invalid_min_fragment():
    with pytest.raises(ValueError, match="min_fragment"):
        BrollConfig(bricks_dir=Path("."), min_fragment=0.0)
    with pytest.raises(ValueError, match="min_fragment"):
        BrollConfig(bricks_dir=Path("."), min_fragment=-1.0)


def test_broll_config_invalid_reuse_rounds():
    with pytest.raises(ValueError, match="max_reuse_rounds"):
        BrollConfig(bricks_dir=Path("."), max_reuse_rounds=0)


def test_apply_speed_noop():
    sentinel = object()
    assert BrollSelector.apply_speed(sentinel, 1.0) is sentinel
    assert BrollSelector.apply_speed(sentinel, 1.0 + 1e-5) is sentinel
