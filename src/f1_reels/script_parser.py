"""Parse multi-video script files (``textos.txt`` format).

Expected format per block::

    Video_1 | process: Y
    First script line...
    Second script line...

    Video_2 | process: N
    This block is skipped...

Accepted header variants:

- Inline: ``Video_1 | process: Y``, ``Video_1, process=Y``,
  ``Video_1 process: Y`` (Y/N is case-insensitive).
- Two lines: a bare ``Video_1`` (or ``Something.mp4``) line followed
  by a ``process: Y`` line. A header without a marker defaults to
  not processed until a ``process: Y`` line is seen.
- The name may be any file base (``Video_1``, ``MyVideo``, ...) with
  or without the ``.mp4`` suffix.

Compatibility: if the file contains no header at all it is treated as
single-video mode and returned as ``{"__SINGLE__": ...}``.

Voice direction: lines wrapped in ``[...]`` are not narrated; they are
stored on :attr:`ScriptBlock.voice_direction` (multiple such lines are
joined with a space). A ``start-end |`` time prefix is stripped from
script lines. Blank lines and ``#`` comments are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SINGLE_VIDEO_NAME: str = "__SINGLE__"

_HEADER_INLINE: re.Pattern[str] = re.compile(
    r"^(.+?)\s*[|,;:-]?\s*process\s*[:=]\s*([YNyn])\s*$"
)
_VIDEO_ONLY: re.Pattern[str] = re.compile(
    r"^((?:Video_\d+)|[\w\-\. ]+?)(?:\.mp4)?\s*$", re.IGNORECASE
)
_PROCESS_ONLY: re.Pattern[str] = re.compile(
    r"^process\s*[:=]\s*([YNyn])\s*$", re.IGNORECASE
)
_VIDEO_INDEX: re.Pattern[str] = re.compile(r"Video_\d+", re.IGNORECASE)
_TIME_PREFIX: re.Pattern[str] = re.compile(
    r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*"
)
_VALID_INLINE_NAME: re.Pattern[str] = re.compile(r"[\w\-\. ]+")


@dataclass
class ScriptBlock:
    """One named script block from the script file."""

    name: str
    process: bool
    lines: list[str] = field(default_factory=list)
    voice_direction: str = ""


def _extract_voice_direction(line: str) -> str | None:
    """Return the inner text if the line is a ``[...]`` direction, else None."""
    text: str = line.strip()
    if len(text) > 2 and text.startswith("[") and text.endswith("]"):
        return text[1:-1].strip()
    return None


def _strip_time_prefix(line: str) -> str:
    """Remove a leading ``start-end |`` time range from a script line."""
    if "|" not in line:
        return line
    maybe_time, _, maybe_text = line.rpartition("|")
    if _TIME_PREFIX.fullmatch(maybe_time):
        return maybe_text.strip()
    return line


def _strip_video_suffix(name: str) -> str:
    """Remove a trailing ``.mp4`` suffix (case-insensitive)."""
    cleaned: str = name.strip()
    if cleaned.lower().endswith(".mp4"):
        cleaned = cleaned[:-4]
    return cleaned


def _looks_like_header(lines: list[str]) -> bool:
    """Check whether any meaningful line acts as a block header."""
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if _HEADER_INLINE.match(line) or _PROCESS_ONLY.match(line):
            return True
        match: re.Match[str] | None = _VIDEO_ONLY.match(line)
        if match and (
            _VIDEO_INDEX.fullmatch(match.group(1).strip())
            or line.lower().endswith(".mp4")
        ):
            return True
    return False


def parse_script_file(path: Path) -> dict[str, ScriptBlock]:
    """Parse a script file into ordered :class:`ScriptBlock` entries.

    Args:
        path: Path to the ``textos.txt``-style script file.

    Returns:
        Ordered mapping of block name to :class:`ScriptBlock`. Only
        blocks with ``process`` set and a non-empty ``lines`` list
        should be rendered by callers.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    script_path: Path = Path(path)
    if not script_path.exists():
        raise FileNotFoundError(f"Script file not found: {script_path}")

    raw_lines: list[str] = script_path.read_text(encoding="utf-8").splitlines()
    stripped: list[str] = [line.strip() for line in raw_lines]

    if not _looks_like_header(stripped):
        return _parse_single_mode(stripped)
    return _parse_multi_mode(stripped)


def _parse_single_mode(lines: list[str]) -> dict[str, ScriptBlock]:
    """Parse single-video mode where the whole file is one script."""
    script_lines: list[str] = []
    directions: list[str] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        direction: str | None = _extract_voice_direction(line)
        if direction:
            directions.append(direction)
            continue
        text: str = _strip_time_prefix(line)
        if text:
            script_lines.append(text)
    block: ScriptBlock = ScriptBlock(
        name=SINGLE_VIDEO_NAME,
        process=True,
        lines=script_lines,
        voice_direction=" ".join(directions).strip(),
    )
    return {SINGLE_VIDEO_NAME: block}


def _parse_multi_mode(lines: list[str]) -> dict[str, ScriptBlock]:
    """Parse multi-video mode with ``process: Y/N`` markers."""
    process_flags: dict[str, bool] = {}
    script_lines: dict[str, list[str]] = {}
    directions: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None

    def start_block(name: str, process: bool) -> None:
        """Begin (or update) a named block and make it current."""
        nonlocal current
        cleaned: str = _strip_video_suffix(name)
        if cleaned not in process_flags:
            process_flags[cleaned] = process
            script_lines[cleaned] = []
            order.append(cleaned)
        else:
            process_flags[cleaned] = process
        current = cleaned

    for line in lines:
        if not line or line.startswith("#"):
            continue

        inline: re.Match[str] | None = _HEADER_INLINE.match(line)
        if inline:
            candidate: str = inline.group(1).strip()
            # Avoid false positives: the name must be short and simple,
            # otherwise the line is treated as regular script text.
            if len(candidate) <= 60 and _VALID_INLINE_NAME.fullmatch(candidate):
                start_block(candidate, inline.group(2).upper() == "Y")
                continue

        process_only: re.Match[str] | None = _PROCESS_ONLY.match(line)
        if process_only:
            if current is not None:
                process_flags[current] = process_only.group(1).upper() == "Y"
            continue

        video_only: re.Match[str] | None = _VIDEO_ONLY.match(line)
        if video_only:
            candidate_name: str = video_only.group(1).strip()
            is_indexed: bool = _VIDEO_INDEX.fullmatch(candidate_name) is not None
            is_file: bool = line.lower().endswith(".mp4")
            if is_indexed or is_file:
                # Header without a marker defaults to not processed
                # until a "process: Y" line is seen.
                start_block(candidate_name, False)
                continue
            # Otherwise it is a regular script line; fall through.

        direction: str | None = _extract_voice_direction(line)
        if direction and current is not None:
            existing: str = directions.get(current, "")
            directions[current] = (existing + " " + direction).strip()
            continue

        text: str = _strip_time_prefix(line)
        if not text:
            continue
        if current is None:
            # Script text before any header is ignored in multi mode.
            continue
        script_lines[current].append(text)

    result: dict[str, ScriptBlock] = {}
    for name in order:
        cleaned_lines: list[str] = [item for item in script_lines[name] if item.strip()]
        result[name] = ScriptBlock(
            name=name,
            process=process_flags[name],
            lines=cleaned_lines,
            voice_direction=directions.get(name, ""),
        )
    return result
