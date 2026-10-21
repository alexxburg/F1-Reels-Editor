"""FastAPI webapp for rendering reels in a single container.

Secrets come ONLY from the environment (``OPENROUTER_API_KEY``);
rendering choices come ONLY from ``config.json`` (see
``config.json.example``). Job flow: ``POST /api/jobs`` references bricks
from the configured server bricks dir into ``data_root/jobs/{uuid}/`` and
renders in a background task via :func:`f1_reels.pipeline.edit_video`
with the real OpenRouter :func:`f1_reels.alignment.generate_voiceover`
adapter and subtitle factories from :mod:`f1_reels.subtitles`.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .alignment import generate_voiceover as _generate_voiceover_impl
from .config import Settings, _default_project_root, load_config_file
from .endcard import EndcardConfig
from .pipeline import PipelineConfig
from .pipeline import edit_video as _edit_video_impl
from .subtitles import SubtitleStyle, group_words_into_lines, render_line_clips

logger = logging.getLogger(__name__)

# Serve .webp with the right type even on minimal Linux images.
mimetypes.add_type("image/webp", ".webp")

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
<button type="submit">Render</button>
</form>
<a id="download" href="#" hidden>Download</a>
<a id="download-srt" href="#" hidden>Download srt</a>
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


def _parse_speed(raw: str | float | None) -> float:
    if raw is None:
        return 1.05
    if isinstance(raw, float):
        value = raw
    elif isinstance(raw, int) and not isinstance(raw, bool):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            return 1.05
        try:
            value = float(text)
        except (TypeError, ValueError):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="invalid speed")
    if not 0.5 <= value <= 2.0:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="invalid speed")
    return value


def _sanitize_name(name: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip()
    ).strip("_")
    return cleaned or "reel"


def resolve_config_path(explicit: Path | str | None = None) -> Path:
    """Return the config file path, first existing of the search order.

    Order: explicit ``config_path`` arg, ``$CONFIG_PATH``, then
    ``<project-root>/config.json``, then ``<cwd>/config.json``.

    Raises:
        RuntimeError: If no candidate exists.
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit).expanduser())
    env_path = os.getenv("CONFIG_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(_default_project_root() / "config.json")
    candidates.append(Path.cwd() / "config.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "Config file not found. Copy config.json.example to config.json "
        "(or set CONFIG_PATH) and adjust the rendering choices. "
        f"Searched: {', '.join(str(c) for c in candidates)}"
    )


def create_app(
    data_root: Path | None = None, config_path: Path | str | None = None
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        data_root: Base directory for job data. Defaults to ``$DATA_ROOT``
            or ``<cwd>/data`` (``/app/data`` in the container). Each job
            lives under ``data_root/jobs/{uuid}/`` with ``bricks/`` and
            ``outputs/``.
        config_path: Explicit config file. Defaults to the
            :func:`resolve_config_path` search order
            (``$CONFIG_PATH``, ``<project-root>/config.json``,
            ``<cwd>/config.json``).

    Returns:
        Configured FastAPI application with in-memory job tracking.

    Raises:
        RuntimeError: If no config file exists.
        ValueError: If the config file holds secrets or unknown keys.
    """
    settings = Settings.from_config(load_config_file(resolve_config_path(config_path)))
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
    app.state.settings = settings
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
        speed: str = Form(default=""),
        margin: float = Form(default=1.0),
        punch: str = Form(default="on"),
        seed: str = Form(default=""),
    ) -> dict[str, str]:
        lines = [line.strip() for line in script_lines.splitlines() if line.strip()]
        if not lines:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="empty script")
        parsed_speed = _parse_speed(speed)
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="missing OpenRouter API key")
        bricks_source = settings.bricks_dir
        if not bricks_source.is_dir():
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"bricks dir not found: {bricks_source}",
            )
        available = sorted(
            p
            for p in bricks_source.iterdir()
            if p.is_file()
            and p.suffix.lower() in {ext.lower() for ext in settings.brick_extensions}
        )
        if not available:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"no bricks available in {bricks_source}",
            )
        logo_path = settings.endcard_logo
        if not logo_path.is_file():
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"endcard logo not found: {logo_path}",
            )
        font_path = settings.subtitle_font
        if not font_path.is_file():
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"subtitle font not found: {font_path}",
            )

        job_id = uuid.uuid4().hex
        job_dir = jobs_root / job_id
        bricks_dir = job_dir / "bricks"
        outputs_dir = job_dir / "outputs"
        tmp_dir = job_dir / "tmp"
        bricks_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for source in available:
            shutil.copy2(source, bricks_dir / source.name)

        reel_name = _sanitize_name(name)
        use_punch = _parse_bool(punch, True)
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
                detected_font = font_path
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

                overlays = subtitle_overlays
                font_arg = detected_font

                def synthesize(text: str, audio_path: Path):
                    voiceover = generate_voiceover(
                        text,
                        audio_path,
                        voice=settings.openrouter_voice,
                        model=settings.openrouter_tts_model,
                        instructions=voice_direction or None,
                        speed=parsed_speed,
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
                        logo_path=logo_path,
                        active=True,
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

    @app.get("/api/reels")
    def list_reels() -> dict[str, Any]:
        from datetime import datetime, timezone

        reels: list[dict[str, Any]] = []
        try:
            job_dirs = sorted(jobs_root.iterdir())
        except OSError:
            job_dirs = []
        for job_dir in job_dirs:
            if not job_dir.is_dir():
                continue
            job_id = job_dir.name
            outputs_dir = job_dir / "outputs"
            if not outputs_dir.is_dir():
                continue
            try:
                mp4_paths = sorted(outputs_dir.glob("*.mp4"))
            except OSError:
                continue
            for mp4_path in mp4_paths:
                if not mp4_path.is_file():
                    continue
                name = mp4_path.stem
                if not name:
                    continue
                srt_path = outputs_dir / f"{name}.srt"
                try:
                    stat = mp4_path.stat()
                    size = int(stat.st_size)
                    modified = datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat()
                except OSError:
                    continue
                reels.append(
                    {
                        "job_id": job_id,
                        "name": name,
                        "mp4": True,
                        "srt": bool(srt_path.is_file()),
                        "size": size,
                        "modified": modified,
                    }
                )
        reels.sort(key=lambda entry: entry["modified"], reverse=True)
        return {"reels": reels}

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

    @app.delete("/api/jobs/{job_id}")
    def job_delete(job_id: str) -> dict[str, str]:
        from fastapi import HTTPException

        if not re.fullmatch(r"[0-9a-f]{32}", job_id or ""):
            raise HTTPException(status_code=404, detail="unknown job")
        record = jobs.pop(job_id, None)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown job")
        shutil.rmtree(jobs_root / job_id, ignore_errors=True)
        logger.info("Job %s deleted.", job_id)
        return {"deleted": job_id}

    return app


APP = create_app()
