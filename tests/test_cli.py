"""Tests for the ``f1-reels`` CLI: argparse parsing only (no video needed)."""

from pathlib import Path

import pytest

from f1_reels.cli import build_parser, main


def test_cmd_edit_uses_no_legacy(tmp_path):
    """_cmd_edit must run on src/ only: no legacy bridge, no backend flags."""
    cli_path = Path(__file__).resolve().parent.parent / "src" / "f1_reels" / "cli.py"
    text = cli_path.read_text(encoding="utf-8")
    assert "import Editvideos" not in text
    assert "legacy." not in text

    parser = build_parser()
    sub_action = next(
        a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
    )
    assert "sample-voices" not in sub_action.choices
    edit_parser = sub_action.choices["edit"]
    option_strings = [
        opt for action in edit_parser._actions for opt in action.option_strings
    ]
    assert "--backend" not in option_strings
    assert "--sample-voices" not in option_strings

    from f1_reels.config import find_first_font

    probe = tmp_path / "ProbeFont.ttf"
    probe.write_bytes(b"fake-font")
    missing = tmp_path / "Missing.ttf"
    assert find_first_font((str(missing), str(probe))) == probe
    with pytest.raises(FileNotFoundError):
        find_first_font((str(missing),))


def test_parser_registers_two_subcommands():
    parser = build_parser()
    sub_action = next(
        a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
    )
    assert set(sub_action.choices) == {"edit", "postprocess-bricks"}


def test_edit_parsing_and_defaults():
    args = build_parser().parse_args(["edit", "textos.txt"])
    assert args.command == "edit"
    assert str(args.text_file) == "textos.txt"
    assert str(args.output_dir) == "Videos_Editados"
    assert not hasattr(args, "backend")
    assert args.margin == 1.0
    assert args.no_endcard is False
    assert args.seed is None


def test_edit_options():
    args = build_parser().parse_args(
        ["edit", "textos.txt", "--output-dir", "out", "--seed", "7"]
    )
    assert str(args.output_dir) == "out"
    assert args.seed == 7


def test_postprocess_bricks_parsing_and_defaults():
    args = build_parser().parse_args(["postprocess-bricks"])
    assert args.command == "postprocess-bricks"
    assert str(args.input_dir) == "Video Bricks"
    assert str(args.output_dir) == "Post Processed Videos"
    assert args.overwrite is False
    assert args.dry_run is False


def test_postprocess_bricks_flags():
    args = build_parser().parse_args(
        ["postprocess-bricks", "--input", "in", "--output", "out",
         "--overwrite", "--dry-run"]
    )
    assert str(args.input_dir) == "in"
    assert str(args.output_dir) == "out"
    assert args.overwrite is True
    assert args.dry_run is True


def test_main_rejects_unknown_command():
    with pytest.raises(SystemExit) as exc:
        main(["no-such-command"])
    assert exc.value.code == 2


def test_import_has_no_side_effects(tmp_path, monkeypatch):
    """Importing the CLI must not create files or read sys.argv."""
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    import importlib

    import f1_reels.cli

    importlib.reload(f1_reels.cli)
    assert set(tmp_path.iterdir()) == before
