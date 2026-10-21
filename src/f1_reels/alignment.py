"""Word-level timing alignment for voiceovers.

Timing strategy, in order:
    1. Real word timestamps via faster-whisper (when installed).
    2. Fallback: letter-weighted proportional split between the measured
       leading/trailing silences of the TTS audio.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from f1_reels.text_style import apply_reels_punch
from f1_reels.tts import OpenRouterTTS, accelerate_audio

logger = logging.getLogger(__name__)


@dataclass
class WordTiming:
    """Timing of a single script word."""

    word: str
    start: float
    end: float


@dataclass
class Voiceover:
    """Synthesized narration with word-level timings."""

    words: list[WordTiming] = field(default_factory=list)
    duration: float = 0.0
    audio_path: Path = field(default_factory=Path)


def word_weight(word: str) -> float:
    """Weight a word by letter count plus punctuation pause bonus.

    Args:
        word: Single script word (may carry trailing punctuation).

    Returns:
        Relative speech-time weight (heavier = longer).
    """
    letters = sum(1 for char in word if char.isalnum())
    weight = max(2.0, float(letters))
    last = word[-1:] if word else ""
    if last in ",;:":
        weight += 2.0
    elif last in ".!?":
        weight += 3.5
    elif last in ("—", "–", "-", '"', "'", ")", "”"):
        weight += 1.0
    return weight


def split_words_fallback(
    text: str,
    total_duration: float,
    start: float = 0.0,
    gap: float = 0.035,
) -> list[WordTiming]:
    """Split ``total_duration`` across words proportional to letter weight.

    Args:
        text: Script whose words receive timings.
        total_duration: Speech span in seconds (last word ends at
            ``start + total_duration``).
        start: Span start offset in seconds.
        gap: Inter-word pause in seconds (shrunk when gaps would exceed
            40% of the span).

    Returns:
        One :class:`WordTiming` per word, spanning exactly ``total_duration``.
    """
    raw = text.split()
    if not raw or total_duration <= 0:
        return []
    weights = [word_weight(word) for word in raw]
    count = len(raw)
    total_gap = gap * (count - 1) if count > 1 else 0.0
    if total_gap >= total_duration * 0.4 and count > 1:
        gap = total_duration * 0.15 / (count - 1)
        total_gap = gap * (count - 1)
    speech = max(0.05, total_duration - total_gap)
    weight_sum = sum(weights) or 1.0
    cursor = start
    out: list[WordTiming] = []
    for index, (word, weight) in enumerate(zip(raw, weights)):
        length = speech * weight / weight_sum
        out.append(WordTiming(word=word, start=cursor, end=cursor + length))
        cursor += length + (gap if index < count - 1 else 0.0)
    if out:
        out[-1].end = start + total_duration
    return out


def measure_silences(
    path: Path | str, sample_rate: int = 16000, threshold: float = 0.02
) -> tuple[float, float]:
    """Measure leading/trailing silence of a TTS audio file.

    TTS engines often leave 50-150ms of air that shifts every subtitle when
    ignored. Decodes to raw PCM with ffmpeg (avoids moviepy artifacts).

    Args:
        path: Audio file.
        sample_rate: Decode sample rate in Hz.
        threshold: RMS level above which a 20ms window counts as speech.

    Returns:
        ``(leading, trailing)`` silence in seconds; ``(0.0, 0.0)`` when the
        audio cannot be decoded.
    """
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "-",
            ],
            capture_output=True,
        )
    except (ImportError, OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not measure silences: %s", exc)
        return 0.0, 0.0
    if result.returncode != 0 or not result.stdout:
        return 0.0, 0.0
    try:
        import numpy as np

        pcm = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    except (ValueError, TypeError) as exc:
        logger.warning("Could not decode PCM for silence measurement: %s", exc)
        return 0.0, 0.0
    if pcm.size == 0:
        return 0.0, 0.0
    window = max(1, sample_rate // 50)  # 20ms windows
    windows = pcm.size // window
    if windows == 0:
        return 0.0, 0.0
    rms = np.sqrt((pcm[: windows * window].reshape(windows, window) ** 2).mean(axis=1))
    voiced = rms > threshold
    if not voiced.any():
        return 0.0, 0.0
    duration = pcm.size / sample_rate
    first = int(np.argmax(voiced))
    last = len(voiced) - 1 - int(np.argmax(voiced[::-1]))
    lead = first * window / sample_rate
    trail = max(0.0, duration - (last + 1) * window / sample_rate)
    return min(lead, duration * 0.3), min(trail, duration * 0.3)


def _normalize_word(word: str) -> str:
    """Normalize for comparison: lowercase, alphanumeric only."""
    return "".join(char for char in word.lower() if char.isalnum())


#: Minimum fraction of script words with an assigned detection below
#: which alignment is rejected (caller falls back to weighted split).
#: 0.8 tolerates an isolated split/merge/substitution/insertion/
#: deletion while rejecting garbage (e.g. 3 unrelated detections over
#: 10 script words only match ~0.3 and return None).
MATCHED_FRACTION_MIN = 0.8


def align_script_words(
    script_words: list[str], detected: list[WordTiming]
) -> list[WordTiming] | None:
    """Align script words to whisper detections with tolerant sequencing.

    Dynamic program over script x detected with operations (costs):
    match/substitute 1:1 (0 when normalized forms are equal, else 1),
    skip-detected/insertion (1), skip-script/deletion (1), merge of
    2 script words into 1 detected word when the concatenated
    normalized forms are exactly equal (0.5), and split of 1 script
    word over 2 detected words on the same equality (0.5).

    Args:
        script_words: Script tokens with original spelling (output words).
        detected: Whisper word timings (transcribed spelling).

    Returns:
        One :class:`WordTiming` per script word using the original
        script spelling, or ``None`` when the matched-script fraction
        (script words with >= 1 assigned detection) is below
        ``MATCHED_FRACTION_MIN``.
    """
    total = len(script_words)
    count = len(detected)
    if not script_words:
        return []
    if not detected:
        return None
    norm_script = [_normalize_word(word) for word in script_words]
    norm_detected = [_normalize_word(item.word) for item in detected]
    dp = [[0.0] * (count + 1) for _ in range(total + 1)]
    for i in range(1, total + 1):
        dp[i][0] = float(i)
    for j in range(1, count + 1):
        dp[0][j] = float(j)
    for i in range(1, total + 1):
        for j in range(1, count + 1):
            sub = 0 if norm_script[i - 1] == norm_detected[j - 1] else 1
            best = dp[i - 1][j - 1] + sub
            skip_detected = dp[i][j - 1] + 1
            if skip_detected < best:
                best = skip_detected
            skip_script = dp[i - 1][j] + 1
            if skip_script < best:
                best = skip_script
            if (
                i >= 2
                and j >= 1
                and norm_script[i - 2] + norm_script[i - 1] == norm_detected[j - 1]
            ):
                merge = dp[i - 2][j - 1] + 0.5
                if merge < best:
                    best = merge
            if (
                i >= 1
                and j >= 2
                and norm_script[i - 1] == norm_detected[j - 2] + norm_detected[j - 1]
            ):
                split = dp[i - 1][j - 2] + 0.5
                if split < best:
                    best = split
            dp[i][j] = best

    def _close(a: float, b: float) -> bool:
        return abs(a - b) < 1e-9

    assigned: list[list[int]] = [[] for _ in range(total)]
    i, j = total, count
    while i > 0 or j > 0:
        if (
            i >= 2
            and j >= 1
            and norm_script[i - 2] + norm_script[i - 1] == norm_detected[j - 1]
            and _close(dp[i][j], dp[i - 2][j - 1] + 0.5)
        ):
            assigned[i - 2].append(j - 1)
            assigned[i - 1].append(j - 1)
            i -= 2
            j -= 1
            continue
        if (
            i >= 1
            and j >= 2
            and norm_script[i - 1] == norm_detected[j - 2] + norm_detected[j - 1]
            and _close(dp[i][j], dp[i - 1][j - 2] + 0.5)
        ):
            assigned[i - 1].extend([j - 2, j - 1])
            i -= 1
            j -= 2
            continue
        if i >= 1 and j >= 1:
            sub = 0 if norm_script[i - 1] == norm_detected[j - 1] else 1
            if _close(dp[i][j], dp[i - 1][j - 1] + sub):
                assigned[i - 1].append(j - 1)
                i -= 1
                j -= 1
                continue
        if i >= 1 and _close(dp[i][j], dp[i - 1][j] + 1):
            i -= 1
            continue
        if j >= 1 and _close(dp[i][j], dp[i][j - 1] + 1):
            j -= 1
            continue
        break
    matched = sum(1 for indices in assigned if indices)
    if matched / total < MATCHED_FRACTION_MIN:
        return None
    out: list[WordTiming | None] = [None] * total
    for index, indices in enumerate(assigned):
        if not indices:
            continue
        begin = min(detected[k].start for k in indices)
        end = max(detected[k].end for k in indices)
        out[index] = WordTiming(word=script_words[index], start=begin, end=end)
    first_start = detected[0].start
    last_end = detected[-1].end
    pos = 0
    while pos < total:
        if out[pos] is not None:
            pos += 1
            continue
        run_start = pos
        while pos < total and out[pos] is None:
            pos += 1
        run_end = pos  # exclusive
        left = out[run_start - 1] if run_start > 0 else None
        right = out[run_end] if run_end < total else None
        if left is not None and right is not None:
            gap_start, gap_end = left.end, right.start
        elif right is not None:
            gap_start, gap_end = first_start, right.start
        elif left is not None:
            gap_start, gap_end = left.end, last_end
        else:  # unreachable under the confidence gate, kept for safety
            gap_start, gap_end = first_start, last_end
        gap_words = script_words[run_start:run_end]
        if gap_end > gap_start:
            filled = split_words_fallback(
                " ".join(gap_words), gap_end - gap_start, start=gap_start
            )
            for offset, item in enumerate(filled):
                out[run_start + offset] = item
        else:
            for offset, word in enumerate(gap_words):
                out[run_start + offset] = WordTiming(
                    word=word, start=gap_start, end=gap_start
                )
    return [item for item in out if item is not None]


def align_with_whisper(
    path: Path | str, text: str, model_name: str = "base"
) -> list[WordTiming] | None:
    """Align script words with real faster-whisper word timestamps.

    Tolerant sequence alignment handles splits, merges, substitutions,
    insertions, and deletions; when the matched-script fraction falls
    below the gate the caller should use the weighted fallback instead.

    Args:
        path: Synthesized audio file.
        text: Script with the original spelling (used for output words).
        model_name: faster-whisper model size.

    Returns:
        Word timings, or ``None`` when whisper is unavailable, detects no
        words, fails the match gate, or fails.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        script = text.split()
        if not script:
            return []
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
        detected = [
            WordTiming(
                word=chunk.word.strip(),
                start=float(chunk.start),
                end=float(chunk.end),
            )
            for segment in segments
            for chunk in (segment.words or [])
            if chunk.word and chunk.word.strip()
        ]
        if not detected:
            return None
        aligned = align_script_words(script, detected)
        if aligned is None:
            logger.warning(
                "Whisper detected %d words vs %d in the script, using estimate.",
                len(detected),
                len(script),
            )
            return None
        return aligned
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("Whisper failed (%s), using estimated split.", str(exc)[:150])
        return None


