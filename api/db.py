"""Postgres (Supabase) connection helper.

Serverless-friendly: opens a short-lived connection per operation against the
Supabase **pooler** (Supavisor / pgbouncer, port 6543). Prepared statements are
disabled because the transaction pooler doesn't keep them across checkouts.

Config comes from ``DATABASE_URL`` (env on Vercel; a local ``.env`` in dev — this
module loads it once on import so scripts/tests don't need python-dotenv).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb  # re-exported for callers writing jsonb

__all__ = ["connect", "Jsonb", "dict_row"]

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Populate os.environ from a project-root .env (local dev only). No-op if the
    keys are already set (e.g. on Vercel) or the file is absent."""
    if os.environ.get("DATABASE_URL"):
        return
    fp = _ROOT / ".env"
    if not fp.is_file():
        return
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()


def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set (check .env or Vercel env vars)")
    return dsn


def connect() -> psycopg.Connection:
    """A new autocommit connection with dict rows. Use as a context manager:

        with connect() as conn, conn.cursor() as cur:
            cur.execute(...)
    """
    return psycopg.connect(
        _dsn(),
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=None,   # transaction pooler: don't persist prepared stmts
        connect_timeout=15,
    )
