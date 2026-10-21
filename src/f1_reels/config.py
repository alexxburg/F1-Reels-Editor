"""Application settings loaded from environment variables.

Every field has a typed default.
Use :meth:`Settings.from_env` to build an instance; paths default to
locations relative to the project root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_project_root() -> Path:
    """Return the project root (parent of ``src/``)."""
    return Path(__file__).resolve().parents[2]


def _get_str(key: str, default: str) -> str:
    value: str = os.getenv(key, "")
    return value if value != "" else default


def _get_int(key: str, default: int) -> int:
    raw: str = os.getenv(key, "").strip()
    if not raw:
        return default
    return int(raw)


def _get_float(key: str, default: float) -> float:
    raw: str = os.getenv(key, "").strip()
    if not raw:
        return default
    return float(raw)


def _get_bool(key: str, default: bool) -> bool:
    raw: str = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"Invalid boolean value for {key}: {raw!r}")


def _get_path(key: str, default: Path) -> Path:
    raw: str = os.getenv(key, "").strip()
    if not raw:
        return default
    candidate: Path = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = _default_project_root() / candidate
    return candidate


def _get_str_tuple(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw: str = os.getenv(key, "").strip()
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_color(raw: str) -> tuple[int, int, int, int]:
    parts: list[str] = [item.strip() for item in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Invalid RGBA color: {raw!r} (expected R,G,B,A)")
    red, green, blue, alpha = (int(item) for item in parts)
    return (red, green, blue, alpha)


def _get_color(key: str, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    raw: str = os.getenv(key, "").strip()
    if not raw:
        return default
    return _parse_color(raw)


def _default_montserrat_fonts(project_root: Path) -> tuple[str, ...]:
    """Return the font search order for Montserrat ExtraBold."""
    home: Path = Path.home()
    return (
        "/Library/Fonts/Montserrat-ExtraBold.ttf",
        str(home / "Library/Fonts/Montserrat-ExtraBold.ttf"),
        str(project_root / "Montserrat-ExtraBold.ttf"),
        "/Library/Fonts/Montserrat-Bold.ttf",
        "/Library/Fonts/Montserrat-Black.ttf",
        str(home / "Library/Fonts/Montserrat-Bold.ttf"),
        str(home / "Library/Fonts/Montserrat-Black.ttf"),
        str(project_root / "Montserrat-Bold.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    )


@dataclass(frozen=True)
class Settings:
    """Typed application configuration with environment overrides."""

    project_root: Path = field(default_factory=_default_project_root)
    videos_dir: Path = field(default_factory=lambda: _default_project_root() / "Videos")
    bricks_dir: Path = field(
        default_factory=lambda: _default_project_root() / "Post Processed Videos"
    )
    output_dir: Path = field(
        default_factory=lambda: _default_project_root() / "Videos_Editados"
    )
    script_file: Path = field(default_factory=lambda: _default_project_root() / "textos.txt")
    video_input: str = ""

    crop_top_pct: float = 0.22
    crop_rescale_to_original: bool = True

    final_margin_sec: float = 1.0
    brick_speed_min: float = 0.95
    brick_speed_max: float = 1.05
    brick_min_fragment_sec: float = 1.0
    brick_extensions: tuple[str, ...] = (".mp4", ".mov", ".m4v")

    endcard_enabled: bool = True
    endcard_logo: Path = field(
        default_factory=lambda: _default_project_root() / "RC-Logo White Full - PNG.png"
    )
    endcard_duration_sec: float = 2.0
    endcard_logo_width_pct: float = 0.86
    endcard_black_fade_sec: float = 1.2
    endcard_logo_delay_sec: float = 0.3
    endcard_logo_fade_sec: float = 1.0
    endcard_fade_out_sec: float = 0.6

    openrouter_api_key: str = ""
    openrouter_tts_model: str = "google/gemini-3.8-flash-tts"
    openrouter_voice: str = "Puck"
    openrouter_response_format: str = "pcm"
    original_video_volume: float = 0.0
    generate_srt: bool = True
    voice_speed: float = 1.05
    reels_punch: bool = True

    subtitle_y_pct: float = 0.62
    subtitle_font_size_pct: float = 0.066
    subtitle_max_words_per_line: int = 20
    subtitle_active_scale: float = 1.10
    subtitle_lead_sec: float = 0.12
    subtitle_base_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    subtitle_active_color: tuple[int, int, int, int] = (0x01, 0xAB, 0xFE, 255)
    subtitle_use_gradient: bool = False
    subtitle_gradient_top: tuple[int, int, int, int] = (0x00, 0xD9, 0xFD, 255)
    subtitle_gradient_bottom: tuple[int, int, int, int] = (0x01, 0x69, 0xFE, 255)
    subtitle_stroke_color: tuple[int, int, int, int] = (0, 0, 0, 255)
    subtitle_stroke_width: int = 0
    subtitle_shadow_enabled: bool = True
    subtitle_shadow_color: tuple[int, int, int, int] = (0, 0, 0, 170)
    subtitle_shadow_dx: int = 0
    subtitle_shadow_dy: int = 5
    subtitle_shadow_blur: int = 8
    subtitle_max_width_pct: float = 0.96
    subtitle_block_gap_sec: float = 0.25

    montserrat_fonts: tuple[str, ...] = ()
    threads: int = 4

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables, falling back to defaults."""
        defaults: Settings = cls()
        root: Path = _get_path("PROJECT_ROOT", defaults.project_root)
        montserrat_default: tuple[str, ...] = _default_montserrat_fonts(root)
        return cls(
            project_root=root,
            videos_dir=_get_path("VIDEOS_DIR", root / "Videos"),
            bricks_dir=_get_path("BRICKS_DIR", root / "Post Processed Videos"),
            output_dir=_get_path("OUTPUT_DIR", root / "Videos_Editados"),
            script_file=_get_path("SCRIPT_FILE", root / "textos.txt"),
            video_input=_get_str("VIDEO_INPUT", ""),
            crop_top_pct=_get_float("CROP_TOP_PCT", 0.22),
            crop_rescale_to_original=_get_bool("CROP_RESCALE_TO_ORIGINAL", True),
            final_margin_sec=_get_float("FINAL_MARGIN_SEC", 1.0),
            brick_speed_min=_get_float("BRICK_SPEED_MIN", 0.95),
            brick_speed_max=_get_float("BRICK_SPEED_MAX", 1.05),
            brick_min_fragment_sec=_get_float("BRICK_MIN_FRAGMENT_SEC", 1.0),
            brick_extensions=_get_str_tuple("BRICK_EXTENSIONS", (".mp4", ".mov", ".m4v")),
            endcard_enabled=_get_bool("ENDCARD_ENABLED", True),
            endcard_logo=_get_path(
                "ENDCARD_LOGO", root / "RC-Logo White Full - PNG.png"
            ),
            endcard_duration_sec=_get_float("ENDCARD_DURATION_SEC", 2.0),
            endcard_logo_width_pct=_get_float("ENDCARD_LOGO_WIDTH_PCT", 0.86),
            endcard_black_fade_sec=_get_float("ENDCARD_BLACK_FADE_SEC", 1.2),
            endcard_logo_delay_sec=_get_float("ENDCARD_LOGO_DELAY_SEC", 0.3),
            endcard_logo_fade_sec=_get_float("ENDCARD_LOGO_FADE_SEC", 1.0),
            endcard_fade_out_sec=_get_float("ENDCARD_FADE_OUT_SEC", 0.6),
            openrouter_api_key=_get_str("OPENROUTER_API_KEY", ""),
            openrouter_tts_model=_get_str(
                "OPENROUTER_TTS_MODEL", "google/gemini-3.8-flash-tts"
            ),
            openrouter_voice=_get_str("OPENROUTER_VOICE", "Puck"),
            openrouter_response_format=_get_str("OPENROUTER_RESPONSE_FORMAT", "pcm"),
            original_video_volume=_get_float("ORIGINAL_VIDEO_VOLUME", 0.0),
            generate_srt=_get_bool("GENERATE_SRT", True),
            voice_speed=_get_float("VOICE_SPEED", 1.05),
            reels_punch=_get_bool("REELS_PUNCH", True),
            subtitle_y_pct=_get_float("SUBTITLE_Y_PCT", 0.62),
            subtitle_font_size_pct=_get_float("SUBTITLE_FONT_SIZE_PCT", 0.066),
            subtitle_max_words_per_line=_get_int("SUBTITLE_MAX_WORDS_PER_LINE", 20),
            subtitle_active_scale=_get_float("SUBTITLE_ACTIVE_SCALE", 1.10),
            subtitle_lead_sec=_get_float("SUBTITLE_LEAD_SEC", 0.12),
            subtitle_base_color=_get_color(
                "SUBTITLE_BASE_COLOR", (255, 255, 255, 255)
            ),
            subtitle_active_color=_get_color(
                "SUBTITLE_ACTIVE_COLOR", (0x01, 0xAB, 0xFE, 255)
            ),
            subtitle_use_gradient=_get_bool("SUBTITLE_USE_GRADIENT", False),
            subtitle_gradient_top=_get_color(
                "SUBTITLE_GRADIENT_TOP", (0x00, 0xD9, 0xFD, 255)
            ),
            subtitle_gradient_bottom=_get_color(
                "SUBTITLE_GRADIENT_BOTTOM", (0x01, 0x69, 0xFE, 255)
            ),
            subtitle_stroke_color=_get_color(
                "SUBTITLE_STROKE_COLOR", (0, 0, 0, 255)
            ),
            subtitle_stroke_width=_get_int("SUBTITLE_STROKE_WIDTH", 0),
            subtitle_shadow_enabled=_get_bool("SUBTITLE_SHADOW_ENABLED", True),
            subtitle_shadow_color=_get_color(
                "SUBTITLE_SHADOW_COLOR", (0, 0, 0, 170)
            ),
            subtitle_shadow_dx=_get_int("SUBTITLE_SHADOW_DX", 0),
            subtitle_shadow_dy=_get_int("SUBTITLE_SHADOW_DY", 5),
            subtitle_shadow_blur=_get_int("SUBTITLE_SHADOW_BLUR", 8),
            subtitle_max_width_pct=_get_float("SUBTITLE_MAX_WIDTH_PCT", 0.96),
            subtitle_block_gap_sec=_get_float("SUBTITLE_BLOCK_GAP_SEC", 0.25),
            montserrat_fonts=_get_str_tuple("MONTSERRAT_FONTS", montserrat_default),
            threads=_get_int("THREADS", 4),
        )


def find_first_font(fonts: tuple[str, ...] | list[str]) -> Path:
    """Return the first existing font from ``fonts``.

    Args:
        fonts: Candidate font paths in preference order.

    Returns:
        The first path that exists on disk.

    Raises:
        FileNotFoundError: If no candidate exists.
    """
    for candidate in fonts:
        path = Path(candidate)
        if path.is_file():
            return path
    raise FileNotFoundError(f"No subtitle font found (checked {len(list(fonts))} paths).")
