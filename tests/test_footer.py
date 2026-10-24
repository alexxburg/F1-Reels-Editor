"""Footer-caption generation (hooky line + 5 hashtags) via OpenRouter."""

from __future__ import annotations


def test_prompt_file_has_hook_and_hashtag_rules():
    from pathlib import Path

    prompt_path = Path("src/f1_reels/footer_prompt.md")
    assert prompt_path.is_file(), "prompt must live in a file"
    text = prompt_path.read_text(encoding="utf-8").lower()
    assert "hook" in text
    assert "5" in text and "hashtag" in text


def test_generate_footer_posts_chat_payload(monkeypatch):
    import json

    from f1_reels import footer as footer_mod

    calls = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "Hook line here\n#one #two"}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["url"] = url
        calls["payload"] = json
        calls["auth"] = headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(footer_mod.requests, "post", fake_post)
    out = footer_mod.generate_footer("fastest lap ever", api_key="k", model="m")
    assert out == "Hook line here\n#one #two"
    assert calls["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls["auth"] == "Bearer k"
    assert calls["payload"]["model"] == "m"
    assert calls["payload"]["reasoning"] == {"effort": "medium"}
    roles = [m["role"] for m in calls["payload"]["messages"]]
    assert roles[0] == "system" and roles[-1] == "user"


def test_generate_footer_raises_without_key():
    import pytest

    from f1_reels import footer as footer_mod

    with pytest.raises(RuntimeError):
        footer_mod.generate_footer("text", api_key="")


def test_generate_footer_raises_on_upstream_error(monkeypatch):
    import pytest

    from f1_reels import footer as footer_mod

    class FakeResponse:
        status_code = 429

        def json(self):
            return {"error": "rate limited"}

        text = "rate limited"

    monkeypatch.setattr(
        footer_mod.requests, "post", lambda *a, **k: FakeResponse()
    )
    with pytest.raises(RuntimeError):
        footer_mod.generate_footer("text", api_key="k")
