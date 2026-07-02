"""File-based user store (mirrors the league store in ``store.py``).

One JSON file per user under ``data/users/<uid>.json``, plus an email→uid index
(``data/users/_index.json``) so login lookups and uniqueness checks are O(1)
without scanning every file.

A user has a role — ``organizer`` (대회운영자) or ``participant`` (대회참가자).
Participants also carry ``pilot_name``/``bib`` used to auto-match their results
against league rosters (see ``api.main`` ``/api/me/results``).

Passwords are never stored in plaintext: ``password_hash`` is produced by
:func:`api.auth.hash_password` (PBKDF2). This module only stores the opaque hash.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from . import auth

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "users"
INDEX_PATH = DATA_DIR / "_index.json"

ROLES = ("organizer", "participant")


class UserError(ValueError):
    """Raised for signup/login problems (duplicate email, bad role, ...)."""


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _path(uid: str) -> Path:
    return DATA_DIR / f"{uid}.json"


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


# --------------------------------------------------------------------------- #
# Email index (email -> uid)
# --------------------------------------------------------------------------- #
def _load_index() -> dict[str, str]:
    if not INDEX_PATH.is_file():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_index(idx: dict[str, str]) -> None:
    _ensure_dir()
    INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _save(user: dict) -> None:
    _ensure_dir()
    _path(user["uid"]).write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user(uid: str) -> dict | None:
    fp = _path(uid)
    if not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def get_user_by_email(email: str) -> dict | None:
    uid = _load_index().get(_norm_email(email))
    return get_user(uid) if uid else None


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def create_user(
    email: str,
    password: str,
    display_name: str,
    role: str,
    pilot_name: str = "",
    bib: str = "",
    glider: str = "",
    contact: str = "",
    glider_class: str = "",
) -> dict:
    email = _norm_email(email)
    if not email or "@" not in email:
        raise UserError("올바른 이메일을 입력하세요.")
    if not password or len(password) < 6:
        raise UserError("비밀번호는 6자 이상이어야 합니다.")
    if role not in ROLES:
        raise UserError("역할이 올바르지 않습니다.")
    if not (display_name or "").strip():
        raise UserError("이름을 입력하세요.")

    idx = _load_index()
    if email in idx:
        raise UserError("이미 가입된 이메일입니다.")

    is_pilot = role == "participant"
    user = {
        "uid": _id(),
        "email": email,
        "password_hash": auth.hash_password(password),
        "display_name": display_name.strip(),
        "role": role,
        # participant matching identity; default the pilot name to the display name
        "pilot_name": (pilot_name or display_name).strip() if is_pilot else "",
        "bib": (bib or "").strip() if is_pilot else "",
        # participant league-registration defaults (glider/class/contact); empty for organizers
        "glider": (glider or "").strip() if is_pilot else "",
        "glider_class": (glider_class or "").strip() if is_pilot else "",
        "contact": (contact or "").strip() if is_pilot else "",
        "created": _now(),
        "last_login": None,
    }
    _save(user)
    idx[email] = user["uid"]
    _save_index(idx)
    return user


def update_user(uid: str, fields: dict) -> dict | None:
    user = get_user(uid)
    if user is None:
        return None
    for k in ("display_name", "pilot_name", "bib", "glider", "glider_class", "contact"):
        if k in fields:
            user[k] = (fields[k] or "").strip()
    if "last_login" in fields:
        user["last_login"] = fields["last_login"]
    if fields.get("password"):
        user["password_hash"] = auth.hash_password(fields["password"])
    _save(user)
    return user


def verify_login(email: str, password: str) -> dict | None:
    """Return the user on a correct email+password, else None (no reason leak)."""
    user = get_user_by_email(email)
    if user is None:
        return None
    if not auth.verify_password(password, user.get("password_hash", "")):
        return None
    update_user(user["uid"], {"last_login": _now()})
    return user


def public(user: dict | None) -> dict | None:
    """Strip secrets for client responses."""
    if not user:
        return None
    return {
        "uid": user["uid"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
        "pilot_name": user.get("pilot_name", ""),
        "bib": user.get("bib", ""),
        "glider": user.get("glider", ""),
        "glider_class": user.get("glider_class", ""),
        "contact": user.get("contact", ""),
    }
