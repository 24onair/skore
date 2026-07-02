"""Authentication — verify Supabase Auth (GoTrue) JWTs.

The frontend logs in with the Supabase JS client and sends the resulting access
token as ``Authorization: Bearer <jwt>``. Supabase signs access tokens with the
project's JWT secret (HS256); we verify the signature + expiry locally and load the
app profile (role, pilot fields) from ``public.profiles``.

FastAPI dependencies keep the same names/shape as before so the route handlers are
unchanged: ``current_user`` / ``require_user`` / ``require_organizer`` /
``require_participant`` / ``require_owner``.
"""

from __future__ import annotations

import os

import jwt
from fastapi import Header, HTTPException

from . import profiles, store

_jwks_client: "jwt.PyJWKClient | None" = None


def _jwks():
    """Cached JWKS client for the project's asymmetric signing keys (ES256/RS256)."""
    global _jwks_client
    if _jwks_client is None:
        base = os.environ.get("SUPABASE_URL", "").rstrip("/")
        anon = os.environ.get("SUPABASE_ANON_KEY", "")
        _jwks_client = jwt.PyJWKClient(
            f"{base}/auth/v1/.well-known/jwks.json",
            headers={"apikey": anon} if anon else None,
        )
    return _jwks_client


def verify_token(token: str) -> dict | None:
    """Return ``{uid, email}`` for a valid Supabase access token, else None.

    Supports both new asymmetric keys (ES256/RS256 via JWKS) and the legacy shared
    secret (HS256 via ``SUPABASE_JWT_SECRET``), chosen by the token's ``alg``.
    """
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            key = os.environ.get("SUPABASE_JWT_SECRET") or ""
        else:
            key = _jwks().get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token, key, algorithms=[alg], audience="authenticated", options={"verify_aud": True}
        )
    except Exception:
        return None
    uid = payload.get("sub")
    if not uid:
        return None
    return {"uid": uid, "email": payload.get("email")}


def _token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def current_user(authorization: str | None = Header(default=None)) -> dict | None:
    """Resolve the logged-in user's profile from the Bearer token (None if anon)."""
    token = _token_from_header(authorization)
    if not token:
        return None
    claims = verify_token(token)
    if not claims:
        return None
    return profiles.get_profile(claims["uid"])


def require_user(authorization: str | None = Header(default=None)) -> dict:
    user = current_user(authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_organizer(authorization: str | None = Header(default=None)) -> dict:
    user = require_user(authorization)
    if user.get("role") != "organizer":
        raise HTTPException(status_code=403, detail="대회운영자만 사용할 수 있습니다.")
    return user


def require_participant(authorization: str | None = Header(default=None)) -> dict:
    user = require_user(authorization)
    if user.get("role") != "participant":
        raise HTTPException(status_code=403, detail="대회참가자만 사용할 수 있습니다.")
    return user


def require_owner(league_id: str, user: dict) -> dict:
    """Ensure ``user`` owns ``league_id``; returns the assembled league dict."""
    league = store.get_league(league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    owner = league.get("owner_id")
    if owner is None:
        raise HTTPException(status_code=403, detail="소유자가 지정되지 않은 리그입니다(읽기 전용).")
    if owner != user.get("uid"):
        raise HTTPException(status_code=403, detail="이 리그의 소유자만 수정할 수 있습니다.")
    return league
