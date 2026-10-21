# Docker Webapp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a single-container FastAPI webapp on LAN port 8001 that renders reels and offers mp4/srt downloads.

**Architecture:** `src/f1_reels/webapp.py` app factory reuses `Settings`/`parse_script_file`/`generate_voiceover`/`edit_video`; in-process background jobs under `data/jobs/{id}/`; vanilla HTML form polls `GET /api/jobs/{id}` then shows download button.

**Tech Stack:** Python >=3.10, FastAPI 0.111, uvicorn 0.30, moviepy 1.0.3, imageio-ffmpeg, faster-whisper, Docker 29 + Compose v5

**Spec:** `docs/superpowers/specs/2026-10-21-docker-webapp-design.md`

## Global Constraints

- Python requires-python >=3.10.
- OpenRouter-only: no `edge_tts`, `EdgeTTS`, `EDGE_VOICE`, `TTS_BACKEND`, `sample-voices` tokens in `src/`, `pyproject.toml`, `requirements.txt`, `.env.example`.
- English identifiers/docstrings/messages only; `pathlib.Path` for paths; `logging` not `print`.
- Bind `uvicorn` to `0.0.0.0:8001`; Compose publishes `8001:8001`; volumes for job data/outputs.
- TDD: failing test first, watch it fail for expected reason, minimal fix, full `PYTHONPATH=src python3 -m pytest tests/ -v` green.

## Review Focus

- Empty script submission should return 400 with message, not queue a job — needs empty-script test.
- Missing OpenRouter key should fail fast with 400 before any ffmpeg work — needs missing-key test.
- Corrupt brick upload should not crash job listing; job goes `error` with log tail — needs bad-brick test.
- Odd-height brick must keep even crop dims — covered by existing crop tests, reused here.
- Re-render with same seed should be reproducible — needs seed passthrough test.

---

### Task 1: Webapp backend with job API

**Files:**
- Create: `src/f1_reels/webapp.py`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `Settings.from_env() -> Settings`, `parse_script_file(Path) -> dict[str,ScriptBlock]` (not used directly; form posts parsed lines), `generate_voiceover(text,audio_path,voice,instructions,speed,subtitle_lead,apply_punch,use_whisper) -> Voiceover`, `edit_video(name,lines,font_path,tmp_dir,config,synthesize_speech,subtitle_overlays,instructions) -> bool`
- Produces: `create_app(data_root: Path | None = None) -> FastAPI`; `POST /api/jobs -> {job_id}`; `GET /api/jobs/{job_id} -> {status, message, files}`; `GET /api/jobs/{job_id}/download -> mp4`; `GET /api/jobs/{job_id}/download?format=srt -> srt`; `GET / -> HTML`

- [ ] **Step 1: Write the failing test**

```python
def test_create_job_and_download_with_fakes():
    client = TestClient(create_app(tmp_path))
    r = client.post("/api/jobs", data={...minimal fields...}, files=[...])
    assert r.status_code == 200
    assert client.get(f"/api/jobs/{r.json()['job_id']}").json()["status"] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_webapp.py -v`
Expected: FAIL with "create_app not defined"

- [ ] **Step 3: Implement `create_app(data_root: Path | None = None) -> FastAPI` in `src/f1_reels/webapp.py`**

In-process jobs dict + BackgroundTasks; job dir `data_root/jobs/{uuid}/` with `bricks/`, `outputs/`; form fields: `name, script_lines, voice_direction, openrouter_key/model/voice, speed, punch, margin, seed, endcard`; files: `bricks[]`, `logo?`, `font?`; synthesize via real `generate_voiceover`, overlays via `group_words_into_lines/render_line_clips`; missing key/script/bricks → 400.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest tests/test_webapp.py -v`
Expected: PASS (moviepy/network faked via monkeypatched `edit_video` or tiny stubs)

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/webapp.py tests/test_webapp.py
git commit -m "feat: add FastAPI reel job webapp backend"
```

### Task 2: Browser form with download button

**Files:**
- Create: `src/f1_reels/templates/index.html`
- Create: `src/f1_reels/static/app.js` (or inline if smaller)
- Test: extend `tests/test_webapp.py`

**Interfaces:**
- Consumes: Task 1 routes (`GET /`, `POST /api/jobs`, `GET /api/jobs/{id}`, download URLs)
- Produces: Form posting all reel inputs; polling JS enabling `<a id="download">` on `done`.

- [ ] **Step 1: Write the failing test**

```python
def test_index_form_has_all_inputs_and_download_button():
    html = client.get("/").text
    assert 'name="script_lines"' in html and 'id="download"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_webapp.py::test_index_form_has_all_inputs_and_download_button -v`
Expected: FAIL (template missing fields)

- [ ] **Step 3: Implement template + JS** in `src/f1_reels/templates/index.html` (Jinja2 `TemplateResponse` or plain `HTMLResponse` + `FileResponse` static)

All inputs from spec §Components; JS `fetch` POST then `setInterval` poll, shows status, sets download `href` on `done` (+srt link).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest tests/test_webapp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/templates/index.html src/f1_reels/static/app.js tests/test_webapp.py
git commit -m "feat: add reel web form with download button"
```

### Task 3: Docker packaging for LAN

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Modify: `pyproject.toml`, `requirements.txt`
- Test: `tests/test_docker.py`

**Interfaces:**
- Consumes: `src/f1_reels/webapp.py:create_app`, `f1-reels` package
- Produces: `docker compose up --build` serving `http://<lan-ip>:8001`

- [ ] **Step 1: Write the failing test**

```python
def test_docker_files_publish_lan_port_with_ffmpeg():
    text = Path("Dockerfile").read_text()
    assert "ffmpeg" in text and "0.0.0.0" in text or "8001" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_docker.py -v`
Expected: FAIL (files missing)

- [ ] **Step 3: Implement `Dockerfile` (python:3.12-slim + ffmpeg + `pip install .`), `docker-compose.yml` (ports `8001:8001`, volumes `./data:/app/data`), `.dockerignore`; add `fastapi>=0.111`, `uvicorn>=0.30` to `pyproject.toml` + pins in `requirements.txt`**

`CMD ["uvicorn","f1_reels.webapp:APP","--host","0.0.0.0","--port","8001"]` via module-level `APP = create_app()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest tests/test_docker.py tests/test_webapp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore pyproject.toml requirements.txt tests/test_docker.py
git commit -m "feat: add Docker LAN packaging on port 8001"
```

### Task 4: Docs + full verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_webapp.py`, `tests/test_docker.py`

**Interfaces:**
- Consumes: Tasks 1–3 done
- Produces: LAN run instructions + green suite + `docker compose config` valid.

- [ ] **Step 1: Write the failing test**

```python
def test_readme_documents_lan_webapp():
    assert "docker compose up --build" in Path("README.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_docs.py -v` (or inline grep test)
Expected: FAIL (README lacks section)

- [ ] **Step 3: Implement README section** (prereqs, `docker compose up --build`, open `http://<lan-ip>:8001`, fill form, download mp4/srt, `OPENROUTER_API_KEY` config)

- [ ] **Step 4: Run full verification to verify it passes**

Run: `PYTHONPATH=src python3 -m pytest tests/ -v` Expected: PASS (109+ new, 0 failures); Run: `docker compose config` Expected: valid
- [ ] **Step 5: Commit**

```bash
git add README.md tests/
git commit -m "docs: document Docker LAN webapp usage"
```
