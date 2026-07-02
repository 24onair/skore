"""Fetch uploaded IGC tracks from Supabase Storage via short-lived signed URLs.

The browser uploads each IGC to the ``igc`` bucket and creates a signed URL (it is
allowed to, being an authenticated user — see the storage RLS policies). It passes
those URLs to the scoring endpoint; we fetch them here. This keeps large uploads off
the serverless function (Vercel's 4.5 MB request limit) and needs no service-role
key. A prefix check restricts fetches to *this* project's storage host (anti-SSRF).
"""

from __future__ import annotations

import os

import httpx


def _allowed_prefixes() -> list[str]:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return [f"{base}/storage/v1/"] if base else []


def fetch(signed_url: str, *, timeout: float = 30.0) -> bytes:
    """Download bytes from a Supabase Storage signed URL. Raises ValueError if the
    URL isn't one of this project's storage URLs (SSRF guard)."""
    prefixes = _allowed_prefixes()
    if not prefixes or not any(signed_url.startswith(p) for p in prefixes):
        raise ValueError("허용되지 않은 스토리지 URL입니다.")
    r = httpx.get(signed_url, timeout=timeout)
    r.raise_for_status()
    return r.content
