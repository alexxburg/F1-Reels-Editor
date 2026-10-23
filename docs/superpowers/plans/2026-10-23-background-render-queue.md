# Background Render Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Submitting a reel queues it on a single-worker FIFO thread, resets the generator, and surfaces progress in the Explorer.

**Architecture:** `POST /api/jobs` only validates + enqueues a per-job `run_job` closure onto a per-app `queue.Queue`; one daemon worker thread per app drains it. New `GET /api/jobs` exposes active records; generator drops its private poll/progress/download; Explorer renders active rows with a 2 s visible-only poll.

**Tech Stack:** FastAPI + stdlib `threading`/`queue`; vanilla JS; pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-10-23-background-render-queue-design.md`

## Global Constraints

- `/api/reels` response shape unchanged (`{"reels": [...]}` finished-only).
- In-progress downloads stay impossible server-side (404 without mp4).
- Queue is in-memory; restarts drop queued/running (documented, matches today's job loss).
- XP Luna styling; Tahoma; no new dependencies.
- TDD per task; commit per task.

## Review Focus

- Double-submit of the same form → two independent jobs, both render. (Task 1 FIFO test submits back-to-back.)
- Delete of a queued job → it must never render afterward. (Task 1 test.)
- Server restart with queued jobs → queue gone, no crash on next submit. (Covered by fresh `queue.Queue` per `create_app`; no test needed beyond suite passing.)
- Explorer open across a done-graduation → row moves active→finished and gains download. (Task 4 browser check.)
- Error messages with HTML in them → active-row text set only via `textContent`, never `innerHTML` (enforced in Task 4 Step 3; pinned by the `"Queued #" in js` contract test). (Task 4.)

---

### Task 1: Backend FIFO queue + active-jobs endpoint

**Files:**
- Modify: `src/f1_reels/webapp.py:194-203` (queue + worker startup), `:439` (enqueue site), new `GET /api/jobs` next to `list_reels` (`:443`)
- Test: `tests/test_webapp.py` (append)

**Interfaces:**
- Consumes: existing `jobs: dict` (`webapp.py:198`), `jobs_root` (`:194`), nested `run_job` closure, `re` (already imported).
- Produces: `app.state.job_queue: queue.Queue`; `GET /api/jobs → {"jobs": [{job_id, name, status, progress, stage, queue_position}]}` where `queue_position` is 1-based rank among `queued` records ordered by enqueue sequence, else `null`.

- [ ] **Step 1: Write the failing tests**

```python
def test_queue_is_fifo_with_positions(tmp_path, monkeypatch):
    # gate release so job A stays running while B, C submit
    # POST A, B, C with brand/speed defaults; assert statuses
    # A == "running", B/C == "queued" with queue_position 1, 2
    # release; wait for done via GET /api/jobs/{id} polling (timeout 30 s)
    # assert completion order == [A, B, C]


def test_active_jobs_endpoint(tmp_path, monkeypatch):
    # gate one fake render; GET /api/jobs shows running record with
    # progress/stage/queue_position null and queued record position 1;
    # finished jobs are absent from /api/jobs but present in /api/reels


def test_delete_queued_job_never_renders(tmp_path, monkeypatch):
    # gate first job; submit second; DELETE second while queued;
    # release; assert second job_id never reaches "done" and polling
    # GET /api/jobs/{second} 404s
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q -k "fifo or active_jobs_endpoint or never_renders"`
Expected: FAIL (no `GET /api/jobs` route; jobs run immediately, not queued).

- [ ] **Step 3: Implement in `src/f1_reels/webapp.py`**

Add `import queue, threading` (top-level). In `create_app` after `app.state.settings` (`:201`): create `job_queue = queue.Queue()`, `enqueue_seq = itertools.count(1)` (add `import itertools` top-level), store both on `app.state`, start `threading.Thread(target=_drain, daemon=True)`. `_drain` (nested): `while True: fn = job_queue.get(); try: fn() finally: job_queue.task_done()`. In `create_job`: stamp `record["queue_seq"] = next(...)`; replace `background_tasks.add_task(run_job)` (`:439`) with `job_queue.put(run_job)` and drop the now-unused `background_tasks: BackgroundTasks` parameter. Worker skip rule: at the top of `run_job`, `if jobs.get(job_id) is None: return` (covers deleted-queued). New route `GET /api/jobs` returning non-`done` records with computed `queue_position` (rank among `status == "queued"` by `queue_seq`, else `null`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q`
Expected: new tests PASS; previously-passing job tests now FAIL on timing (fixed in Task 5).

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/webapp.py tests/test_webapp.py
git commit -m "feat: single-worker FIFO render queue with active-jobs endpoint"
```

### Task 2: Fix existing tests for async completion

**Files:**
- Modify: `tests/test_webapp.py` (every test that POSTs then immediately asserts `done`)

**Interfaces:**
- Consumes: Task 1 (`GET /api/jobs/{id}` status polling).
- Produces: green suite on queued semantics.

- [ ] **Step 1: Add a wait helper and convert assertions (tests are the deliverable; they fail first by definition)**

```python
def _wait_done(client, job_id, timeout=30):
    import time
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/api/jobs/{job_id}").json()
        if s["status"] in ("done", "error"):
            return s
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} not finished in {timeout}s")
```

Apply to: `test_create_job_and_download_with_fakes`, `test_delete_job_removes_files_and_record`, `test_endpoints_survive_restart_from_disk`, `test_api_reels_lists_done_job`, `test_finished_job_reports_progress_100`, `test_job_uses_configured_voice_direction`, `test_job_uses_default_voice_direction`, `test_brand_toggle_form_and_behavior`. Pattern: replace immediate `client.get(...).json()["status"] == "done"` checks with `_wait_done(...)`.

- [ ] **Step 2: Run the suite**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q`
Expected: PASS (all 25+).

