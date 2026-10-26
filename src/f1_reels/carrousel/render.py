"""Carrousel PNG rendering — F1 job cards on the LinkedIn template."""

import os
import textwrap

TEAM_DISPLAY = {
    "alpine": "Alpine F1 Team",
    "ap_racing": "AP Racing",
    "aston_martin": "Aston Martin F1 Team",
    "cadillac": "Cadillac F1 Team",
    "general_motors_ppu": "General Motors PPU",
    "haas": "Haas F1 Team",
    "kick_sauber": "Audi F1 Team",
    "mclaren": "McLaren Mastercard F1 Team",
    "mercedes": "Mercedes F1 Team",
    "mercedes_hpp": "Mercedes HPP",
    "rb": "Visa Cashapp Racing Bulls",
    "red_bull_racing": "Oracle Red Bull Racing",
    "williams": "Williams F1 Team",
    "xtrac": "Xtrac",
}


def _static_path(*parts):
    return os.path.join(os.path.dirname(__file__), "..", "static", *parts)


TEMPLATE_PNG = _static_path("carrousel-template.png")
CENTURY_GOTHIC_TTC = _static_path("fonts", "CenturyGothic.ttc")
CENTURY_GOTHIC_REGULAR_INDEX = 0  # ("Century Gothic", "Regular")
CENTURY_GOTHIC_BOLD_INDEX = 1  # ("Century Gothic", "Bold")


def _load_bold_font(size):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(
            CENTURY_GOTHIC_TTC, size, index=CENTURY_GOTHIC_BOLD_INDEX
        )
    except Exception:
        pass
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )
    except Exception:
        return ImageFont.load_default()


def _load_regular_font(size):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(
            CENTURY_GOTHIC_TTC, size, index=CENTURY_GOTHIC_REGULAR_INDEX
        )
    except Exception:
        pass
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size
        )
    except Exception:
        return ImageFont.load_default()


MAX_TEXT_WIDTH = 1300


def _draw_centered_text(draw, text, top_y, bold, prefer_single_line=False):
    if prefer_single_line:
        size = 96 if bold else 72
        font = _load_bold_font(size) if bold else _load_regular_font(size)
        while True:
            font = _load_bold_font(size) if bold else _load_regular_font(size)
            if draw.textlength(text, font=font) <= MAX_TEXT_WIDTH or size <= 40:
                break
            size -= 4
        if draw.textlength(text, font=font) <= MAX_TEXT_WIDTH:
            lines = [text]
        else:
            size = 40
            font = _load_bold_font(size) if bold else _load_regular_font(size)
            lines = textwrap.wrap(text, width=24, break_long_words=True) or [""]
    else:
        lines = textwrap.wrap(text, width=24, break_long_words=True) or [""]
        size = 96 if len(lines) == 1 else 72
        font = _load_bold_font(size) if bold else _load_regular_font(size)
        while size > 40:
            lines = textwrap.wrap(text, width=24, break_long_words=True) or [""]
            font = _load_bold_font(size) if bold else _load_regular_font(size)
            if all(draw.textlength(line, font=font) <= MAX_TEXT_WIDTH for line in lines):
                break
            size -= 4
            if size < 40:
                size = 40
                font = _load_bold_font(size) if bold else _load_regular_font(size)
                lines = textwrap.wrap(text, width=24, break_long_words=True) or [""]
                break
        line_height = size + 12
        y = top_y
        for line in lines:
            draw.text((750, y), line, fill=(255, 255, 255), font=font, anchor="ma")
            y += line_height
        return
    line_height = size + 12
    y = top_y
    for line in lines:
        draw.text((750, y), line, fill=(255, 255, 255), font=font, anchor="ma")
        y += line_height


def team_label(team):
    return TEAM_DISPLAY.get(team, str(team or "").replace("_", " ").title())


def render_single(row):
    """Render one job as 1500x1500 PNG on top of the LinkedIn template."""
    from PIL import Image, ImageDraw

    job_id, title, team, subteam, job_type, location, link = (
        row[0],
        row[1] or "",
        row[2] or "",
        row[3] or "",
        row[4] or "",
        row[5] or "",
        row[6] or "",
    )
    team_line = team_label(team)
    loc_line = str(location)
    role_text = (title or "").upper()

    base = Image.open(TEMPLATE_PNG).convert("RGB")
    draw = ImageDraw.Draw(base)

    for text, top_y, bold, prefer_single_line in (
        (role_text, 700, True, False),
        (team_line, 900, False, True),
        (loc_line, 1075, False, True),
    ):
        _draw_centered_text(draw, text, top_y, bold, prefer_single_line)
    return base
