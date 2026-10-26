"""Carrousel DSQL access — IAM token auth with a 14-minute cache."""

import os
import subprocess
import time

DSQL_HOST = os.environ.get(
    "DSQL_HOST", "fbt7qrxfs2egnxikn4bqy3mbhq.dsql.eu-north-1.on.aws"
)
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")
DSQL_USER = os.environ.get("DSQL_USER", "admin")
DBNAME = os.environ.get("DBNAME", "postgres")

TOKEN_TTL_SECONDS = 14 * 60

_cached_token = None
_cached_at = 0.0


class TokenError(RuntimeError):
    pass


def get_token():
    """Return cached DSQL IAM token, regenerating if older than 14 min."""
    global _cached_token, _cached_at
    if _cached_token and (time.time() - _cached_at) < TOKEN_TTL_SECONDS:
        return _cached_token
    try:
        result = subprocess.run(
            [
                "aws",
                "dsql",
                "generate-db-connect-admin-auth-token",
                "--hostname",
                DSQL_HOST,
                "--region",
                AWS_REGION,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as e:
        raise TokenError(f"AWS CLI not found: {e}")
    except subprocess.TimeoutExpired as e:
        raise TokenError(f"AWS CLI timed out: {e}")
    if result.returncode != 0:
        raise TokenError((result.stderr or result.stdout or "unknown error").strip())
    token = (result.stdout or "").strip()
    if not token:
        raise TokenError("empty token from AWS CLI")
    _cached_token = token
    _cached_at = time.time()
    return token


def clear_token_cache():
    global _cached_token, _cached_at
    _cached_token = None
    _cached_at = 0.0


def is_auth_error(exc):
    msg = str(exc).lower()
    return any(k in msg for k in ("auth", "expired", "token"))


def query_db(sql, params=None):
    """Run a query with IAM token auth; retry once on auth/expired/token errors."""
    import psycopg2
    from psycopg2 import OperationalError

    try:
        token = get_token()
    except Exception as e:
        raise TokenError(str(e))

    def _run(password):
        conn = psycopg2.connect(
            host=DSQL_HOST,
            dbname=DBNAME,
            user=DSQL_USER,
            password=password,
            sslmode="require",
            connect_timeout=10,
        )
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchall()
        finally:
            conn.close()

    try:
        return _run(token)
    except OperationalError as e:
        if is_auth_error(e):
            clear_token_cache()
            try:
                token2 = get_token()
            except Exception as e2:
                raise TokenError(str(e2))
            return _run(token2)
        raise
