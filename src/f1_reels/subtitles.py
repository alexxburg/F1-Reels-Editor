"""Word-highlight subtitle rendering in Reels style.

Faithful port of the subtitle pipeline from the legacy script
(``agrupar_palabras_en_lineas`` / ``crear_subtitulo_linea`` /
``_fmt_srt`` / ``escribir_srt``) with English names.

Visual output is unchanged: inactive words render white, the spoken word
renders 10% larger in solid blue ``#01abfe`` with a soft drop shadow and no
hard stroke. All tuning constants live in :class:`SubtitleStyle` (injected
per call) instead of module globals. Paths use :class:`pathlib.Path` and
diagnostics go through :mod:`logging` instead of ``print``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordTiming:
    """A single word with its display interval in seconds."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class SrtEntry:
    """A single subtitle entry for SRT export."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SubtitleStyle:
    """All visual tuning constants for subtitle rendering.

    Defaults reproduce the legacy look exactly: white base text, ``#01abfe``
    active word at +10% size, no hard stroke, soft drop shadow.
    """

    y_pct: float = 0.62
    font_size_pct: float = 0.066
    max_words_per_line: int = 20
    active_scale: float = 1.10
    base_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    active_color: tuple[int, int, int, int] = (0x01, 0xAB, 0xFE, 255)
    use_gradient: bool = False
    gradient_top: tuple[int, int, int, int] = (0x00, 0xD9, 0xFD, 255)
    gradient_bottom: tuple[int, int, int, int] = (0x01, 0x69, 0xFE, 255)
    stroke_color: tuple[int, int, int, int] = (0, 0, 0, 255)
    stroke_width: int = 0
    shadow: bool = True
    shadow_color: tuple[int, int, int, int] = (0, 0, 0, 170)
    shadow_dx: int = 0
    shadow_dy: int = 5
    shadow_blur: int = 8
    max_width_pct: float = 0.96


WordLike = Union[WordTiming, Sequence]
SrtLike = Union[SrtEntry, Sequence]

_DEFAULT_STYLE = SubtitleStyle()


def _resolve_style(style: SubtitleStyle | None) -> SubtitleStyle:
    return style if style is not None else _DEFAULT_STYLE


def load_font(font_path: str | Path, size: int):
    """Load the subtitle font, pinning variable fonts to ExtraBold."""
    font = ImageFont.truetype(str(font_path), size)
    try:
        names = font.get_variation_names() if hasattr(font, "get_variation_names") else []
        if names and any(b"ExtraBold" in n for n in names):
            font.set_variation_by_name(b"ExtraBold")
    except Exception:
        pass
    return font


def font_sizes(video_width: int, style: SubtitleStyle | None = None) -> tuple[int, int]:
    """Return ``(base_size, active_size)`` for a given video width."""
    resolved = _resolve_style(style)
    base_size = max(30, int(video_width * resolved.font_size_pct))
    big_size = max(int(base_size * resolved.active_scale), base_size + 2)
    return base_size, big_size


def normalize_words(words: Sequence[WordLike]) -> list[WordTiming]:
    """Accept ``WordTiming`` items or ``(text, start, end)`` tuples."""
    normalized: list[WordTiming] = []
    for item in words:
        if isinstance(item, WordTiming):
            normalized.append(item)
        else:
            text, start, end = item
            normalized.append(WordTiming(str(text), float(start), float(end)))
    return normalized


def group_words_into_lines(
    words: Sequence[WordLike],
    video_width: int,
    font_path: str | Path,
    style: SubtitleStyle | None = None,
) -> list[list[WordTiming]]:
    """Group words into lines that fit the screen width (Reels style).

    Width is measured with the large (active-word) font, i.e. the worst
    case where every word could be active. Words keep their original order
    and timings; no word is ever dropped.
    """
    resolved = _resolve_style(style)
    items = normalize_words(words)
    if not items:
        return []

    base_size, big_size = font_sizes(video_width, resolved)
    font_base = load_font(font_path, base_size)
    font_big = load_font(font_path, big_size)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    space_w = probe.textlength(" ", font=font_base)
    max_w = video_width * resolved.max_width_pct

    lines: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    total = 0.0
    for item in items:
        word_w = probe.textlength(item.text.strip().upper(), font=font_big)
        candidate = total + (space_w if current else 0) + word_w
        if current and (
            candidate > max_w or len(current) >= resolved.max_words_per_line
        ):
            lines.append(current)
            current = [item]
            total = word_w
        else:
            current.append(item)
            total = candidate
    if current:
        lines.append(current)
    logger.debug("group_words_into_lines: %d words -> %d lines", len(items), len(lines))
    return lines


def _vertical_gradient_rgba(
    w: int,
    h: int,
    color_top: tuple[int, int, int, int],
    color_bottom: tuple[int, int, int, int],
) -> np.ndarray:
    """Vertical RGBA gradient: ``color_top`` at the top, ``color_bottom`` below."""
    top = np.array(color_top[:3], dtype=np.float32)
    bottom = np.array(color_bottom[:3], dtype=np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    column = top[None, :] * (1 - t) + bottom[None, :] * t
    rgb = np.repeat(column[:, None, :], w, axis=1)
    alpha_top = color_top[3] if len(color_top) > 3 else 255
    alpha_bottom = color_bottom[3] if len(color_bottom) > 3 else 255
    alpha_column = alpha_top * (1 - t[:, 0]) + alpha_bottom * t[:, 0]
    gradient = np.zeros((h, w, 4), dtype=np.uint8)
    gradient[..., :3] = rgb.astype(np.uint8)
    gradient[..., 3] = np.repeat(alpha_column[:, None], w, axis=1).astype(np.uint8)
    return gradient


def render_line_clips(
    line: Sequence[WordLike],
    w: int,
    h: int,
    font_path: str | Path,
    style: SubtitleStyle | None = None,
) -> list:
    """Render one line as a moviepy clip per word with active-word highlight.

    Each word in the line gets a full-line image clip: the spoken word is
    10% larger in blue ``#01abfe`` while the rest stays white, with a soft
    shadow for readability and no hard stroke. Transitions are instant with
    no overlap: each clip ends exactly when the next word starts.

    Returns:
        List of moviepy ``ImageClip`` objects (``moviepy`` is imported
        lazily so the rest of this module works without it).
    """
    from moviepy.editor import ImageClip

    resolved = _resolve_style(style)
    items = normalize_words(line)
    if not items:
        return []

    texts = [item.text.strip().upper() for item in items]
    base_size, big_size = font_sizes(w, resolved)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_w = w * resolved.max_width_pct

    clips = []
    for i, current in enumerate(items):
        # Shrink fonts until the line (with the active word enlarged) fits.
        small, large = base_size, big_size
        while True:
            font_base = load_font(font_path, small)
            font_active = load_font(font_path, large)
            space_w = probe.textlength(" ", font=font_base)
            widths = [
                probe.textlength(text, font=(font_active if j == i else font_base))
                for j, text in enumerate(texts)
            ]
            total_w = sum(widths) + space_w * (len(texts) - 1)
            if total_w <= max_w or small <= 20:
                break
            small -= 2
            large = max(small + 2, int(small * resolved.active_scale))

        asc_base, desc_base = font_base.getmetrics()
        asc_active, desc_active = font_active.getmetrics()
        max_asc = max(asc_base, asc_active)
        text_h = max_asc + max(desc_base, desc_active)
        margin = resolved.stroke_width * 2 + int(large * 0.15)
        if resolved.shadow:
            margin += (
                resolved.shadow_blur
                + max(abs(resolved.shadow_dx), abs(resolved.shadow_dy))
                + 2
            )
        img_w = int(total_w + margin * 2)
        img_h = int(text_h + margin * 2)

        line_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(line_img)
        shadow_layer = (
            Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
            if resolved.shadow
            else None
        )
        draw_shadow = ImageDraw.Draw(shadow_layer) if shadow_layer else None

        current_x = margin
        baseline_y = margin + max_asc
        active_xy = None
        active_text = None
        active_font = None
        for j, text in enumerate(texts):
            font = font_active if j == i else font_base
            asc, _ = font.getmetrics()
            xy = (current_x, baseline_y - asc)
            if draw_shadow is not None:
                draw_shadow.text(
                    (xy[0] + resolved.shadow_dx, xy[1] + resolved.shadow_dy),
                    text,
                    font=font,
                    fill=resolved.shadow_color,
                )
            if j == i:
                draw.text(
                    xy,
                    text,
                    font=font,
                    fill=resolved.stroke_color,
                    stroke_width=resolved.stroke_width,
                    stroke_fill=resolved.stroke_color,
                )
                active_xy = xy
                active_text = text
                active_font = font
            else:
                draw.text(
                    xy,
                    text,
                    font=font,
                    fill=resolved.base_color,
                    stroke_width=resolved.stroke_width,
                    stroke_fill=resolved.stroke_color,
                )
            current_x += widths[j] + space_w

        if active_xy is not None:
            if resolved.use_gradient:
                mask = Image.new("L", (img_w, img_h), 0)
                ImageDraw.Draw(mask).text(
                    active_xy, active_text, font=active_font, fill=255
                )
                gradient = _vertical_gradient_rgba(
                    img_w, img_h, resolved.gradient_top, resolved.gradient_bottom
                )
                line_img.paste(
                    Image.fromarray(gradient, mode="RGBA"), (0, 0), mask
                )
            else:
                draw.text(
                    active_xy,
                    active_text,
                    font=active_font,
                    fill=resolved.active_color,
                    stroke_width=resolved.stroke_width,
                    stroke_fill=resolved.stroke_color,
                )

        if shadow_layer is not None:
            shadow_layer = shadow_layer.filter(
                ImageFilter.GaussianBlur(resolved.shadow_blur)
            )
            line_img = Image.alpha_composite(shadow_layer, line_img)

        if i < len(items) - 1:
            display_end = items[i + 1].start
        else:
            display_end = current.end

        if display_end <= current.start:
            continue

        frame = np.array(line_img)
        y_pos = int(h * resolved.y_pct) - (img_h // 2)

        clip = (
            ImageClip(frame, transparent=True)
            .set_start(current.start)
            .set_duration(display_end - current.start)
            .set_position(("center", y_pos))
        )
        clips.append(clip)

    logger.debug("render_line_clips: %d words -> %d clips", len(items), len(clips))
    return clips


def format_srt_time(t: float) -> str:
    """Format seconds as an SRT timestamp (``HH:MM:SS,mmm``)."""
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    millis = int(round((t - int(t)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def write_srt(entries: Sequence[SrtLike], path: str | Path) -> Path:
    """Write subtitle entries to an SRT file (UTF-8).

    Accepts :class:`SrtEntry` items or ``(start, end, text)`` tuples and
    returns the output path.
    """
    out = Path(path)
    lines: list[str] = []
    for index, entry in enumerate(entries, 1):
        if isinstance(entry, SrtEntry):
            start, end, text = entry.start, entry.end, entry.text
        else:
            start, end, text = entry
        lines.append(f"{index}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{text}\n")
    out.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    logger.info("write_srt: wrote %d entries to %s", len(lines), out)
    return out
