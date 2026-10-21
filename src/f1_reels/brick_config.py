"""Per-video logo/trim tables, ported from ``Postprocess_bricks.py``.

These tables drive the brick post-processing step:

* :data:`LOGO_POR_VIDEO` maps a ``Video_<N>`` group number to the watermark
  position found in its takes. ``"TL"`` means a top-left logo, ``"BL"`` a
  bottom-left logo, and ``None`` means no watermark was spotted (the file is
  copied untouched).
* :data:`TRIM_POR_TAKE` maps an exact take filename to the number of leading
  seconds to remove (cold open / slate frames).
"""

from __future__ import annotations

LOGO_POR_VIDEO: dict[int, str | None] = {
    1: "TL",
    2: "TL",
    3: "TL",
    4: "TL",
    6: "TL",
    7: None,  # trim only, no watermark spotted
    8: "TL",
    9: "BL",
    10: "TL",
    11: "TL",  # TL watermark spotted -> cropped
    12: None,
    15: None,
    19: None,  # no watermark spotted -> copied as-is
    16: "BL",
    17: "BL",
    18: "BL",
    20: "TL",
    21: "TL",
    22: "TL",
    23: "TL",
    24: "TL",
    25: "TL",
    26: "TL",
    27: "TL",
    28: "TL",
    29: "TL",
    30: "TL",
    31: "TL",
    # Video 5/13/14/32: no bricks in folder -> nothing to do.
}
"""Watermark position per ``Video_<N>`` group (``"TL"`` / ``"BL"`` / ``None``)."""

TRIM_POR_TAKE: dict[str, float] = {
    "Video_4_take01.mp4": 6.0,
    "Video_7_take01.mp4": 4.0,
    "Video_8_take01.mp4": 6.0,
    "Video_21_take01.mp4": 2.3,
    "Video_22_take01.mp4": 5.0,
    "Video_25_take01.mp4": 4.0,
    "Video_29_take01.mp4": 4.0,
    "Video_30_take01.mp4": 4.0,
}
"""Leading seconds to remove, keyed by exact take filename."""


def logo_for_video(group: int | None) -> str | None:
    """Return the watermark position for a ``Video_<N>`` group.

    Unknown groups (or ``None``) map to ``None`` (no crop).
    """
    if group is None:
        return None
    return LOGO_POR_VIDEO.get(group)


def trim_for_take(filename: str) -> float:
    """Return the leading seconds to trim for a take filename (0.0 if none)."""
    return TRIM_POR_TAKE.get(filename, 0.0)
