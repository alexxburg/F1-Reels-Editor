# Job Carrousel Merge — Design

Date: 2026-10-26 | Status: awaiting review | Approach: A (native FastAPI port)

## 1. Background and intent

`~/job-carrousel` is a standalone Flask app: it lists live jobs from an AWS
DSQL cluster (IAM auth via AWS CLI + `psycopg2`), filters/selects them in a
table UI, and renders selected jobs as 1500x1500 PNGs on a LinkedIn template
(single PNG per job plus a zip bundle).

Intent: merge it into this repo as a third XP desktop window ("Job
Carrousel"), same shell contract as Generator and Explorer — one visible
window at a time, taskbar button, start-menu entry — served by the single
FastAPI process on the single existing port.

## 2. Goals / non-goals

Goals:

- Single process, single port, single container. Flask/gunicorn do not
  come over; routes are rewritten as FastAPI.
- Full feature parity: search + team/location/type filters, checkbox
  select (1–24), per-job PNG render, zip download, error surfaces.
- XP look and shell behavior identical in kind to the existing windows.
- Secrets strictly from environment, never `config.json` (repo rule,
  enforced by the existing unknown-key/secret tests).
- Testable without AWS access (DB layer is a stubbed boundary).

Non-goals:

- No change to reel rendering, branding, queue, or existing API shapes.
- No queueing of PNG renders (they are synchronous request/response,
  as today; renders are fast Pillow work).
- No persistence of carrousel selections server-side.

## 3. Architecture

New `src/f1_reels/carrousel/` package (no Flask import anywhere):

- `db.py` — IAM token cache + `query_db(sql, params)` with one retry on
  auth errors. Logic moves verbatim; `psycopg2` import stays lazy.
- `render.py` — `TEAM_DISPLAY`, font loaders, `_draw_centered_text`,
  `render_single(row)` returning a Pillow image. Math unchanged.
- `router.py` — FastAPI `APIRouter(prefix="/api/carrousel")` with:
  - `GET /jobs?search=&team=&location=&type=` → `[{job_id, title, team,
    subteam, type, location, link}]` (500 max, `last_seen` DESC).
  - `GET /filters` → `{teams[], locations[], types[]}`.
  - `POST /image` `{ids: [int, 1..24]}` → `{images: [{job_id, url}]}`,
    400 on bad ids, 404 when no live rows.
  - `GET /image/{job_id}` → `image/png` (1500x1500).
  - `GET /images.zip?ids=1,2,3` → `carrousel.zip` (1–24 ids).
- Registered on the main app in `webapp.py` (`app.include_router`).

Namespace note: this repo already owns `GET /api/jobs` (reel jobs), so
every carrousel route lives under `/api/carrousel/*`. The old standalone
paths (`/api/jobs`, `/api/filters`, `/api/image`, `/api/images.zip`)
are NOT preserved.

## 4. Secrets and configuration

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (plus optional
  `AWS_SESSION_TOKEN`) from the environment only.
- `DSQL_HOST` (default `fbt7qrxfs2egnxikn4bqy3mbhq.dsql.eu-north-1.on.aws`),
  `AWS_REGION` (default `eu-north-1`), `DSQL_USER` (default `admin`),
  `DBNAME` (default `postgres`) — env with the current hardcoded values
  as defaults, matching current behavior.
- Documented in `.env.example` and README. No new `config.json` keys.
- Missing/invalid credentials surface as HTTP 500 with the current
  guidance message (unchanged semantics).

## 5. Assets

- `LinkedIn.png` → `src/f1_reels/static/carrousel-template.png`.
- `fonts/` (Century Gothic) → `src/f1_reels/static/fonts/`.
  Existing `static/*` package-data glob already covers both; reel fonts
  untouched. XP UI keeps Tahoma; carrousel PNGs keep Century Gothic.
- Linux runtime keeps the DejaVu fallback chain already in the code.

## 6. XP shell and frontend

- New `win-carrousel` window in `index.html` following the existing
  window/title-bar/body pattern; `data-win="win-carrousel"` taskbar
  button; start-menu app row (icon + one-line description).
- `showWindow`/`syncPressed`/logoff already handle N windows; no shell
  logic changes expected beyond adding the window to the hide-all lists
  (verify by reading, not assuming).
- Table UI ported from the Flask template and restyled to XP (inset
  list, silver header, outset buttons). Same behavior: filter dropdowns
  populated from `/api/carrousel/filters`, checkbox selection (1–24,
  persisted client-side across reloads as today), PNG results tab,
  zip download via blob URL.
- Single-visible-window contract unchanged; only one window shows at a
  time (existing tests assert exact visibility, update counts only).

## 7. Data flow

Browse: `GET /api/carrousel/filters` + `GET /api/carrousel/jobs?...`
→ table rows. Select: checkbox set in page state. Render:
`POST /api/carrousel/image {ids}` → `{images: [{job_id, url}]}` where
`url` points at `GET /api/carrousel/image/{id}`; zip via
`GET /api/carrousel/images.zip?ids=...` downloaded as `carrousel.zip`.
Reel endpoints and job records are untouched; the two "job" concepts
share nothing but English.

## 8. Error handling

- 400 on malformed ids (non-integer list, empty, >24), matching current
  validation exactly.
- 404 when no live rows match.
- 500 with credential guidance on missing/invalid AWS creds, and
  `database error: ...` otherwise (current contract preserved).
- Frontend: failed fetch keeps existing rows (stale-but-visible rule
  already established for the Explorer); render/zip failures surface
  via the page's existing alert pattern.

## 9. Testing

- New `tests/test_carrousel.py` with the DB boundary stubbed
  (monkeypatch `query_db`): filter params build the right SQL/params,
  id validation rejects bad input, empty DB → 404, credential failure
  → 500 with guidance, PNG bytes start with the PNG magic and are
  1500x1500, zip contains one PNG per id in request order.
- Render tests use the bundled template + fonts (no AWS, no network).
- Existing suite: update only icon/menu-count assertions that enumerate
  taskbar and start-menu entries; no other changes.
- Browser verification: filters populate, select → preview renders,
  zip downloads — all against stubbed DB responses; no test or check
  may require real AWS credentials or network access to the cluster.

## 10. Docker and dependencies

- `requirements.txt`/`pyproject.toml` gain `psycopg2-binary`. Pillow
  already present. Flask and gunicorn are not added.
- `Dockerfile` gains `awscli` (same apt pattern as the carrousel
  Dockerfile). Single service, single port unchanged.
- Compose keeps one service; AWS keys arrive via the existing env-file
  mechanism.

## 11. Rollout

Single merge, no migration. The standalone Flask service is superseded;
its repo stays untouched (no changes there). Rollback = revert this
merge; reel functionality is unaffected either way (separate router,
separate static assets, no shared code paths beyond the XP shell lists).
