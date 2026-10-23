# Background Render Queue — Design

Date: 2026-10-23 | Status: awaiting review | Approach: A (in-process FIFO worker)

## 1. Background and intent

Rendering a reel currently locks the generator window: submit disables the
form and polls that one job, with a private progress bar and download link.
The backend already renders off-request (`BackgroundTasks`); only the
frontend serializes the user onto one job.

Intent: submitting must never block the generator. Queueing resets the form
for the next reel; rendering happens on a background FIFO queue; the Windows
Explorer shows in-progress reels with live progress and withholds downloads
until finished. Success = render-while-browsing with no stuck UI.

## 2. Goals / non-goals

Goals:

- Single-worker FIFO: one render at a time, visible queue positions.
- Generator resets to a clean form on submit; no per-job polling, progress
  bar, or download link there. Explorer is the single place for progress
  and downloads.
- In-progress rows are never downloadable; failed rows show their error
  with Delete (retry = manual resubmit).

Non-goals:

- Queue durability across restarts (in-memory, like today's job records).
- Auto-retry of failed jobs.
- Parallel renders or worker pools.

## 3. Architecture

One dedicated worker thread drains an in-process FIFO (`queue.Queue`).
`POST /api/jobs` validates input, creates the job record, enqueues it, and
returns immediately. The worker runs the existing `run_job` body unchanged
per job, flipping `status` queued → running → done/error. Polling endpoints
are unchanged in shape; a new list endpoint exposes active jobs.

```
generator --POST /api/jobs--> [FIFO queue] --> worker thread --> run_job
explorer  --GET /api/jobs---> active rows (queued/running/error)
explorer  --GET /api/reels--> finished rows (unchanged)
```

Concurrency: exactly one `run_job` at a time. Submissions during a render
wait with a visible position. No locks leak into request handlers; the only
shared state is the queue plus the existing `jobs` dict.

## 4. Components

### 4.1 Backend queue (`webapp.py`)

- Job records gain `queue_position` (1-based among queued/running).
- `POST /api/jobs`: same validation as today (400s unchanged), then
  `status="queued"`, enqueue, return `{"job_id"}` immediately.
- Worker thread (daemon, started at app creation): `queue.get()` loop,
  sets `running`, executes current `run_job` body, sets `done`/`error`.
- New `GET /api/jobs`: returns non-done in-memory records
  (`queued`/`running`/`error`) as
  `{"jobs": [{job_id, name, status, progress, stage, queue_position}]}`.
- `GET /api/reels` unchanged (finished mp4s only).
- Downloads: `/api/jobs/{id}/download` already 404s without an mp4; no
  change, covered by a regression test.
- Restart semantics: queued/running records vanish (documented; matches
  today's in-memory job loss). Orphan job dirs are untouched.

### 4.2 Generator window (`index.html`, `app.js`, `style.css`)

- Submit button label Render → Queue.
- On 2xx: reset form fields to defaults, flash transient "queued" status,
  re-enable immediately. No `setInterval` polling, no `#progress` bar, no
  `#download` link wiring (markup and CSS hooks removed; existing tests
  asserting on them updated).
- Validation errors still surface inline in the generator status line.

### 4.3 Explorer window (`app.js`, `style.css`)

- `loadReels` fetches `/api/jobs` alongside `/api/reels`; active rows
  render above finished ones: name + status text, inline mini progress
  bar while running, `Queued #N` label while waiting, error text when
  failed.
- Download control omitted/disabled until `done`; Delete works on every
  row via the existing endpoint.
- Polls every ~2 s while the Explorer is visible; stops when hidden.
  Refresh button behavior unchanged.

## 5. Data flow

Submit: `FormData → POST /api/jobs → {job_id}` → form resets.
Track: Explorer polls `GET /api/jobs` (active) + `GET /api/reels`
(finished) → rows keyed by `job_id`; a job graduating done moves from
the active list to the finished list on the next poll, gaining its
download button. Download gating is server-side (404 without mp4), so a
stale client can never fetch an unfinished file.

## 6. Error handling

- Submit validation failures: 400s as today, shown in generator status.
- Render failures: `status=error` with message; row persists with Delete.
- Worker exceptions: caught per job (record `error`, continue draining).
- Poll failures in Explorer: rows go stale but persist; next successful
  poll reconciles by `job_id`.

## 7. Testing

- Unit: FIFO order with stubbed `edit_video` (submit A, B, C → run order
  A, B, C; positions 1, 2, 3; statuses queued → running → done).
- API: `/api/jobs` shape and positions; in-progress download → 404;
  error record shape; unknown job → 404 unchanged.
- Frontend contract: `Queue` label present; no generator polling code;
  explorer renders active rows with progress and gated downloads.
- Regression: full `pytest` suite green (updating generator
  progress/download markup assertions).

## 8. Rollout

Single deploy, no migration: queue starts empty; in-flight renders from
before the deploy follow the old path to completion. No config changes.
