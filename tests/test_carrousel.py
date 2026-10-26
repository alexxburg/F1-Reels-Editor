"""Carrousel DSQL layer tests (no AWS access; subprocess/psycopg2 stubbed)."""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from f1_reels.carrousel import db


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    db.clear_token_cache()
    yield
    db.clear_token_cache()


def _stub_subprocess(monkeypatch, calls):
    def fake_run(*args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stdout="fake-token\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)


def _install_psycopg2_stub(monkeypatch):
    """Install a stub psycopg2 module; returns (pkg, calls, behavior).

    The caller appends ("rows", [...]) or ("raise", exc) entries to
    ``behavior``; the n-th connect() consumes the n-th entry (last one
    repeats).
    """
    calls = {"n": 0}
    behavior: list = []
    pkg = types.ModuleType("psycopg2")

    class OperationalError(Exception):
        pass

    pkg.OperationalError = OperationalError

    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args):
            pass

        def fetchall(self):
            return self._rows

    class _Conn:
        def __init__(self, rows):
            self._rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return _Cursor(self._rows)

        def close(self):
            pass

    def connect(**kwargs):
        calls["n"] += 1
        kind, payload = behavior[min(calls["n"] - 1, len(behavior) - 1)]
        if kind == "raise":
            raise payload
        return _Conn(payload)

    pkg.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", pkg)
    return pkg, calls, behavior


def test_token_cached_within_ttl(monkeypatch):
    calls: list = []
    _stub_subprocess(monkeypatch, calls)
    assert db.get_token() == "fake-token"
    assert db.get_token() == "fake-token"
    assert len(calls) == 1


def test_token_refreshes_after_ttl(monkeypatch):
    calls: list = []
    _stub_subprocess(monkeypatch, calls)
    assert db.get_token() == "fake-token"
    db._cached_at -= db.TOKEN_TTL_SECONDS + 1
    assert db.get_token() == "fake-token"
    assert len(calls) == 2


def test_query_retries_once_on_auth_error(monkeypatch):
    calls: list = []
    _stub_subprocess(monkeypatch, calls)
    pkg, conn_calls, behavior = _install_psycopg2_stub(monkeypatch)
    behavior.append(("raise", pkg.OperationalError("connection expired")))
    behavior.append(("rows", [(1, "x")]))
    rows = db.query_db("SELECT 1", [])
    assert rows == [(1, "x")]
    assert conn_calls["n"] == 2


def test_query_raises_token_error_without_aws_cli(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("no aws")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(db.TokenError):
        db.get_token()


def test_is_auth_error_matches_only_auth_failures():
    assert db.is_auth_error(Exception("connection expired, retry"))
    assert db.is_auth_error(Exception("token is invalid"))
    assert db.is_auth_error(Exception("FATAL: password authentication failed"))
    assert not db.is_auth_error(Exception("syntax error at end of input"))
    assert not db.is_auth_error(Exception("connection refused"))


def test_render_produces_1500x1500_png():
    import io

    from f1_reels.carrousel import render as render_mod

    img = render_mod.render_single(
        (
            1,
            "SENIOR AERODYNAMICIST",
            "red_bull_racing",
            None,
            "Full-time",
            "Milton Keynes",
            "https://x",
        )
    )
    assert img.size == (1500, 1500) and img.mode == "RGB"
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def test_team_display_fallback_renders_text():
    import numpy as np

    from f1_reels.carrousel import render as render_mod

    img = render_mod.render_single(
        (2, "WIND TUNNEL TECH", "brand_new_team", None, "Full-time", "Nowhere", "https://x")
    )
    assert img.size == (1500, 1500)
    px = np.asarray(img)
    assert (px.mean(axis=2) > 200).mean() > 0.005
