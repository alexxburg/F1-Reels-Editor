"""Tests for ``f1_reels.tts`` with mocked HTTP."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from f1_reels import tts
from f1_reels.tts import OpenRouterTTS, accelerate_audio, pcm_to_wav_bytes


class FakeResponse:
    def __init__(self, status_code=200, content=b"", payload=None, text=""):
        self.status_code = status_code
        self.content = content
        self._payload = payload
        self.text = text or ""

    def json(self):
        if self._payload is not None:
            return self._payload
        raise ValueError("No JSON")


def _pcm_sample() -> bytes:
    return b"\x01\x02\x03\x04" * 100


def test_pcm_to_wav_bytes_header():
    pcm = _pcm_sample()
    wav = pcm_to_wav_bytes(pcm, sample_rate=24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"
    assert len(wav) == 44 + len(pcm)
    (chunk_size,) = struct.unpack("<I", wav[4:8])
    assert chunk_size == 36 + len(pcm)
    (sample_rate,) = struct.unpack("<I", wav[24:28])
    assert sample_rate == 24000


def test_pcm_to_wav_bytes_custom_rate():
    wav = pcm_to_wav_bytes(b"\x00\x00" * 10, sample_rate=44100, channels=2)
    (sample_rate,) = struct.unpack("<I", wav[24:28])
    assert sample_rate == 44100
    (channels,) = struct.unpack("<H", wav[22:24])
    assert channels == 2


def test_synthesize_wraps_pcm_to_wav(tmp_path, monkeypatch):
    pcm = _pcm_sample()
    monkeypatch.setattr(
        tts.requests, "post", lambda *a, **k: FakeResponse(200, content=pcm)
    )
    client = OpenRouterTTS(api_key="key")
    out = tmp_path / "voice.wav"
    result = client.synthesize("hello", out)
    assert result == out
    data = out.read_bytes()
    assert data[:4] == b"RIFF"


def test_synthesize_mp3_renamed_to_wav(tmp_path, monkeypatch):
    pcm = _pcm_sample()
    monkeypatch.setattr(
        tts.requests, "post", lambda *a, **k: FakeResponse(200, content=pcm)
    )
    client = OpenRouterTTS(api_key="key")
    out = tmp_path / "voice.mp3"
    result = client.synthesize("hello", out)
    assert result == tmp_path / "voice.wav"
    assert result.read_bytes()[:4] == b"RIFF"
    assert not out.exists()


def test_synthesize_already_riff_not_rewrapped(tmp_path, monkeypatch):
    wav = pcm_to_wav_bytes(_pcm_sample())
    monkeypatch.setattr(
        tts.requests, "post", lambda *a, **k: FakeResponse(200, content=wav)
    )
    client = OpenRouterTTS(api_key="key")
    out = tmp_path / "voice.wav"
    result = client.synthesize("hello", out)
    assert result.read_bytes() == wav


def test_synthesize_400_with_instructions_retries(tmp_path, monkeypatch):
    pcm = _pcm_sample()
    calls: list[dict] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs.get("json", {}))
        if len(calls) == 1:
            return FakeResponse(400, content=b"", payload={"error": "bad"}, text="bad")
        return FakeResponse(200, content=pcm)

    monkeypatch.setattr(tts.requests, "post", fake_post)
    client = OpenRouterTTS(api_key="key")
    out = tmp_path / "voice.wav"
    result = client.synthesize("hello", out, instructions="speak fast")
    assert result.read_bytes()[:4] == b"RIFF"
    assert len(calls) == 2
    assert "instructions" in calls[0]
    assert "instructions" not in calls[1]


def test_synthesize_400_without_instructions_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *a, **k: FakeResponse(400, content=b"", payload={"error": "x"}, text="x"),
    )
    client = OpenRouterTTS(api_key="key")
    with pytest.raises(RuntimeError, match="OpenRouter TTS 400"):
        client.synthesize("hello", tmp_path / "voice.wav")


def test_synthesize_non_200_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tts.requests,
        "post",
        lambda *a, **k: FakeResponse(500, content=b"oops", text="oops"),
    )
    client = OpenRouterTTS(api_key="key")
    with pytest.raises(RuntimeError, match="OpenRouter TTS 500"):
        client.synthesize("hello", tmp_path / "voice.wav")


def test_synthesize_missing_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = OpenRouterTTS(api_key="")
    with pytest.raises(RuntimeError, match="Missing OPENROUTER_API_KEY"):
        client.synthesize("hello", tmp_path / "voice.wav")


def test_accelerate_audio_factor_1_noop(tmp_path):
    target = tmp_path / "audio.wav"
    target.write_bytes(b"fake-audio")
    assert accelerate_audio(target, 1.0) is True
    assert target.read_bytes() == b"fake-audio"


def test_accelerate_audio_uses_env_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    client = OpenRouterTTS(api_key=None)
    assert client.api_key == "env-key"
