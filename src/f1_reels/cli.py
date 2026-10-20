"""Command-line interface for the typed F1 reels pipeline.

Subcommands:

* ``edit`` -- build reels from a script text file over random B-roll.
* ``postprocess-bricks`` -- strip watermarks and trim heads of raw takes.

Design rules: English help/messages, :mod:`argparse` (no ``sys.argv``
reads), and no import-time side effects -- heavy third-party imports
(``moviepy``) happen inside the command
handlers so ``import f1_reels.cli`` is always cheap and safe.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .brick_config import LOGO_POR_VIDEO, TRIM_POR_TAKE

logger = logging.getLogger(__name__)

TOP_CUT_PCT = 0.22
BOTTOM_CUT_PCT = 0.18


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the ``f1-reels`` argument parser (no parsing performed here)."""
    parser = argparse.ArgumentParser(
        prog="f1-reels",
        description="Build F1 reels: B-roll editing and brick post-processing.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_edit = sub.add_parser(
        "edit",
        help="Edit one or more reels from a script text file.",
        description="Parse a script file (multi-video 'Name | process: Y' "
        "headers or a plain single script) and render each pending video "
        "over randomly assembled B-roll.",
    )
    p_edit.add_argument("text_file", type=Path, help="Script text file to edit.")
    p_edit.add_argument(
        "--output-dir",
        type=Path,
        default=Path("Videos_Editados"),
        help="Directory for finished .mp4/.srt files (default: Videos_Editados).",
    )
    p_edit.add_argument(
        "--bricks-dir",
        type=Path,
        default=None,
        help="Directory of post-processed bricks "
        "(default: <repo>/Post Processed Videos).",
    )
    p_edit.add_argument(
        "--font",
        type=Path,
        default=None,
        help="Subtitle font .ttf file (default: auto-detect Montserrat).",
    )
    p_edit.add_argument(
        "--margin",
        type=float,
        default=1.0,
        help="Seconds of video past the voice-over (default: 1.0).",
    )
    p_edit.add_argument(
        "--no-endcard",
        action="store_true",
        help="Disable the closing end card.",
    )
    p_edit.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible B-roll (default: random each run).",
    )
    p_edit.set_defaults(func=_cmd_edit)

    p_brick = sub.add_parser(
        "postprocess-bricks",
        help="Remove watermarks and trim heads of raw brick takes.",
        description="For every .mp4 brick: crop the F1 watermark band "
        "(top-left or bottom-left per video group) and trim leading seconds "
        "per take. Files with neither are stream-copied untouched.",
    )
    p_brick.add_argument(
        "--input",
        dest="input_dir",
        type=Path,
        default=Path("Video Bricks"),
        help="Directory with raw brick takes (default: 'Video Bricks').",
    )
    p_brick.add_argument(
        "--output",
        dest="output_dir",
        type=Path,
        default=Path("Post Processed Videos"),
        help="Destination directory (default: 'Post Processed Videos').",
    )
    p_brick.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-encode even if the output file already exists.",
    )
    p_brick.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned actions without running ffmpeg.",
    )
    p_brick.set_defaults(func=_cmd_postprocess_bricks)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (also exposed as the ``f1-reels`` console script)."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


