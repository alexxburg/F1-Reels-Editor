# Docker Webapp (Local Network) Design

**Goal:** Single-container Docker webapp on LAN: fill reel inputs in browser, render via `src/f1_reels`, download `.mp4` (+`.srt`).

**Approach chosen:** FastAPI + vanilla HTML + in-process background jobs + `uvicorn --host 0.0.0.0`. Rejected Streamlit/Gradio (heavier, worse downloads) and split React frontend (overkill, YAGNI).

## Architecture

- `src/f1_reels/webapp.py` (FastAPI app factory) + `templates/index.html` + `static/` (vanilla form + fetch polling). No SPA build.
- `Dockerfile` (python:3.12-slim + `ffmpeg` apt layer + `pip install .`) + `docker-compose.yml` (port `8001:8001`, volumes for `outputs/`, `bricks/`). Port 8001 free; 8000/8080/5000 occupied.
- Reuse `Settings`, `parse_script_file`, `generate_voiceover`, `PipelineConfig/edit_video`, `BrollSelector`, `find_first_font` — no logic duplication.

## Components

1. `GET /` form: reel name, script lines textarea (one per line), process flag auto-Y, voice-direction box, OpenRouter key/model/voice, speed, punch toggle, margin, seed, endcard toggle, bricks multi-upload, logo/font optional upload.
2. `POST /api/jobs` multipart: saves uploads to job dir, returns `job_id`.
3. `GET /api/jobs/{id}` polling: `queued|running|done|error` + progress message.
4. `GET /api/jobs/{id}/download` mp4 + `...?format=srt` sidecar. `GET /api/jobs/{id}/preview` optional.

## Data flow

Form → job dir `data/jobs/{id}/` (script.txt, bricks/, outputs/) → background `edit_video()` with injected `generate_voiceover` → outputs `{name}.mp4/.srt` → download button enabled on `done`.

## Error handling

Missing key/bricks/script → 400 with message; render failure → `error` state + log tail; trim>=duration bricks skipped; odd-height crop stays even; no bare `except`.

## Testing

`tests/test_webapp.py` (TestClient, no network/moviepy: fake `synthesize_speech`, tiny fake bricks dir), `tests/test_docker.py` (Dockerfile/compose parse checks: ffmpeg layer, 0.0.0.0, port publish, volumes). Full `pytest` green required.
