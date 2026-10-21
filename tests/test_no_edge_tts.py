"""Assert every TTS backend other than OpenRouter is gone (no edge-tts)."""

import inspect
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "f1_reels"

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"

BANNED_TOKENS = (
    "edge_tts",
    "EdgeTTS",
    "EDGE_VOICE",
    "TTS_BACKEND",
    "sample-voices",
    "sample_voices",
)

LEGACY_TOKENS = (
    "import Editvideos",
    "Editvideos.py",
    "Postprocess_bricks",
)


def _source_files() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if p.is_file())


def test_no_banned_edge_tokens_in_src() -> None:
    violations: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for token in BANNED_TOKENS:
            if token in text:
                violations.append(f"{path.name} still contains {token!r}")
    assert not violations, "; ".join(violations)


def test_generate_voiceover_has_no_backend_param() -> None:
    from f1_reels.alignment import generate_voiceover

    params = inspect.signature(generate_voiceover).parameters
    assert "backend" not in params


def test_cli_parser_has_no_sample_voices_or_backend_flag() -> None:
    from f1_reels.cli import build_parser

    parser = build_parser()
    sub_action = next(
        a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
    )
    assert "sample-voices" not in sub_action.choices
    assert "sample_voices" not in sub_action.choices

    edit_parser = sub_action.choices["edit"]
    option_strings = [
        opt for action in edit_parser._actions for opt in action.option_strings
    ]
    assert "--backend" not in option_strings


def test_no_legacy_imports() -> None:
    violations: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for token in LEGACY_TOKENS:
            if token in text:
                violations.append(f"{path.name} still contains {token!r}")
    readme_text = README_PATH.read_text(encoding="utf-8")
    for token in LEGACY_TOKENS:
        if token in readme_text:
            violations.append(f"README.md still contains {token!r}")
    assert not violations, "; ".join(violations)
