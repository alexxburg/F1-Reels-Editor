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

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
```

## Changelog

- 2026-10-21: retired previous single-file scripts; `src/` is now the sole implementation.
