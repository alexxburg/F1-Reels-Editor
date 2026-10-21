# F1 Reels Sole-src Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `src/f1_reels/` the sole implementation with zero `import Editvideos` and delete legacy scripts.

**Architecture:** Rewire `cli._cmd_edit` to `Settings` + `script_parser` + `alignment.generate_voiceover` + `subtitles` helpers; deduplicate SRT/crop paths; add missing unit tests with fakes/mocks; fix packaging drift then `git rm` legacy files.

**Tech Stack:** Python >=3.10, moviepy 1.0.3, imageio-ffmpeg, faster-whisper (optional), requests, pytest

**Spec:** N/A — legacy behavior defined by `Editvideos.py:150-327,359-691,692-944,945-1464` + `Postprocess_bricks.py:73-154` + session audits (2026-10-21). Plan argues from that behavior.

## Global Constraints

- Python requires-python >=3.10.
- OpenRouter-only: no `edge_tts`, `EdgeTTS`, `EDGE_VOICE`, `TTS_BACKEND`, `sample-voices` tokens in `src/`, `pyproject.toml`, `requirements.txt`, `.env.example`.
- English identifiers/docstrings/messages only; `pathlib.Path` for paths; `logging` not `print`.
- No `import Editvideos` anywhere in `src/` after cutover.
- TDD: failing test first, watch it fail for expected reason, minimal fix, full `PYTHONPATH=src python3 -m pytest tests/ -v` green.

## Review Focus

- Empty/missing `textos.txt` block should skip with warning, not crash — needs missing-file/empty-script test.
- Corrupt/too-short brick video should be skipped, not abort whole run — needs probe-failure test.
- Missing `OPENROUTER_API_KEY` should raise clear RuntimeError before ffmpeg — needs missing-key test.
- Odd-height video (e.g. 1440x2560) must keep even crop dimensions — needs odd-size crop test.
- `--overwrite` vs skip-existing must not re-encode unnecessarily — needs skip-existing test.

---

### Task 1: Rewire CLI off legacy

**Files:**
- Modify: `src/f1_reels/cli.py`
- Modify: `src/f1_reels/config.py` (add `find_first_font()` helper)
- Test: `tests/test_cli.py`, `tests/test_no_edge_tts.py`

**Interfaces:**
- Consumes: `Settings.from_env() -> Settings`, `parse_script_file(Path) -> dict[str,ScriptBlock]`, `generate_voiceover(text,audio_path,voice,instructions,speed,subtitle_lead,apply_punch,use_whisper) -> Voiceover`, `group_words_into_lines()`, `render_line_clips()`
- Produces: `_cmd_edit(args) -> int` with zero `legacy.` refs; `find_first_font(fonts: tuple[str,...]) -> Path`

- [ ] **Step 1: Write failing test** `test_cmd_edit_uses_no_legacy` asserting `grep -r "import Editvideos\|legacy\." src/f1_reels/cli.py` empty + `build_parser` has no `--backend`/`sample-voices` + `find_first_font` returns existing path.
- [ ] **Step 2: Run test to verify it fails** Run: `PYTHONPATH=src python3 -m pytest tests/test_cli.py::test_cmd_edit_uses_no_legacy -v` Expected: FAIL (legacy bridge still present).
- [ ] **Step 3: Implement** rewrite `_cmd_edit` to use `Settings`, `parse_script_file`, `generate_voiceover` adapter to `TtsCallable`, `subtitles` factories; add `find_first_font()` in `config.py`; delete `import Editvideos`, `os.environ TTS_BACKEND`, `_sample_all`, `_cmd_sample_voices`.
- [ ] **Step 4: Run test to verify it passes** Run: `PYTHONPATH=src python3 -m pytest tests/test_cli.py tests/test_no_edge_tts.py -v` Expected: PASS.
- [ ] **Step 5: Commit** `git add src/f1_reels/cli.py src/f1_reels/config.py tests/test_cli.py && git commit -m "feat: rewire CLI off legacy Editvideos"`

### Task 2: Deduplicate pipeline paths + packaging fix

**Files:**
- Modify: `src/f1_reels/pipeline.py` (use `subtitles.write_srt`, fix `[bracket]` cursor bug)
- Modify: `src/f1_reels/cli.py` (`_process_one` uses `crop.compute_crop_window`)
- Modify: `src/f1_reels/__init__.py` (export `Settings`, `parse_script_file`, `ScriptBlock`, `generate_voiceover`)
- Modify: `pyproject.toml`, `README.md`
- Test: `tests/test_pipeline.py` (new, fakes only)

