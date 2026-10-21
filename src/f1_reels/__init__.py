"""Typed F1 reels editing pipeline.

New code lives here; the legacy ``Editvideos.py`` / ``Postprocess_bricks.py``
/ ``Voices.py`` scripts are kept as-is for reference.
"""

from .alignment import generate_voiceover
from .brick_config import LOGO_POR_VIDEO, TRIM_POR_TAKE, logo_for_video, trim_for_take
from .broll import BrollConfig, BrollSelector
from .config import Settings
from .endcard import EndcardConfig, build_endcard
from .pipeline import PipelineConfig, edit_video
from .script_parser import ScriptBlock, parse_script_file
from .subtitles import SubtitleStyle

__all__ = [
    "BrollConfig",
    "BrollSelector",
    "EndcardConfig",
    "LOGO_POR_VIDEO",
    "PipelineConfig",
    "ScriptBlock",
    "Settings",
    "SubtitleStyle",
    "TRIM_POR_TAKE",
    "build_endcard",
    "edit_video",
    "generate_voiceover",
    "logo_for_video",
    "parse_script_file",
    "trim_for_take",
]
