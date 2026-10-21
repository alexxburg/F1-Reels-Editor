"""OpenRouter text-to-speech plus local audio speed-up.

Backend:
    - :class:`OpenRouterTTS`: paid TTS via OpenRouter
      (returns raw PCM wrapped into WAV on the fly).

Docs: https://openrouter.ai/docs/api/api-reference/tts/create-speech
Gemini voices: Puck | Zephyr | Charon | Kore | Fenrir | Leda | ...
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/audio/speech"
DEFAULT_REQUEST_TIMEOUT = 120  # seconds
DEFAULT_SAMPLE_RATE = 24000


def pcm_to_wav_bytes(
    pcm: bytes,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """Wrap raw little-endian PCM bytes in a WAV container.

    Args:
        pcm: Raw audio bytes (signed 16-bit LE by default).
        sample_rate: Sample rate in Hz.
        channels: Channel count (1 = mono).
        bits_per_sample: Bits per sample.

    Returns:
        Complete WAV file bytes (44-byte header + payload).
    """
    data_size = len(pcm)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM format tag
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm


class OpenRouterTTS:
    """Paid TTS via the OpenRouter ``/audio/speech`` endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "google/gemini-3.8-flash-tts",
        voice: str = "Puck",
        response_format: str = "pcm",
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Bind credentials and defaults (env vars as fallback).

        Args:
            api_key: OpenRouter key; falls back to ``OPENROUTER_API_KEY``.
            model: TTS model id.
            voice: Default voice name.
            response_format: ``"pcm"`` for Gemini (raw bytes, not JSON).
            timeout: HTTP timeout in seconds.
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model
        self.default_voice = voice
        self.response_format = response_format
        self.timeout = timeout

    def synthesize(
        self,
        text: str,
        out_path: Path | str,
        voice: str | None = None,
        instructions: str | None = None,
    ) -> Path:
        """Synthesize ``text`` and save the audio file.

        Args:
            text: Script to narrate.
            out_path: Destination file (``.mp3`` becomes ``.wav`` when the
                payload is WAV, since Gemini only returns PCM audio).
            voice: Voice override (defaults to the instance voice).
            instructions: Delivery direction; retried without it when the
                provider rejects it with HTTP 400.

        Returns:
            The real audio file path (may differ in extension).

        Raises:
            RuntimeError: Missing API key or failed synthesis.
        """
        if not self.api_key:
            raise RuntimeError("Missing OPENROUTER_API_KEY in the environment (.env).")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, str] = {
            "model": self.model,
            "input": text,
            "voice": voice or self.default_voice,
            "response_format": self.response_format,
        }
        if instructions:
            payload["instructions"] = instructions

        response = requests.post(
            OPENROUTER_API_URL, json=payload, headers=headers, timeout=self.timeout
        )
        if response.status_code == 400 and instructions:
            # Some providers do not honor `instructions`; retry without it.
            logger.warning("Provider rejected `instructions`, retrying without them.")
            payload = {k: v for k, v in payload.items() if k != "instructions"}
            response = requests.post(
                OPENROUTER_API_URL, json=payload, headers=headers, timeout=self.timeout
            )
        if response.status_code != 200:
            try:
                detail: object = response.json()
            except ValueError:
                detail = response.text[:500]
            raise RuntimeError(f"OpenRouter TTS {response.status_code}: {detail}")

        # Success is raw audio bytes, NOT JSON.
        data = response.content
        if data[:4] != b"RIFF" and self.response_format.lower() == "pcm":
            data = pcm_to_wav_bytes(data)
        target = Path(out_path)
        if target.suffix.lower() == ".mp3" and data[:4] == b"RIFF":
            target = target.with_suffix(".wav")
        target.write_bytes(data)
        return target


def accelerate_audio(path: Path | str, factor: float) -> bool:
    """Speed up an audio file in place with ffmpeg ``atempo`` (pitch safe).

    The speed is applied locally because the TTS API ``speed`` parameter is
    ignored (or rejected with 400) by several providers.

    Args:
        path: Audio file to speed up in place.
        factor: Speed factor (``1.0`` = no-op).

    Returns:
        ``True`` on success, ``False`` when ffmpeg failed (file untouched).
    """
    audio_path = Path(path)
    if factor == 1.0:
        return True
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError) as exc:
        logger.warning("ffmpeg unavailable, keeping normal speed: %s", exc)
        return False
    tmp_path = Path(str(audio_path) + ".fast.wav")
    # `atempo` accepts 0.5-2.0 per filter; plain values go through directly.
    command = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(audio_path),
        "-filter:a",
        f"atempo={factor},aresample=44100",
        "-c:a",
        "pcm_s16le",
        "-vn",
        str(tmp_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not speed up audio: %s", exc)
        return False
    if result.returncode != 0 or not tmp_path.exists():
        logger.warning(
            "Could not speed up audio (%s), keeping normal speed.",
            result.stderr.strip()[:200],
        )
        return False
    tmp_path.replace(audio_path)
    return True
