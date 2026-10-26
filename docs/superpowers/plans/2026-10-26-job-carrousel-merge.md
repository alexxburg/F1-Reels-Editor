# Job Carrousel Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the Flask Job Carrousel app into this repo as a third XP window backed by a native FastAPI router, with full feature parity.

**Architecture:** New `src/f1_reels/carrousel/` package (`db.py` + `render.py` verbatim logic, `router.py` as a FastAPI `APIRouter(prefix="/api/carrousel")`); XP shell extended with `win-carrousel`; no Flask dependency added.

**Tech Stack:** FastAPI (existing), `psycopg2-binary` (new), Pillow (existing), vanilla JS, pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-10-26-job-carrousel-merge-design.md`

## Global Constraints

- No Flask or gunicorn dependency, ever.
- Secrets only from env; never `config.json` (existing secret test enforces this).
- No `GET /api/jobs`-style unprefixed carrousel routes — everything under `/api/carrousel/*` (name collision with reel jobs).
- XP Luna styling; Tahoma for UI, Century Gothic stays inside PNG renders only.
- No real AWS credentials or cluster access in any test or check; stub at the `query_db` boundary.
- TDD per task; commit per task.

## Review Focus

- Search/filter values reach SQL only as `%s` params, never interpolated — a `Robert'; DROP TABLE` search must return zero rows, not an error. (Task 3 test.)
- Missing AWS creds yield the guidance message, never a traceback or env dump. (Task 3 test.)
- `POST /api/carrousel/image` with 0, 25, non-integer, or boolean ids → 400 in every case. (Task 3 test.)
- No-creds browser state shows the guidance text, not an empty table. (Task 5 browser check.)
- Reel endpoints untouched: `GET /api/jobs/{job_id}` and `GET /api/reels` behave exactly as before (existing suite covers; re-run in Task 5).

---

### Task 1: DB layer (`db.py`)

**Files:**
- Create: `src/f1_reels/carrousel/__init__.py`, `src/f1_reels/carrousel/db.py`
- Test: `tests/test_carrousel.py` (new; stub `psycopg2` in `sys.modules` — established pattern in `tests/test_pipeline.py`)

**Interfaces:**
- Consumes: env (`DSQL_HOST`, `AWS_REGION`, `DSQL_USER`, `DBNAME`) with spec §4 defaults; `aws` CLI on PATH at runtime (not in tests).
- Produces: `get_token() -> str` (14-min cache); `query_db(sql, params=None) -> list[tuple]` (one auth retry, then raise); `TokenError`; `is_auth_error(exc) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_token_cached_within_ttl(monkeypatch): ...
  # stub subprocess.run to count calls; two get_token() calls -> one subprocess call

def test_token_refreshes_after_ttl(monkeypatch): ...
  # backdate cache privately or monkeypatch time; second call re-invokes CLI

def test_query_retries_once_on_auth_error(monkeypatch): ...
  # stub psycopg2 module: first connect raises OperationalError("...expired token..."), second succeeds; assert rows returned and connect called twice

def test_query_raises_token_error_without_aws_cli(monkeypatch): ...
  # subprocess.run raises FileNotFoundError -> TokenError

def test_is_auth_error_matches_only_auth_failures(): ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'f1_reels.carrousel'`.

- [ ] **Step 3: Implement `db.py`** — port token cache, `get_token` (awscli subprocess, 30 s timeout), `query_db` with single auth retry, same error semantics as the Flask original.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/carrousel/ tests/test_carrousel.py
git commit -m "feat: carrousel DSQL layer with cached IAM auth"
```

### Task 2: Render layer + assets

**Files:**
- Create: `src/f1_reels/carrousel/render.py`
- Copy (binary): `~/job-carrousel/LinkedIn.png` → `src/f1_reels/static/carrousel-template.png`; `~/job-carrousel/fonts/` → `src/f1_reels/static/fonts/` (covered by existing `static/*` package-data; verify with `git check-ignore` that neither path is ignored)
- Test: `tests/test_carrousel.py` (append)

**Interfaces:**
- Consumes: template PNG path, `static/fonts/CenturyGothic.ttc` (+ DejaVu fallback chain, unchanged).
- Produces: `render_single(row: tuple) -> PIL.Image` (1500x1500 RGB); `TEAM_DISPLAY: dict`.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_produces_1500x1500_png():
  img = render_single((1, "SENIOR AERODYNAMICIST", "red_bull_racing", None, "Full-time", "Milton Keynes", "https://x"))
  assert img.size == (1500, 1500) and img.mode == "RGB"
  buf = io.BytesIO(); img.save(buf, format="PNG")
  assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"

def test_team_display_fallback():
  # unknown team code renders title-cased with underscores as spaces (assert via TEAM_DISPLAY.get fallback path on a crafted row; exact pixels not asserted)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py -q -k "render or team_display"`
Expected: FAIL with `ModuleNotFoundError` / missing `render_single`.

- [ ] **Step 3: Implement `render.py`** — port `TEAM_DISPLAY`, font loaders (template path now `static/carrousel-template.png`), `_draw_centered_text`, `render_single` unchanged in math.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/carrousel/render.py src/f1_reels/static/carrousel-template.png src/f1_reels/static/fonts/ tests/test_carrousel.py
git commit -m "feat: carrousel PNG renderer and template assets"
```

### Task 3: API router + registration

**Files:**
- Create: `src/f1_reels/carrousel/router.py`
- Modify: `src/f1_reels/webapp.py` (import router near line 29–36; `app.include_router(...)` before `return app` at line 668)
- Test: `tests/test_carrousel.py` (append)

**Interfaces:**
- Consumes: `db.query_db` (monkeypatch point: `f1_reels.carrousel.router.query_db`), `render.render_single`.
- Produces: routes `GET /api/carrousel/jobs`, `GET /api/carrousel/filters`, `POST /api/carrousel/image`, `GET /api/carrousel/image/{id}`, `GET /api/carrousel/images.zip` with spec §3 shapes and status codes.

- [ ] **Step 1: Write the failing tests**

```python
def test_jobs_filters_pass_params_not_sql(...):  # search "%x%" appears in params, "ILIKE" in sql; capture query_db args
def test_image_rejects_bad_ids(...):  # parametrize: [] / 25 ids / ["a"] / [true] -> 400
def test_image_404_and_zip_order(...):  # empty rows -> 404; zip contains "<id>.png" in request order with PNG magic
def test_cred_failure_shape(...):  # query_db raises TokenError("nope") -> 500 {"error": ...guidance with AWS_ACCESS_KEY_ID...}, and reel GET /api/jobs still fine (existing tests cover)
def test_sql_injection_search_returns_rows(...):  # search "x' OR '1'='1" hits stub, returns stub rows, no exception (params, not interpolation — assert sql has exactly one ILIKE clause set and params carry the raw string)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py -q -k "jobs or image or cred or injection"`
Expected: FAIL (no router / 404s).

- [ ] **Step 3: Implement `router.py` + register it** — port the five endpoints with identical validation, shapes, and status codes; reuse `render_single`; map `TokenError`/credential failures to the guidance 500.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_carrousel.py tests/test_webapp.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/carrousel/router.py src/f1_reels/webapp.py tests/test_carrousel.py
git commit -m "feat: carrousel FastAPI router under /api/carrousel"
```

### Task 4: XP window frontend

**Files:**
- Modify: `src/f1_reels/templates/index.html` (new `win-carrousel` hidden window after `win-explorer` ~line 94; taskbar button after line 134; start-menu app row after line 119), `src/f1_reels/static/app.js` (`showWindow` list line 447 + logoff list line 469 gain `"win-carrousel"`; add `loadCarrousel`), `src/f1_reels/static/style.css` (carrousel block)
- Test: `tests/test_webapp.py` (update svg counts: taskbar `>= 1` → `>= 2`; menu `>= 2` → `>= 3`; assert `id="win-carrousel" hidden` and `data-win="win-carrousel"`)

**Interfaces:**
- Consumes: `/api/carrousel/*` (Task 3).
- Produces: filter bar + results table + PNG preview + zip download in XP styling; `loadCarrousel()` on window open + manual Refresh (no interval polling — static job list).

- [ ] **Step 1: Write the failing tests** — contract test asserting hidden window, taskbar/start `data-win="win-carrousel"` entries, updated svg counts, plus a JS-content assert that `loadCarrousel` fetches `/api/carrousel/filters` and `/api/carrousel/jobs`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py -q -k "carrousel or desktop_chrome"`
Expected: FAIL.

- [ ] **Step 3: Implement** — XP window markup (filter selects populated from filters endpoint, search box, results table with checkboxes 1–24, results pane with search/results tabs like the original, Refresh button), `loadCarrousel` + select/download wiring mirroring the Flask UI behavior, XP CSS block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv311/bin/python -m pytest tests/test_webapp.py tests/test_carrousel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/f1_reels/templates/index.html src/f1_reels/static/app.js src/f1_reels/static/style.css tests/test_webapp.py
git commit -m "feat: carrousel XP window with browse-select-render flow"
```

### Task 5: Deps, docs, full verification

**Files:**
- Modify: `pyproject.toml` (`dependencies` += `"psycopg2-binary"`), `Dockerfile` (apt line += `awscli`), `.env.example` (commented `AWS_ACCESS_KEY_ID=` / `AWS_SECRET_ACCESS_KEY=` + `DSQL_HOST/AWS_REGION/DSQL_USER/DBNAME` defaults as comments), `README.md` (short carrousel section: what it needs, where it lives in the UI)
- Test: none new (contract: full suite)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: buildable image, documented setup, green suite.

- [ ] **Step 1: Write the failing test** — extend `tests/test_docker.py::test_docker_files_publish_lan_port_with_ffmpeg` (or a sibling test) to assert `awscli` in Dockerfile and `psycopg2` in dependencies.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv311/bin/python -m pytest tests/test_docker.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** the dep/docker/env-doc/README changes.

- [ ] **Step 4: Run the full suite + browser check**

Run: `.venv311/bin/python -m pytest tests/ -q`
Expected: all PASS. Then: serve locally, open the carrousel window with no AWS creds configured, confirm the guidance error surfaces (no traceback), confirm filters/table render once stubbed responses are returned (stub at the network layer in-browser only if needed; never with real creds).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Dockerfile .env.example README.md tests/test_docker.py
git commit -m "feat: carrousel runtime deps, AWS env docs, setup guide"
```