**Interfaces:**
- Consumes: `crop.compute_crop_window(w,h,pos) -> CropBox`, `subtitles.write_srt(entries,path) -> Path`
- Produces: Single `write_srt` path used by pipeline; `_process_one` delegates to `crop` module.

- [ ] **Step 1: Write failing test** `test_pipeline_uses_single_srt_writer` + `test_bracket_lines_do_not_shift_cursor` with fake `synthesize_speech`/`subtitle_overlays`.
- [ ] **Step 2: Run test to verify it fails** Run: `PYTHONPATH=src python3 -m pytest tests/test_pipeline.py -v` Expected: FAIL.
- [ ] **Step 3: Implement** delete `pipeline.format_srt_timestamp/write_srt` dup (import from `subtitles`), fix bracket `cursor` advance, wire `_process_one` to `crop` module, add `faster-whisper` optional + `pytest` test extra + `testpaths` in `pyproject.toml`, fix `README.md` install cmd.
- [ ] **Step 4: Run test to verify it passes** Run: `PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_cli.py -v` Expected: PASS.
- [ ] **Step 5: Commit** `git add src/f1_reels/ pyproject.toml README.md tests/test_pipeline.py && git commit -m "fix: dedupe SRT/crop paths and packaging"`

### Task 3: Missing unit coverage

**Files:**
- Create: `tests/test_config.py`, `tests/test_tts.py`, `tests/test_broll.py`, `tests/test_endcard.py`
- Test: same files

**Interfaces:**
- Consumes: `Settings.from_env`, `OpenRouterTTS.synthesize` (mocked `requests.post`), `BrollSelector` (stubbed `probe_duration`), `build_endcard` (`pytest.importorskip("moviepy")`)
- Produces: Green coverage for config/tts/broll/endcard edge cases.

- [ ] **Step 1: Write failing tests** covering: `from_env` defaults/overrides/invalid bool, PCM→WAV + 400-retry + missing-key, broll empty-dir + seed determinism, endcard disabled/missing-logo → None.
- [ ] **Step 2: Run tests to verify they fail** Run: `PYTHONPATH=src python3 -m pytest tests/test_config.py tests/test_tts.py tests/test_broll.py tests/test_endcard.py -v` Expected: FAIL (files missing).
- [ ] **Step 3: Implement tests only** (production code already exists; add `BrollConfig` validation if missing).
- [ ] **Step 4: Run tests to verify they pass** Run: `PYTHONPATH=src python3 -m pytest tests/ -v` Expected: PASS (50+ new tests, 0 failures; 2 pre-existing moviepy skips allowed).
- [ ] **Step 5: Commit** `git add tests/ src/f1_reels/broll.py && git commit -m "test: cover config/tts/broll/endcard"`

### Task 4: Retire legacy + final verify

**Files:**
- Delete: `Editvideos.py`, `Postprocess_bricks.py` via `git rm` (resolve existing `D Voices.py`)
- Modify: `README.md`, `src/f1_reels/__init__.py` docstrings (scrub legacy refs)
- Test: `tests/test_no_edge_tts.py` (extend to ban `import Editvideos`)

**Interfaces:**
- Consumes: All prior tasks green
- Produces: Repo with sole `src/f1_reels/` implementation; `README` says sole implementation.

- [ ] **Step 1: Write failing test** assert `grep -r "import Editvideos\|Editvideos.py\|Postprocess_bricks" src/ README.md` empty.
- [ ] **Step 2: Run test to verify it fails** Run: `PYTHONPATH=src python3 -m pytest tests/test_no_edge_tts.py -v` Expected: FAIL (legacy refs in docstrings).
- [ ] **Step 3: Implement** `git rm Editvideos.py Postprocess_bricks.py Voices.py`, scrub docstrings, update `README.md` to sole-src usage (`f1-reels edit`, `f1-reels postprocess-bricks`).
- [ ] **Step 4: Run full suite to verify it passes** Run: `PYTHONPATH=src python3 -m pytest tests/ -v` Expected: PASS, `git status --short` shows `D Editvideos.py D Postprocess_bricks.py D Voices.py`.
- [ ] **Step 5: Commit** `git add -A && git commit -m "chore: retire legacy scripts, src is sole implementation"`