# --------------------------------------------------------------------------
# edit
# --------------------------------------------------------------------------
def _cmd_edit(args: argparse.Namespace) -> int:
    """Render every pending block of the script file via the typed pipeline."""
    from .alignment import generate_voiceover
    from .config import Settings, find_first_font
    from .endcard import EndcardConfig
    from .pipeline import PipelineConfig, edit_video
    from .script_parser import SINGLE_VIDEO_NAME, parse_script_file
    from .subtitles import SubtitleStyle, group_words_into_lines, render_line_clips

    settings = Settings.from_env()
    text_file = Path(args.text_file)
    try:
        blocks = parse_script_file(text_file)
    except FileNotFoundError:
        logger.error("Script file not found: %s", text_file)
        return 2

    if not settings.openrouter_api_key:
        logger.error("Missing OPENROUTER_API_KEY in the environment (.env).")
        return 2

    if args.font:
        font = Path(args.font)
        if not font.is_file():
            logger.error("Subtitle font not found: %s", font)
            return 2
    else:
        try:
            font = find_first_font(settings.montserrat_fonts)
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return 2

    bricks_dir = Path(args.bricks_dir) if args.bricks_dir else settings.bricks_dir
    config = PipelineConfig(
        output_dir=Path(args.output_dir),
        bricks_dir=bricks_dir,
        margin_final=args.margin,
        speed_min=settings.brick_speed_min,
        speed_max=settings.brick_speed_max,
        min_fragment=settings.brick_min_fragment_sec,
        generate_srt=settings.generate_srt,
        original_volume=settings.original_video_volume,
        threads=settings.threads,
        seed=args.seed,
        endcard=EndcardConfig(
            logo_path=settings.endcard_logo,
            active=settings.endcard_enabled and not args.no_endcard,
            duration=settings.endcard_duration_sec,
            width_pct=settings.endcard_logo_width_pct,
            fade_black=settings.endcard_black_fade_sec,
            logo_delay=settings.endcard_logo_delay_sec,
            logo_fade=settings.endcard_logo_fade_sec,
            fade_out=settings.endcard_fade_out_sec,
        ),
    )
    style = SubtitleStyle(
        y_pct=settings.subtitle_y_pct,
        font_size_pct=settings.subtitle_font_size_pct,
        max_words_per_line=settings.subtitle_max_words_per_line,
        active_scale=settings.subtitle_active_scale,
        base_color=settings.subtitle_base_color,
        active_color=settings.subtitle_active_color,
        use_gradient=settings.subtitle_use_gradient,
        gradient_top=settings.subtitle_gradient_top,
        gradient_bottom=settings.subtitle_gradient_bottom,
        stroke_color=settings.subtitle_stroke_color,
        stroke_width=settings.subtitle_stroke_width,
        shadow=settings.subtitle_shadow_enabled,
        shadow_color=settings.subtitle_shadow_color,
        shadow_dx=settings.subtitle_shadow_dx,
        shadow_dy=settings.subtitle_shadow_dy,
        shadow_blur=settings.subtitle_shadow_blur,
        max_width_pct=settings.subtitle_max_width_pct,
    )

    if SINGLE_VIDEO_NAME in blocks:
        single = blocks[SINGLE_VIDEO_NAME]
        if not any(line.strip() for line in single.lines):
            logger.warning("Nothing to process (empty script).")
            return 0
        pending = [("Video_Broll", single)]
    else:
        pending = [
            (name, block)
            for name, block in blocks.items()
            if block.process and any(line.strip() for line in block.lines)
        ]
        skipped = len(blocks) - len(pending)
        logger.info("Pending: %d/%d videos (%d skipped).", len(pending), len(blocks), skipped)

    if not pending:
        logger.warning("Nothing to process (no block with process=Y and text).")
        return 0

    def subtitle_overlays(words, width, height, font_path):
        grouped = group_words_into_lines(words, width, font_path, style)
        clips: list = []
        for line in grouped:
            built = render_line_clips(line, width, height, font_path, style)
            if built:
                clips.extend(built)
        return clips

    tmp_dir = Path(tempfile.mkdtemp(prefix="voz_"))
    ok = fail = 0
    try:
        for video_name, block in pending:
            instructions = block.voice_direction

            def synthesize(text: str, audio_path: Path, _instructions: str = instructions):
                voiceover = generate_voiceover(
                    text,
                    audio_path,
                    voice=settings.openrouter_voice,
                    instructions=_instructions or None,
                    speed=settings.voice_speed,
                    subtitle_lead=settings.subtitle_lead_sec,
                    apply_punch=settings.reels_punch,
                    use_whisper=True,
                )
                stamps = [
                    (item.word, item.start, item.end) for item in voiceover.words
                ]
                return stamps, voiceover.duration

            logger.info("Editing %s (%d blocks).", video_name, len(block.lines))
            if edit_video(
                video_name,
                block.lines,
                font,
                tmp_dir,
                config=config,
                synthesize_speech=synthesize,
                subtitle_overlays=subtitle_overlays,
                instructions=instructions,
            ):
                logger.info("Saved %s.mp4.", video_name)
                ok += 1
            else:
                logger.error("Failed %s.", video_name)
                fail += 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info("Done. %d ok / %d failed.", ok, fail)
    return 0 if fail == 0 else 1


