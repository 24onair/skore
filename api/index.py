"""Vercel serverless entry point.

Vercel's @vercel/python builder imports this file and serves the module-level
``app`` (an ASGI application). We keep the whole FastAPI app in the ``api`` package
(``api.main``) and just re-export it here. ``vercel.json`` lists only this file as the
Python build, so the sibling modules (auth/db/store/…) are bundled as imports rather
than mistaken for separate functions.

The route rewrite in ``vercel.json`` sends ``/api/*`` here with the original path
intact, so FastAPI's ``/api/...`` routes match unchanged.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable so `api` and `scoring` resolve as packages,
# regardless of how the runtime sets the entrypoint's module context.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.main import app  # noqa: E402  (path setup must run first)

__all__ = ["app"]
