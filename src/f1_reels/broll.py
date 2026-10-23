"""Random B-roll assembly from pre-processed brick clips.

Explicit, dependency-injected selector:

* no module-level globals -- all tuning lives in :class:`BrollConfig`;
* :mod:`pathlib` paths and :mod:`logging` output instead of ``print``;
* deterministic shuffling via the ``seed`` parameter;
* clip durations are cached process-wide with :func:`functools.lru_cache`;
* ``moviepy`` is imported lazily so this module stays importable (and
  testable) without video dependencies installed.
"""

from __future__ import annotations

import functools
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: One selection entry: (source path, used start, used end, source duration).
SelectionEntry = tuple[Path, float, float, float]

#: Human-readable form of a selection entry: (basename, start, end, duration).
SelectionInfo = list[tuple[str, float, float, float]]


@dataclass(frozen=True)
class BrollConfig:
    """Tuning for :class:`BrollSelector`."""

    bricks_dir: Path
    speed_min: float = 0.95
    speed_max: float = 1.05
    min_fragment: float = 1.0
    extensions: tuple[str, ...] = (".mp4", ".mov", ".m4v")
    best_fit_max_waste: float = 4.0
    snap_tolerance: float = 0.08
    max_reuse_rounds: int = 5

    def __post_init__(self) -> None:
        if not 0.0 < self.speed_min <= self.speed_max:
            raise ValueError(
                f"Invalid speed range: [{self.speed_min}, {self.speed_max}]"
            )
        if self.min_fragment <= 0.0:
            raise ValueError(f"min_fragment must be positive: {self.min_fragment!r}")
        if self.max_reuse_rounds < 1:
            raise ValueError("max_reuse_rounds must be >= 1")


@functools.lru_cache(maxsize=1024)
def _cached_clip_duration(path_str: str) -> float:
    """Probe a clip duration; results are cached for the process lifetime."""
    from moviepy.editor import VideoFileClip

    clip = VideoFileClip(path_str)
    try:
        return float(clip.duration or 0.0)
    finally:
        clip.close()