# --------------------------------------------------------------------------
# postprocess-bricks
# --------------------------------------------------------------------------
def _crop_window(w: int, h: int, where: str) -> tuple[int, int, int, int]:
    """Crop window ``(w2, h2, x, y)`` removing the logo while keeping 9:16."""
    if where == "TL":
        cut = int(round(h * TOP_CUT_PCT))
    elif where == "BL":
        cut = int(round(h * BOTTOM_CUT_PCT))
    else:  # pragma: no cover - guarded by callers
        raise ValueError(where)
    h2 = h - cut
    w2 = int(round(h2 * 9.0 / 16.0)) - (int(round(h2 * 9.0 / 16.0)) % 2)
    x = (w - w2) // 2
    return w2, h2, x, (cut if where == "TL" else 0)


def _process_one(entrada: Path, salida: Path, logo: str | None, trim: float) -> bool:
    """Post-process one brick via ffmpeg; return ``True`` on success."""
    import imageio_ffmpeg

    from moviepy.editor import VideoFileClip

    with VideoFileClip(str(entrada)) as probe:
        w, h = int(probe.w), int(probe.h)
        duration = float(probe.duration)
        has_audio = probe.audio is not None
    if trim >= duration - 0.3:
        logger.warning(
            "%s: trim %.1fs >= duration %.2fs, skipping.", entrada.name, trim, duration
        )
        return False

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-v", "error"]
    if trim > 0:
        cmd += ["-ss", f"{trim:.3f}"]
    cmd += ["-i", str(entrada)]
    if logo in ("TL", "BL"):
        w2, h2, x, y = _crop_window(w, h, logo)
        cmd += [
            "-vf", f"crop={w2}:{h2}:{x}:{y},scale={w}:{h}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        ]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac"] if has_audio else ["-an"]
    cmd += ["-movflags", "+faststart", str(salida)]
    action = logo if logo else "copy"
    logger.info(
        "%s trim=%gs %dx%d %.1fs -> %s", action, trim, w, h, duration, salida.name
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not salida.exists():
        logger.error("ffmpeg failed: %s", result.stderr.strip()[:300])
        return False
    return True


def _cmd_postprocess_bricks(args: argparse.Namespace) -> int:
    """Crop/trim every raw brick take into the output directory."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in input_dir.glob("*.mp4") if p.is_file() and not p.name.startswith(".")
    ) if input_dir.is_dir() else []
    if not files:
        logger.error("No .mp4 bricks in %s.", input_dir)
        return 1

    logger.info(
        "%d bricks -> %s (%s%s).",
        len(files),
        output_dir,
        "overwrite" if args.overwrite else "skip existing",
        ", dry run" if args.dry_run else "",
    )
    ok = skipped = failed = 0
    for entrada in files:
        salida = output_dir / entrada.name
        if salida.exists() and not args.overwrite:
            skipped += 1
            continue
        match = re.match(r"Video_(\d+)_take\d+\.mp4$", entrada.name, re.I)
        group = int(match.group(1)) if match else None
        logo = LOGO_POR_VIDEO.get(group) if group is not None else None
        trim = TRIM_POR_TAKE.get(entrada.name, 0.0)
        if args.dry_run:
            logger.info(
                "DRY-RUN %s logo=%s trim=%gs -> %s",
                entrada.name, logo, trim, salida.name,
            )
            ok += 1
            continue
        try:
            if _process_one(entrada, salida, logo, trim):
                ok += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error("%s: %s", entrada.name, exc)
            failed += 1

    logger.info("Done. %d ok / %d skipped / %d failed.", ok, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
