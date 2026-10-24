"""AI reel-footer captions (hooky line + hashtags) via OpenRouter chat.

The system prompt lives in ``footer_prompt.md`` next to this module so it
can be edited without touching code.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
FOOTER_MODEL_DEFAULT = "meta/muse-spark-1.3-contributor"
FOOTER_REASONING_EFFORT = "medium"
# Reasoning tokens share the max_tokens budget (medium effort can spend
# ~900 tokens thinking), so the ceiling must stay far above the ~150-token
# footer or the visible reply gets truncated to nothing.
FOOTER_MAX_TOKENS = 2000

BUILTIN_PROMPT = """\
Write the upload caption footer for a short motorsport (Formula 1) reel,
based on the reel's script lines. Output plain text only: one hooky opening
line that makes scrolling stop, followed by exactly 5 relevant hashtags.
Keep it under 280 characters. No preamble, no quotes, no explanations."""


def load_footer_prompt() -> str:
    """Return the footer system prompt, preferring ``footer_prompt.md``."""
    try:
        text = (Path(__file__).resolve().parent / "footer_prompt.md").read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Footer prompt file missing, using builtin: %s", exc)
        return BUILTIN_PROMPT
    text = text.strip()
    return text or BUILTIN_PROMPT


def generate_footer(
    script_text: str,
    *,
    api_key: str,
    model: str = FOOTER_MODEL_DEFAULT,
    timeout: float = 60.0,
) -> str:
    """Generate a hooky footer caption with hashtags for ``script_text``.

    Raises:
        RuntimeError: Missing API key or failed generation.
    """
    if not (api_key or "").strip():
        raise RuntimeError("Missing OPENROUTER_API_KEY in the environment (.env).")
    if not (script_text or "").strip():
        raise RuntimeError("Empty script: nothing to caption.")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
    }
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": load_footer_prompt()},
            {"role": "user", "content": script_text.strip()},
        ],
        "reasoning": {"effort": FOOTER_REASONING_EFFORT},
        "max_tokens": FOOTER_MAX_TOKENS,
    }
    try:
        response = requests.post(
            OPENROUTER_CHAT_URL, json=payload, headers=headers, timeout=timeout
        )
    except Exception as exc:
        raise RuntimeError(f"OpenRouter footer request failed: {exc}") from exc
    if response.status_code != 200:
        try:
            detail: object = response.json()
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"OpenRouter footer {response.status_code}: {detail}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"OpenRouter footer bad payload: {exc}") from exc
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("OpenRouter footer returned empty text.")
    return text
