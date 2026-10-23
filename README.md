# F1 Reels Editor

Sole implementation lives in `src/f1_reels/` (installed as the `f1-reels` console script).

## Setup

```bash
cp .env.example .env
pip install -e ".[test]"
```

Set `OPENROUTER_API_KEY` in `.env` for voiceover synthesis.

## Usage

### Edit reels

```bash
f1-reels edit textos.txt --output-dir Videos_Editados
```

Parses a script file (`Video_1 | process: Y` headers or a plain single
script), synthesizes the voiceover, assembles random B-roll, burns in
word-highlight subtitles, and writes `<name>.mp4` (+ optional `.srt`).

Options: `--bricks-dir`, `--font`, `--margin`, `--no-endcard`, `--seed`.

```python
from pathlib import Path
from f1_reels import Settings, parse_script_file

settings = Settings.from_env()
blocks = parse_script_file(Path("textos.txt"))
for name, block in blocks.items():
    if block.process and block.lines:
        print(name, block.lines, block.voice_direction)
```

### Post-process bricks

```bash
f1-reels postprocess-bricks --input "Video Bricks" --output "Post Processed Videos"
```

Crops the watermark band and trims leading seconds per take.
Use `--overwrite` to re-encode existing outputs, `--dry-run` to preview.

### Docker LAN webapp

Requires Docker 29+ with Compose v5.

```bash
cp config.json.example config.json
cp .env.example .env   # then set OPENROUTER_API_KEY in .env
docker compose up --build
```

Open `http://<lan-ip>:8082` from any device on your LAN
(use `http://localhost:8082` on the host).

1. Fill the form: reel name, script lines, voice direction, speed,
   margin, and seed. (The API key comes only from `.env`; bricks,
   voice/model, the endcard logo, and the subtitle font come only
   from `config.json`.)
2. Queue the render with Queue; the form resets for the next reel
   while it renders in the background (one at a time, FIFO).
3. Watch live progress in Windows Explorer — My Reels; download
   `<name>.mp4` and `<name>.srt` from finished rows (in-progress
   rows are not downloadable).

Job data persists in `./data` (mounted as `/app/data`; override with `DATA_ROOT`).
`./config.json` is mounted read-only as `/app/config.json`
(override with `CONFIG_PATH`). Bricks are served from the configured
`bricks_dir` on the server, not uploaded per job.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
```

## Changelog

- 2026-10-21: retired previous single-file scripts; `src/` is now the sole implementation.
