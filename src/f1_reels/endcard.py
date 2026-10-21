"""Closing end card: fade to black with the channel logo.

``moviepy``/``numpy`` are imported lazily so this module stays importable
without video dependencies installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EndcardConfig:
    """Tuning for :func:`build_endcard`."""

    logo_path: Path | None = None
    active: bool = True
    duration: float = 2.0
    width_pct: float = 0.86
    fade_black: float = 1.2
    logo_delay: float = 0.3
    logo_fade: float = 1.0
    fade_out: float = 0.6

    def __post_init__(self) -> None:
        if self.duration <= 0.0:
            raise ValueError(f"duration must be positive: {self.duration!r}")
        if not 0.0 < self.width_pct <= 1.0:
            raise ValueError(f"width_pct must be in (0, 1]: {self.width_pct!r}")
        for field_name in ("fade_black", "logo_delay", "logo_fade", "fade_out"):
            if getattr(self, field_name) < 0.0:
                raise ValueError(f"{field_name} must be >= 0: {getattr(self, field_name)!r}")


def _fade_mask(size: tuple[int, int], clip_dur: float, fade_dur: float) -> Any:
    """White opacity mask ramping 0 -> 1 for real opacity fades."""
    from moviepy.editor import ColorClip

    return (
        ColorClip(size=size, color=1.0, ismask=True)
        .set_duration(clip_dur)
        .fadein(fade_dur)
    )


def build_endcard(
    w: int,
    h: int,
    logo_path: str | Path | None,
    config: EndcardConfig,
) -> Any | None:
    """Build the closing end card clip (``None`` when disabled/missing logo).

    The card fades the video through black over the last ``duration``
    seconds while the logo fades in with its original colors (its alpha
    channel is preserved) after ``logo_delay`` seconds. The caller owns the
    returned clip and must close it after writing.
    """
    effective = Path(logo_path) if logo_path is not None else config.logo_path
    if not config.active:
        return None
    if effective is None or not Path(effective).is_file():
        logger.warning("End card skipped: logo not found: %s", effective)
        return None

    import numpy as np
    from moviepy.editor import ColorClip, CompositeVideoClip, ImageClip

    width, height = int(w), int(h)
    black = ColorClip(size=(width, height), color=(0, 0, 0)).set_duration(
        config.duration
    )
    black = black.set_mask(_fade_mask((width, height), config.duration, config.fade_black))

    logo_w = int(width * config.width_pct)
    logo = ImageClip(str(effective)).resize(width=logo_w)
    logo = logo.set_position("center").set_duration(config.duration - config.logo_delay)
    if logo.mask is not None:
        fade = max(config.logo_fade, 1e-6)
        logo.mask = logo.mask.fl(
            lambda gf, t: np.clip(gf(t).astype(float), 0.0, 1.0)
            * min(max(t, 0.0) / fade, 1.0)
        )
    else:
        logo = logo.set_mask(
            _fade_mask(logo.size, logo.duration, config.logo_fade)
        )
    logo = logo.set_start(config.logo_delay)
    return CompositeVideoClip([black, logo], size=(width, height)).set_duration(
        config.duration
    )
