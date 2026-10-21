"""FastAPI webapp for rendering reels in a single container.

Job flow: ``POST /api/jobs`` saves uploaded bricks into
``data_root/jobs/{uuid}/`` and renders in a background task via
:func:`f1_reels.pipeline.edit_video` with the real OpenRouter
:func:`f1_reels.alignment.generate_voiceover` adapter and subtitle
factories from :mod:`f1_reels.subtitles`.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .alignment import generate_voiceover as _generate_voiceover_impl
from .config import Settings, find_first_font
from .endcard import EndcardConfig
from .pipeline import PipelineConfig
from .pipeline import edit_video as _edit_video_impl
from .subtitles import SubtitleStyle, group_words_into_lines, render_line_clips

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Module-level aliases so tests can monkeypatch ``webapp.edit_video`` or
# ``webapp.generate_voiceover`` to avoid network/moviepy work.
edit_video = _edit_video_impl
generate_voiceover = _generate_voiceover_impl

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>F1 Reels</title></head>
<body>
<h1>F1 Reels</h1>
<form action="/api/jobs" method="post" enctype="multipart/form-data">
<label>Reel name <input name="name" value=""></label><br>
<label>Script lines <textarea name="script_lines"></textarea></label><br>
<label>Bricks <input type="file" name="bricks" multiple></label><br>
<button type="submit">Render</button>
</form>
<a id="download" href="#" hidden>Download</a>
</body>
</html>
"""


