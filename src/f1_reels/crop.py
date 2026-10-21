"""Unified crop-window math for F1 watermark removal.

This module merges the two previously duplicated implementations:

- ``Editvideos.aplicar_crop`` (top 22% cut, moviepy path)
- ``Postprocess_bricks.ventana_recorte`` (top 22% / bottom 18% cuts, ffmpeg path)

into a single source of truth. Two deliberate unifications: the output width
is always forced even (required for ``yuv420p`` ffmpeg output), matching the
``Postprocess_bricks`` behavior, and the cut itself is forced even as well so
the remaining height stays even for even-sized sources (also required for
``yuv420p``). For 1080x1920 top-crop this changes the window width from 843
to 842px, a sub-pixel-irrelevant one-pixel difference.

English only. No globals: cut ratios are module constants, everything else
flows through function arguments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

#: Logo position: "top" removes the top band (top-left watermark),
#: "bottom" removes the bottom band (bottom-left watermark).
CropPosition = Literal["top", "bottom"]

TOP_CUT_PCT = 0.22
BOTTOM_CUT_PCT = 0.18

TARGET_ASPECT_W = 9.0
TARGET_ASPECT_H = 16.0

CUT_PCT_BY_POSITION: dict[str, float] = {
    "top": TOP_CUT_PCT,
    "bottom": BOTTOM_CUT_PCT,
}


@dataclass(frozen=True)
class CropBox:
    """Crop window in pixels: origin (x, y) plus size (w2, h2)."""

    x: int
    y: int
    w2: int
    h2: int

    @property
    def width(self) -> int:
        """Alias for :attr:`w2`."""
        return self.w2

    @property
    def height(self) -> int:
        """Alias for :attr:`h2`."""
        return self.h2


def _even(value: int) -> int:
    """Round down to the nearest even integer (minimum 2)."""
    return max(2, value - (value % 2))


def compute_crop_window(w: int, h: int, position: CropPosition) -> CropBox:
    """Compute the crop window that removes the watermark and keeps 9:16.

    Args:
        w: Source frame width in pixels.
        h: Source frame height in pixels.
        position: "top" cuts ``TOP_CUT_PCT`` off the top (window starts at
            ``y = cut``); "bottom" cuts ``BOTTOM_CUT_PCT`` off the bottom
            (window starts at ``y = 0``).

    Returns:
        CropBox with a horizontally centered, even-width 9:16 window.

    Raises:
        ValueError: If ``position`` is not "top" or "bottom".
    """
    if position not in CUT_PCT_BY_POSITION:
        raise ValueError(
            f"Unknown crop position {position!r}: expected 'top' or 'bottom'."
        )
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid frame size {w}x{h}: dimensions must be positive.")

    cut = _even(int(round(h * CUT_PCT_BY_POSITION[position])))
    h2 = h - cut
    if h2 % 2:
        # Odd source height: shave one row so yuv420p output stays valid.
        h2 -= 1
    raw_w2 = int(round(h2 * TARGET_ASPECT_W / TARGET_ASPECT_H))
    w2 = min(w, _even(raw_w2))
    x = (w - w2) // 2
    y = cut if position == "top" else 0

    box = CropBox(x=x, y=y, w2=w2, h2=h2)
    logger.debug("compute_crop_window(%d, %d, %r) -> %s", w, h, position, box)
    return box


def crop_ffmpeg_filter(box: CropBox, out_w: int, out_h: int) -> str:
    """Build the ffmpeg ``-vf`` string for a crop box.

    The window itself is 9:16, then it is scaled back to the original size
    so the output keeps the source dimensions without black bars.

    Args:
        box: Crop window from :func:`compute_crop_window`.
        out_w: Output width (usually the source width).
        out_h: Output height (usually the source height).
    """
    vf = f"crop={box.w2}:{box.h2}:{box.x}:{box.y},scale={out_w}:{out_h}"
    logger.debug("crop_ffmpeg_filter -> %s", vf)
    return vf


def apply_crop_to_clip(clip, box: CropBox, rescale_to_original: bool = True):
    """Apply a crop box to a moviepy clip, optionally rescaling to source size.

    Args:
        clip: A moviepy clip with ``.w`` / ``.h`` attributes.
        box: Crop window from :func:`compute_crop_window`.
        rescale_to_original: When True (default), resize the cropped clip
            back to the original ``(w, h)`` so downstream code keeps
            working with full-size frames.
    """
    cropped = clip.crop(x1=box.x, y1=box.y, x2=box.x + box.w2, y2=box.y + box.h2)
    if rescale_to_original and (cropped.w != clip.w or cropped.h != clip.h):
        try:
            # moviepy 1.x keyword form.
            cropped = cropped.resize(newsize=(clip.w, clip.h))
        except TypeError:
            cropped = cropped.resize((clip.w, clip.h))
    return cropped


def apply_crop_top(clip, rescale_to_original: bool = True):
    """Remove the top watermark band from a moviepy clip (top 22% cut).

    This is the moviepy-path equivalent of the old ``aplicar_crop`` helper:
    it computes the "top" window via :func:`compute_crop_window` and applies
    it via :func:`apply_crop_to_clip`. For the ffmpeg path, use
    :func:`crop_ffmpeg_filter` with the same box instead.
    """
    box = compute_crop_window(int(clip.w), int(clip.h), "top")
    return apply_crop_to_clip(clip, box, rescale_to_original=rescale_to_original)