class BrollSelector:
    """Assembles a random B-roll track covering exactly ``target_dur`` seconds."""

    def __init__(self, config: BrollConfig) -> None:
        self._config = config

    @property
    def config(self) -> BrollConfig:
        return self._config

    def list_bricks(self) -> list[Path]:
        """List all usable brick clips, sorted by filename."""
        bricks_dir = Path(self._config.bricks_dir)
        if not bricks_dir.is_dir():
            return []
        exts = {e.lower() for e in self._config.extensions}
        return sorted(
            p
            for p in bricks_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in exts
        )

    def probe_duration(self, path: str | Path) -> float:
        """Clip duration in seconds (cached via :func:`functools.lru_cache`)."""
        return _cached_clip_duration(str(Path(path)))

    @staticmethod
    def cache_info() -> functools._CacheInfo:
        """Expose the duration-cache stats (hits/misses/currsize)."""
        return _cached_clip_duration.cache_info()

    @staticmethod
    def cache_clear() -> None:
        """Drop all cached clip durations."""
        _cached_clip_duration.cache_clear()

    def evaluate_bricks(self) -> list[tuple[Path, float]]:
        """Measure every brick; skip unreadable or degenerate clips."""
        info: list[tuple[Path, float]] = []
        for path in self.list_bricks():
            try:
                duration = self.probe_duration(path)
            except Exception as exc:
                logger.warning("Unreadable brick %s: %s", path.name, str(exc)[:120])
                continue
            if duration > 0.2:
                info.append((path, duration))
        return info

    @staticmethod
    def apply_speed(clip: Any, factor: float) -> Any:
        """Speed a clip up/down by ``factor`` (no-op when ~1.0)."""
        if abs(factor - 1.0) < 1e-4:
            return clip
        try:
            import moviepy.video.fx.all as vfx

            return clip.fx(vfx.speedx, factor)
        except Exception:
            if hasattr(clip, "speedx"):
                return clip.speedx(factor)
            return clip

    def build_broll(
        self, target_dur: float, seed: int | None = None
    ) -> tuple[Any, list[Any], SelectionInfo]:
        """Build a B-roll track lasting exactly ``target_dur`` seconds.

        Bricks are shuffled (``seed`` makes the order reproducible, ``None``
        gives a different combination on every call), accumulated until they
        cover the target, and the tail is trimmed or speed-adjusted so no
        final fragment is shorter than ``min_fragment``. When the bricks fall
        short they are reused in a fresh random order.

        Returns ``(concatenated_clip, opened_clips, selection_info)`` where
        ``selection_info`` holds ``(basename, used_start, used_end,
        source_duration)`` tuples. The caller must close the concatenated
        clip and every clip in ``opened_clips`` after writing.
        """
        from moviepy.editor import VideoFileClip, concatenate_videoclips

        if target_dur <= 0.0:
            raise ValueError(f"target_dur must be positive, got {target_dur!r}")
        cfg = self._config
        info = self.evaluate_bricks()
        if not info:
            raise RuntimeError(f"No usable clips in {cfg.bricks_dir}")
        logger.info(
            "Bricks evaluated: %d clips, %.1fs total.",
            len(info),
            sum(d for _, d in info),
        )

        rng = random.Random(seed) if seed is not None else random.Random()
        order = info[:]
        rng.shuffle(order)

        selection: list[SelectionEntry] = []
        used: set[Path] = set()
        total = 0.0

        # 1) Accumulate whole clips while they fit; keep the first overflowing
        #    clip aside as the trim candidate.
        idx = 0
        excess: tuple[Path, float] | None = None
        while total < target_dur and idx < len(order):
            path, duration = order[idx]
            idx += 1
            if total + duration <= target_dur:
                selection.append((path, 0.0, duration, duration))
                used.add(path)
                total += duration
            else:
                excess = (path, duration)
                break

        # 2) Handle the tail: normal trim, best-fit swap, or global speedup.
        if total < target_dur - 1e-3 and excess is not None:
            path, duration = excess
            remain = target_dur - total
            if remain >= cfg.min_fragment or duration < cfg.min_fragment:
                if duration >= remain:
                    selection.append((path, 0.0, remain, duration))
                    used.add(path)
                    total = target_dur
                else:  # unreachable in practice; kept for safety
                    selection.append((path, 0.0, duration, duration))
                    used.add(path)
                    total += duration
            else:
                # A direct trim would leave a micro-fragment: look for an
                # unused clip that covers `remain` with minimal waste.
                rest = [(p2, d2) for p2, d2 in order[idx:] if p2 not in used]
                best: tuple[Path, float, float] | None = None
                for p2, d2 in rest:
                    if d2 >= remain:
                        waste = d2 - remain
                        if best is None or waste < best[2]:
                            best = (p2, d2, waste)
                if best is not None and best[2] <= cfg.best_fit_max_waste:
                    selection.append((best[0], 0.0, remain, best[1]))
                    used.add(best[0])
                    total = target_dur
                else:
                    factor = (total + duration) / target_dur
                    if cfg.speed_min <= factor <= cfg.speed_max:
                        selection.append((path, 0.0, duration, duration))
                        used.add(path)
                        total += duration
                    else:
                        selection.append((path, 0.0, remain, duration))
                        used.add(path)
                        total = target_dur

        # 3) Still short (all bricks used or tiny clips): reuse in new orders.
        rounds = 0
        while total < target_dur - 1e-3 and rounds < cfg.max_reuse_rounds:
            rounds += 1
            extra = info[:]
            rng.shuffle(extra)
            for path, duration in extra:
                if total >= target_dur - 1e-3:
                    break
                remain = target_dur - total
                if duration <= remain:
                    selection.append((path, 0.0, duration, duration))
                    total += duration
                else:
                    selection.append((path, 0.0, remain, duration))
                    total = target_dur
                    break
            if total < target_dur - 1e-3:
                logger.warning("Bricks fell short, retrying (round %d)...", rounds)

        # 4) Open, randomly offset-trim, and concatenate.
        opened: list[Any] = []
        pieces: list[Any] = []
        try:
            for path, ini, fin, _orig in selection:
                clip = VideoFileClip(str(path))
                opened.append(clip)
                if fin - ini < clip.duration - 1e-3:
                    span = fin - ini
                    max_start = max(0.0, clip.duration - span)
                    start = rng.uniform(0.0, max_start) if max_start > 0.05 else 0.0
                    pieces.append(clip.subclip(start, start + span))
                else:
                    pieces.append(clip)
        except Exception:
            for clip in opened:
                try:
                    clip.close()
                except Exception:
                    pass
            raise

        if not pieces:
            for clip in opened:
                try:
                    clip.close()
                except Exception:
                    pass
            raise RuntimeError("B-roll selection came out empty.")

        concat = concatenate_videoclips(pieces, method="chain")
        concat_dur = float(concat.duration or 0.0)

        # 5) Final snap, only when strictly needed (subclip rounding drift).
        if abs(concat_dur - target_dur) > cfg.snap_tolerance:
            factor = concat_dur / target_dur if target_dur > 0 else 1.0
            if cfg.speed_min <= factor <= cfg.speed_max:
                logger.info(
                    "Fine speed adjust x%.3f to hit %.2fs (concat %.2fs).",
                    factor,
                    target_dur,
                    concat_dur,
                )
                concat = self.apply_speed(concat, factor)
            elif concat_dur > target_dur:
                concat = concat.subclip(0, target_dur)
            else:
                # Pad by freezing the last frame (rare).
                from moviepy.editor import ImageClip as _ImageClip

                missing = target_dur - concat_dur
                last_frame = pieces[-1].get_frame(pieces[-1].duration - 0.04)
                freeze = _ImageClip(last_frame, transparent=False).set_duration(missing)
                try:
                    freeze = freeze.set_fps(30)  # must match PipelineConfig.fps
                except Exception:
                    pass
                concat = concatenate_videoclips([concat, freeze], method="chain")

        sel_info: SelectionInfo = [
            (p.name, round(i, 2), round(f, 2), round(d, 2))
            for p, i, f, d in selection
        ]
        logger.info(
            "B-roll: %d bricks, %.2fs (target %.2fs).",
            len(selection),
            float(concat.duration),
            target_dur,
        )
        for name, ini, fin, duration in sel_info:
            logger.debug("  - %s [%ss -> %ss of %ss]", name, ini, fin, duration)
        return concat, opened, sel_info