def _parse_bool(raw: str | bool | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def _parse_seed(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    return int(text)


def _sanitize_name(name: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip()
    ).strip("_")
    return cleaned or "reel"


def create_app(data_root: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        data_root: Base directory for job data. Defaults to ``$DATA_ROOT``
            or ``<cwd>/data`` (``/app/data`` in the container). Each job
            lives under ``data_root/jobs/{uuid}/`` with ``bricks/`` and
            ``outputs/``.

    Returns:
        Configured FastAPI application with in-memory job tracking.
    """
    if data_root is None:
        env_root = os.getenv("DATA_ROOT", "").strip()
        if env_root:
            resolved_root = Path(env_root).expanduser()
        else:
            resolved_root = Path.cwd() / "data"
    else:
        resolved_root = Path(data_root)
    jobs_root = resolved_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="F1 Reels Webapp")
    jobs: dict[str, dict[str, Any]] = {}
    app.state.jobs = jobs
    app.state.data_root = resolved_root
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        try:
            return TEMPLATE_PATH.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Template %s missing, using placeholder.", TEMPLATE_PATH)
            return PLACEHOLDER_HTML

    @app.post("/api/jobs")
    async def create_job(
        background_tasks: BackgroundTasks,
        name: str = Form(default=""),
        script_lines: str = Form(default=""),
        voice_direction: str = Form(default=""),
        openrouter_key: str = Form(default=""),
        openrouter_model: str = Form(
            default="google/gemini-3.8-flash-tts"
        ),
        openrouter_voice: str = Form(default=""),
        voice: str = Form(default=""),
        speed: float = Form(default=1.05),
        margin: float = Form(default=1.0),
        punch: str = Form(default="on"),
        seed: str = Form(default=""),
        endcard: str = Form(default="on"),
        bricks: list[UploadFile] = File(default=[]),
        logo: UploadFile | None = File(default=None),
        font: UploadFile | None = File(default=None),
    ) -> dict[str, str]:
        lines = [line.strip() for line in script_lines.splitlines() if line.strip()]
        if not lines:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="empty script")
        api_key = openrouter_key.strip() or os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="missing OpenRouter API key")
        uploads = [b for b in (bricks or []) if b.filename]
        if not uploads:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="no bricks uploaded")

        job_id = uuid.uuid4().hex
        job_dir = jobs_root / job_id
        bricks_dir = job_dir / "bricks"
        outputs_dir = job_dir / "outputs"
        tmp_dir = job_dir / "tmp"
        bricks_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for upload in uploads:
            dest = bricks_dir / Path(upload.filename or "brick.mp4").name
            content = await upload.read()
            dest.write_bytes(content)
        logo_path: Path | None = None
        if logo is not None and logo.filename:
            logo_path = job_dir / Path(logo.filename).name
            logo_path.write_bytes(await logo.read())
        font_upload_path: Path | None = None
        if font is not None and font.filename:
            font_upload_path = job_dir / Path(font.filename).name
            font_upload_path.write_bytes(await font.read())

        reel_name = _sanitize_name(name)
        resolved_voice = (
            openrouter_voice.strip() or voice.strip() or "Puck"
        )
        use_punch = _parse_bool(punch, True)
        use_endcard = _parse_bool(endcard, True)
        try:
            parsed_seed = _parse_seed(seed)
        except ValueError:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="invalid seed")

        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "message": "queued",
            "name": reel_name,
            "files": [],
        }

        def run_job() -> None:
            record = jobs[job_id]
            record["status"] = "running"
            record["message"] = "rendering"
            try:
                settings = Settings.from_env()
                try:
                    detected_font = font_upload_path or find_first_font(
                        settings.montserrat_fonts
                    )
                except FileNotFoundError:
                    detected_font = None
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

                def subtitle_overlays(words, width, height, font_path):
                    grouped = group_words_into_lines(words, width, font_path, style)
                    clips: list = []
                    for line in grouped:
                        built = render_line_clips(line, width, height, font_path, style)
                        if built:
                            clips.extend(built)
                    return clips

                overlays = subtitle_overlays if detected_font is not None else None
                font_arg = detected_font if detected_font is not None else ""

                def synthesize(text: str, audio_path: Path):
                    os.environ["OPENROUTER_API_KEY"] = api_key
                    voiceover = generate_voiceover(
                        text,
                        audio_path,
                        voice=resolved_voice,
                        instructions=voice_direction or None,
                        speed=speed,
                        subtitle_lead=settings.subtitle_lead_sec,
                        apply_punch=use_punch,
                        use_whisper=True,
                    )
                    stamps = [
                        (item.word, item.start, item.end)
                        for item in voiceover.words
                    ]
                    return stamps, voiceover.duration

                config = PipelineConfig(
                    output_dir=outputs_dir,
                    bricks_dir=bricks_dir,
                    margin_final=margin,
                    speed_min=settings.brick_speed_min,
                    speed_max=settings.brick_speed_max,
                    min_fragment=settings.brick_min_fragment_sec,
                    generate_srt=settings.generate_srt,
                    original_volume=settings.original_video_volume,
                    threads=settings.threads,
                    seed=parsed_seed,
                    endcard=EndcardConfig(
                        logo_path=logo_path or settings.endcard_logo,
                        active=settings.endcard_enabled and use_endcard,
                        duration=settings.endcard_duration_sec,
                        width_pct=settings.endcard_logo_width_pct,
                        fade_black=settings.endcard_black_fade_sec,
                        logo_delay=settings.endcard_logo_delay_sec,
                        logo_fade=settings.endcard_logo_fade_sec,
                        fade_out=settings.endcard_fade_out_sec,
                    ),
                )
                ok = edit_video(
                    reel_name,
                    lines,
                    font_arg,
                    tmp_dir,
                    config=config,
                    synthesize_speech=synthesize,
                    subtitle_overlays=overlays,
                    instructions=voice_direction,
                )
                mp4_path = outputs_dir / f"{reel_name}.mp4"
                srt_path = outputs_dir / f"{reel_name}.srt"
                if ok and mp4_path.exists():
                    made = [mp4_path.name]
                    if srt_path.exists():
                        made.append(srt_path.name)
                    record["status"] = "done"
                    record["message"] = "done"
                    record["files"] = made
                else:
                    record["status"] = "error"
                    record["message"] = "render failed"
            except Exception as exc:
                logger.error("Job %s failed: %s", job_id, exc)
                record["status"] = "error"
                record["message"] = f"error: {exc}"[:500]

        background_tasks.add_task(run_job)
        logger.info("Job %s queued for reel %s.", job_id, reel_name)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        from fastapi import HTTPException

        record = jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return record

    @app.get("/api/jobs/{job_id}/download")
    def job_download(job_id: str, format: str = "mp4"):  # noqa: A002
        from fastapi import HTTPException

        record = jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown job")
        reel_name = str(record.get("name", "reel"))
        outputs_dir = jobs_root / job_id / "outputs"
        if format == "srt":
            srt_path = outputs_dir / f"{reel_name}.srt"
            if not srt_path.exists():
                raise HTTPException(status_code=404, detail="srt not ready")
            return FileResponse(
                str(srt_path), media_type="text/plain", filename=srt_path.name
            )
        mp4_path = outputs_dir / f"{reel_name}.mp4"
        if not mp4_path.exists():
            raise HTTPException(status_code=404, detail="mp4 not ready")
        return FileResponse(
            str(mp4_path), media_type="video/mp4", filename=mp4_path.name
        )

    return app


APP = create_app()
