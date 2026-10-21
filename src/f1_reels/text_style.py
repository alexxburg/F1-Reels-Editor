"""Viral-delivery text styling for Reels voiceovers.

The transformation only changes punctuation/casing, never the word count,
so word-level subtitle alignment stays exact.
"""

from __future__ import annotations

import re

_LONG_SENTENCE_MIN_SPACES = 15
_HOOK_MIN_WORDS = 3


def apply_reels_punch(text: str) -> str:
    """Apply the viral Reels delivery style to ``text``.

    1. Hook: the first sentence ends with ``!`` if it ended with ``.``
       (and has at least 3 words).
    2. Long sentences: ``", "`` becomes ``". "`` when a segment holds
       more than 15 words, splitting flat enumerations into short,
       punchy sentences.

    Args:
        text: Original narration script.

    Returns:
        The styled script with the same word count as the input.
    """
    if not text or not text.strip():
        return text
    styled = text.strip()
    hook = re.match(r"^([^.!?]+)\.\s+(.*)$", styled, re.DOTALL)
    if hook and len(hook.group(1).split()) >= _HOOK_MIN_WORDS:
        styled = hook.group(1).rstrip() + "! " + hook.group(2).lstrip()
    sentences = re.split(r"(?<=[.!?])\s+", styled)
    reshaped: list[str] = []
    for sentence in sentences:
        if sentence.count(" ") >= _LONG_SENTENCE_MIN_SPACES and ", " in sentence:
            sentence = _split_long_sentence(sentence)
        reshaped.append(sentence)
    return " ".join(reshaped)


def _split_long_sentence(sentence: str) -> str:
    """Split a long comma-heavy sentence near its middle word.

    Returns the sentence unchanged when no clean split point exists.
    """
    chunks = sentence.split(", ")
    head: list[str] = []
    word_count = 0
    half = len(sentence.split()) / 2
    tail: list[str] = []
    for index, chunk in enumerate(chunks):
        if word_count + len(chunk.split()) < half or not head:
            head.append(chunk)
            word_count += len(chunk.split())
        else:
            tail = chunks[index:]
            break
    if (
        tail
        and len(tail[0].split()) >= _HOOK_MIN_WORDS
        and not re.search(r"\b(e\.g|i\.e|vs)\.?$", head[-1].strip(), re.IGNORECASE)
    ):
        sentence = ", ".join(head).rstrip() + ". " + ", ".join(tail).lstrip()
        sentence = re.sub(
            r"\. ([a-z])",
            lambda match: ". " + match.group(1).upper(),
            sentence,
            count=1,
        )
    return sentence
