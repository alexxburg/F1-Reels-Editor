# F1 Reels Editor (tidy refactor)

New tidy package lives in `src/f1_reels/`. Legacy scripts
(`Editvideos.py`, `Postprocess_bricks.py`, `Voices.py`) are untouched
until the refactor is complete.

## Setup

```bash
cp .env.example .env
pip install -e ".[test]"
```

## Usage

```python
from pathlib import Path
from f1_reels import Settings, parse_script_file

settings = Settings.from_env()
blocks = parse_script_file(settings.script_file)
for name, block in blocks.items():
    if block.process and block.lines:
        print(name, block.lines, block.voice_direction)
```

## Tests

```bash
python -m pytest
```
