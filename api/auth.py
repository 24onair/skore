"""Authentication primitives — stdlib only (no JWT/passlib dependency).

Three concerns:

1. **Password hashing** — PBKDF2-HMAC-SHA256 (200k iterations) with a per-user
   random salt, stored as ``pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>``.
   Verification is constant-time via :func:`hmac.compare_digest`.

2. **Session token** — a stateless signed token ``<payload_b64>.<sig_b64>`` where
   the payload is ``{"uid","role","exp"}`` JSON and the signature is
   HMAC-SHA256 over the payload bytes keyed by the server SECRET. No server-side
   session table; the cookie itself is the credential. Tampering or expiry →
   rejected.

3. **FastAPI dependencies** — read the ``skore_session`` httpOnly cookie and
   resolve the current user / enforce role / enforce league ownership.

The SECRET comes from ``$SKORE_SECRET`` or, failing that, a generated
``data/secret.key`` (git-ignored). Rotating the secret invalidates all sessions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from fastapi import Cookie, HTTPException

from . import store
from . import users as users_store

COOKIE_NAME = "skore_session"
TOKEN_TTL = 60 * 60 * 24 * 14  # 14 days
_PBKDF2_ITERS = 200_000
_SECRET_PATH = Path(__file__).resolve().parent.parent / "data" / "secret.key"


# --------------------------------------------------------------------------- #
# Secret
# --------------------------------------------------------------------------- #
def _secret() -> bytes:
    import os

    env = os.environ.get("SKORE_SECRET")
    if env:
        return env.encode("utf-8")
    if _SECRET_PATH.is_file():
        return _SECRET_PATH.read_bytes()
    _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    _SECRET_PATH.write_bytes(key)
    return key


# --------------------------------------------------------------------------- #
# Password hashing (PBKDF2-HMAC-SHA256)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters_s))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------- #
# Signed session token
# --------------------------------------------------------------------------- #
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid: str, role: str, ttl: int = TOKEN_TTL) -> str:
    payload = {"uid": uid, "role": role, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str | None) -> dict | None:
    """Return the validated payload, or None if missing/tampered/expired."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def current_user(skore_session: str | None = Cookie(default=None)) -> dict | None:
    """Resolve the logged-in user from the session cookie (None if anonymous)."""
    payload = read_token(skore_session)
    if not payload:
        return None
    return users_store.get_user(payload["uid"])


def require_user(skore_session: str | None = Cookie(default=None)) -> dict:
    user = current_user(skore_session)
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_organizer(skore_session: str | None = Cookie(default=None)) -> dict:
    user = require_user(skore_session)
    if user.get("role") != "organizer":
        raise HTTPException(status_code=403, detail="대회운영자만 사용할 수 있습니다.")
    return user


def require_participant(skore_session: str | None = Cookie(default=None)) -> dict:
    user = require_user(skore_session)
    if user.get("role") != "participant":
        raise HTTPException(status_code=403, detail="대회참가자만 사용할 수 있습니다.")
    return user


def require_owner(league_id: str, user: dict) -> dict:
    """Ensure ``user`` owns ``league_id``; returns the league dict on success."""
    league = store.get_league(league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    owner = league.get("owner_id")
    if owner is None:
        # Legacy league with no owner — read-only for everyone (safe default).
        raise HTTPException(status_code=403, detail="소유자가 지정되지 않은 리그입니다(읽기 전용).")
    if owner != user.get("uid"):
        raise HTTPException(status_code=403, detail="이 리그의 소유자만 수정할 수 있습니다.")
    return league
