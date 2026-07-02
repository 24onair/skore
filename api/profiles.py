"""Profile store — the ``public.profiles`` row that mirrors each Supabase auth user.

Supabase Auth (GoTrue) owns identity (email/password, sessions). Our app-specific
fields — role (organizer/participant) and the pilot profile (name/bib/glider/
glider_class/contact) — live in ``public.profiles``, auto-created by the
``on_auth_user_created`` trigger from the signUp metadata.
"""

from __future__ import annotations

from .db import connect

_COLS = "id, email, display_name, role, pilot_name, bib, glider, glider_class, contact"


def get_profile(uid: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_COLS} from profiles where id = %s::uuid", (uid,))
        row = cur.fetchone()
    return _row(row) if row else None


def update_profile(uid: str, fields: dict) -> dict | None:
    cols = ("display_name", "pilot_name", "bib", "glider", "glider_class", "contact")
    sets, vals = [], []
    for k in cols:
        if k in fields and fields[k] is not None:
            sets.append(f"{k} = %s")
            vals.append((fields[k] or "").strip())
    if not sets:
        return get_profile(uid)
    vals.append(uid)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update profiles set {', '.join(sets)} where id = %s::uuid returning {_COLS}", vals
        )
        row = cur.fetchone()
    return _row(row) if row else None


def _row(r: dict) -> dict:
    return {
        "uid": str(r["id"]),
        "email": r["email"],
        "display_name": r["display_name"],
        "role": r["role"],
        "pilot_name": r["pilot_name"],
        "bib": r["bib"],
        "glider": r["glider"],
        "glider_class": r["glider_class"],
        "contact": r["contact"],
    }


def public(profile: dict | None) -> dict | None:
    """Profiles hold no secrets; return as-is (or None)."""
    return profile
