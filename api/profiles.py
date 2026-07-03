"""Profile store — the ``public.profiles`` row that mirrors each Supabase auth user.

Supabase Auth (GoTrue) owns identity (email/password, sessions). Our app-specific
fields — role (organizer/participant) and the pilot profile (name/bib/glider/
glider_class/contact) — live in ``public.profiles``, auto-created by the
``on_auth_user_created`` trigger from the signUp metadata.
"""

from __future__ import annotations

from .db import connect

_COLS = (
    "id, email, display_name, role, status, "
    "pilot_name, bib, glider, glider_brand, glider_class, contact"
)


def get_profile(uid: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_COLS} from profiles where id = %s::uuid", (uid,))
        row = cur.fetchone()
    return _row(row) if row else None


def list_by(*, role: str | None = None, status: str | None = None) -> list[dict]:
    """Profiles filtered by role and/or status (for the admin console)."""
    where, vals = [], []
    if role is not None:
        where.append("role = %s")
        vals.append(role)
    if status is not None:
        where.append("status = %s")
        vals.append(status)
    clause = (" where " + " and ".join(where)) if where else ""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"select {_COLS} from profiles{clause} order by created desc", vals)
        return [_row(r) for r in cur.fetchall()]


def set_status(uid: str, status: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update profiles set status = %s where id = %s::uuid returning {_COLS}",
            (status, uid),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def promote_to_organizer(uid: str) -> dict | None:
    """Make ``uid`` an active organizer (used when an admin hands a league to a pilot)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update profiles set role = 'organizer', status = 'active' "
            f"where id = %s::uuid returning {_COLS}",
            (uid,),
        )
        row = cur.fetchone()
    return _row(row) if row else None


def update_profile(uid: str, fields: dict) -> dict | None:
    cols = ("display_name", "pilot_name", "bib", "glider", "glider_brand", "glider_class", "contact")
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
        "status": r["status"],
        "pilot_name": r["pilot_name"],
        "bib": r["bib"],
        "glider": r["glider"],
        "glider_brand": r["glider_brand"],
        "glider_class": r["glider_class"],
        "contact": r["contact"],
    }


def public(profile: dict | None) -> dict | None:
    """Profiles hold no secrets; return as-is (or None)."""
    return profile