- [ ] **Step 3: Commit**

```bash
git add tests/test_webapp.py
git commit -m "test: wait for queued renders instead of assuming sync completion"
```

### Task 3: Generator becomes Queue-and-reset

**Files:**
- Modify: `src/f1_reels/templates/index.html:69` (`>Render<` → `>Queue<`), `:72-75` (remove `#progress` + `.downloads`/`#download` markup), `src/f1_reels/static/app.js:26-101` (submit handler), `src/f1_reels/static/style.css` (remove `.xp-progress*`, `.downloads` rules)
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `POST /api/jobs` (unchanged contract).
- Produces: submit → 2xx → `form.reset()` + transient `status` "queued"; no `setInterval` poll, no progress/download elements.

- [ ] **Step 1: Write the failing tests**

```python
def test_generator_queue_resets_without_private_progress(tmp_path, monkeypatch):
    app, _ = _make_client(tmp_path, monkeypatch)
    client = TestClient(app)
    html = client.get("/").text
    assert ">Queue<" in html and ">Render<" not in html
    assert 'id="progress"' not in html and 'id="download"' not in html
    js = client.get("/static/app.js").text
    assert "setInterval" not in js
```

Update (not delete) existing assertions that now contradict: `test_index_form_new_contract` (`id="download"`, `>Download</a>`), `test_index_polished_structure` (progress block), `test_desktop_chrome` (download/progress/`job.progress` js asserts), `test_progress_markup_and_assets` (delete test; Explorer progress covered in Task 4).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q -k "queue_resets or polished or desktop_chrome or progress_markup or new_contract"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`index.html`: button text; delete progress + downloads markup. `app.js`: submit handler keeps validation-error path, on 2xx does `form.reset()`, `setStatus("queued: " + jobId, "queued")`, re-enable button, return. Delete poll block, progress/download element lookups. `style.css`: delete `.xp-progress`, `.xp-progress-fill`, `.downloads` rules.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/templates/index.html src/f1_reels/static/app.js src/f1_reels/static/style.css tests/test_webapp.py
git commit -m "feat: generator queues renders and resets, no private progress"
```

### Task 4: Explorer shows live queue

**Files:**
- Modify: `src/f1_reels/static/app.js` (`loadReels`, row builders, poll loop), `src/f1_reels/static/style.css` (`.reel-active`, `.reel-progress` mini bar)
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `GET /api/jobs` (Task 1), `GET /api/reels`, `DELETE /api/jobs/{id}` (unchanged).
- Produces: active rows (queued/running/error) above finished rows; running rows carry `.reel-progress` bar; no enabled download until `done`; 2 s poll only while Explorer visible.

- [ ] **Step 1: Write the failing tests**

```python
def test_explorer_contract_covers_active_rows(tmp_path, monkeypatch):
    # markup/js contract only (rendering verified in browser):
    js = client.get("/static/app.js").text
    assert "/api/jobs" in js and "reel-progress" in js
    assert "Queued #" in js
    css = client.get("/static/style.css").text
    assert ".reel-progress" in css
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q -k active_rows`
Expected: FAIL.

- [ ] **Step 3: Implement in `app.js`/`style.css`**

`loadReels`: fetch `/api/jobs` (tolerate failure → `[]`); render active rows first into a `.reel-active` container: name + status line (`Rendering… 42%` / `Queued #1` / error text, all set via `textContent`, never `innerHTML`), mini bar `<span class="reel-progress"><span style="width:…">`, Delete button (reuse handler), download link only when `status === "done"` (defensive; normally graduated already). Graduated jobs appear via `/api/reels` on the same poll. Polling: `setInterval(loadReels, 2000)` started in `showWindow("win-explorer")`, cleared when any other window shows or on logoff; manual Refresh still calls `loadReels`. CSS: `.reel-active` row variant + `.reel-progress` sunken track reusing XP bar look.

- [ ] **Step 4: Run tests, then verify in the browser**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q` (PASS), then: start dev server, submit two reels via the generator, open Explorer, screenshot active rows (queued + running visible, no download on unfinished), confirm a row graduates to downloadable. Fix discrepancies.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/static/app.js src/f1_reels/static/style.css tests/test_webapp.py
git commit -m "feat: explorer shows live queue with progress and gated downloads"
```

### Task 5: Full regression + docs touch-up

**Files:**
- Modify: `tests/test_webapp.py` only if fallout remains; `README.md` if it documents the render flow (check first, smallest edit that stays true)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: green suite + committed branch.

- [ ] **Step 1: Run the full suite**

Run: `.venv311/bin/python -m pytest tests/ -q`
Expected: all PASS except the known pre-existing `test_docker` port-mapping failure (untouched `docker-compose.yml`).

- [ ] **Step 2: Commit any fallout fixes**

```bash
git add -A  # review `git status` first; never commit .env/docker-compose.yml dirt or local artifacts (.venv*, uv.lock, egg-info)
git commit -m "test: <what broke>"
```