def generate_voiceover(
    text: str,
    audio_path: Path | str,
    *,
    voice: str | None = None,
    model: str | None = None,
    instructions: str | None = None,
    speed: float = 1.0,
    subtitle_lead: float = 0.0,
    apply_punch: bool = True,
    use_whisper: bool = True,
    whisper_model: str = "base",
) -> Voiceover:
    """Generate narration audio and word-level timings (OpenRouter only).

    Args:
        text: Script to narrate.
        audio_path: Destination audio file.
        voice: Voice override for OpenRouter.
        model: TTS model id override (defaults to the OpenRouter default).
        instructions: Delivery direction (OpenRouter only).
        speed: Local ffmpeg speed factor (``1.0`` = unchanged).
        subtitle_lead: Seconds to shift every word earlier so the highlight
            never lags perceived speech (never below 0).
        apply_punch: Run :func:`apply_reels_punch` on the script first.
        use_whisper: Try real word timestamps before the fallback split.
        whisper_model: faster-whisper model size.

    Returns:
        :class:`Voiceover` with words, audio duration, and real audio path.

    Raises:
        RuntimeError: TTS synthesis or audio probing failed.
    """
    if apply_punch:
        punched = apply_reels_punch(text)
        if punched != text:
            logger.info("Reels punch: %s...", punched[:90])
        text = punched
    target = Path(audio_path)
    tts_kwargs: dict[str, str] = {}
    if model:
        tts_kwargs["model"] = model
    tts = OpenRouterTTS(**tts_kwargs)
    target = tts.synthesize(text, target, voice=voice, instructions=instructions)
    if speed != 1.0:
        accelerate_audio(target, speed)
    try:
        from moviepy.editor import AudioFileClip

        clip = AudioFileClip(str(target))
        duration = float(clip.duration)
        clip.close()
    except ImportError as exc:
        raise RuntimeError("Missing moviepy: pip install moviepy") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read TTS audio: {exc}") from exc

    words: list[WordTiming] | None = None
    if use_whisper:
        words = align_with_whisper(target, text, whisper_model)
    if not words:
        lead, trail = measure_silences(target)
        begin = min(lead, duration * 0.5)
        end = max(begin + 0.1, duration - trail)
        words = split_words_fallback(text, end - begin, start=begin)
    if subtitle_lead:
        words = [
            WordTiming(
                word=item.word,
                start=max(0.0, item.start - subtitle_lead),
                end=max(0.01, item.end - subtitle_lead),
            )
            for item in words
        ]
    return Voiceover(words=words, duration=duration, audio_path=target)
