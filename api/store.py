"""File-based league store (3-tier: league → meet → task).

A **league** (리그/시즌) accumulates **meets** (차전), each of which accumulates
**tasks** (일차 타스크). Each task is scored once with its meet's scoring
parameters and the per-pilot result is persisted.

  * meet standings  = sum of a pilot's task totals within that meet
  * league standings = sum of a pilot's meet totals across the whole season

The **roster** (registered pilots: bib/name/glider/aliases) lives at the *league*
level — identity is shared across the season, so the same person is consolidated
across every meet and task regardless of how each instrument spelled their name.

Identity is resolved against the roster **at read time**: task results store the
raw bib/name/glider read from each IGC, and standings resolve them on read, so
editing the roster (adding a pilot, fixing a typo, adding an alias) retroactively
consolidates results across the season without rescoring.

Storage: one JSON file per league under ``data/leagues/``. A database can replace
this later without touching the API surface.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "leagues"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _path(league_id: str) -> Path:
    return DATA_DIR / f"{league_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# League CRUD
# --------------------------------------------------------------------------- #
def create_league(name: str, params: dict, owner_id: str | None = None) -> dict:
    _ensure_dir()
    league = {
        "id": _id(),
        "name": name or "Untitled league",
        "created": _now(),
        "owner_id": owner_id,      # uid of the organizer who owns this league
        "params": params,          # default scoring params; seeds each new meet
        "roster": [],
        "meets": [],
    }
    _save(league)
    return league


def list_leagues() -> list[dict]:
    _ensure_dir()
    out = []
    for fp in sorted(DATA_DIR.glob("*.json")):
        try:
            lg = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out.append(
            {
                "id": lg["id"],
                "name": lg["name"],
                "created": lg.get("created"),
                "owner_id": lg.get("owner_id"),
                "meet_count": len(lg.get("meets", [])),
                "roster_size": len(lg.get("roster", [])),
            }
        )
    out.sort(key=lambda c: c.get("created") or "", reverse=True)
    return out


def get_league(league_id: str) -> dict | None:
    fp = _path(league_id)
    if not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def delete_league(league_id: str) -> bool:
    fp = _path(league_id)
    if not fp.is_file():
        return False
    fp.unlink()
    return True


def _save(league: dict) -> None:
    _ensure_dir()
    _path(league["id"]).write_text(json.dumps(league, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Meets (차전)
# --------------------------------------------------------------------------- #
def add_meet(league_id: str, name: str, params: dict | None) -> dict | None:
    league = get_league(league_id)
    if league is None:
        return None
    meet = {
        "id": _id(),
        "name": name or f"{len(league['meets']) + 1}차전",
        "created": _now(),
        "params": params or dict(league.get("params", {})),
        "tasks": [],
    }
    league["meets"].append(meet)
    _save(league)
    return meet


def get_meet(league: dict, meet_id: str) -> dict | None:
    return next((m for m in league.get("meets", []) if m["id"] == meet_id), None)


def delete_meet(league_id: str, meet_id: str) -> bool:
    league = get_league(league_id)
    if league is None:
        return False
    before = len(league["meets"])
    league["meets"] = [m for m in league["meets"] if m["id"] != meet_id]
    if len(league["meets"]) == before:
        return False
    _save(league)
    return True


# --------------------------------------------------------------------------- #
# Tasks (일차 타스크)
# --------------------------------------------------------------------------- #
def add_task(league_id: str, meet_id: str, task_name: str, result: dict) -> dict | None:
    league = get_league(league_id)
    if league is None:
        return None
    meet = get_meet(league, meet_id)
    if meet is None:
        return None
    task = {
        "id": _id(),
        "name": task_name or f"{len(meet['tasks']) + 1}일차",
        "created": _now(),
        "result": result,
    }
    meet["tasks"].append(task)
    _save(league)
    return task


def get_task(league: dict, meet_id: str, task_id: str) -> dict | None:
    meet = get_meet(league, meet_id)
    if meet is None:
        return None
    return next((t for t in meet.get("tasks", []) if t["id"] == task_id), None)


def delete_task(league_id: str, meet_id: str, task_id: str) -> bool:
    league = get_league(league_id)
    if league is None:
        return False
    meet = get_meet(league, meet_id)
    if meet is None:
        return False
    before = len(meet["tasks"])
    meet["tasks"] = [t for t in meet["tasks"] if t["id"] != task_id]
    if len(meet["tasks"]) == before:
        return False
    _save(league)
    return True


# --------------------------------------------------------------------------- #
# Roster (league-level: bib / name / glider / aliases)
# --------------------------------------------------------------------------- #
def _norm(s: str | None) -> str:
    """Normalize a name for matching: drop all whitespace, casefold."""
    return "".join((s or "").split()).casefold()


def add_pilot(
    league_id: str,
    bib: str,
    name: str,
    glider: str,
    aliases: list[str] | None = None,
    *,
    uid: str | None = None,
    contact: str = "",
    glider_class: str = "",
    source: str = "organizer",
    status: str = "approved",
) -> dict | None:
    league = get_league(league_id)
    if league is None:
        return None
    pilot = {
        "pid": _id(),
        "bib": (bib or "").strip(),
        "name": (name or "").strip(),
        "glider": (glider or "").strip(),
        "glider_class": (glider_class or "").strip(),   # EN class: CCC/D/C/B/A ("" = 미지정)
        "aliases": [a.strip() for a in (aliases or []) if a.strip()],
        "uid": uid,                    # linked participant account (None = organizer/igc)
        "contact": (contact or "").strip(),
        "source": source,             # organizer | igc | self
        "status": status,             # approved | pending | rejected
    }
    league.setdefault("roster", []).append(pilot)
    _save(league)
    return pilot


# --------------------------------------------------------------------------- #
# Membership (participant self-registration → organizer approval)
# --------------------------------------------------------------------------- #
def _is_approved(pilot: dict) -> bool:
    """A roster entry counts toward scoring/matching unless it is a pending or
    rejected self-registration. Legacy entries (no ``status``) are approved."""
    return pilot.get("status", "approved") == "approved"


def request_membership(
    league_id: str, uid: str, name: str, bib: str, glider: str, contact: str,
    glider_class: str = "",
) -> dict | None:
    """Create a *pending* self-registration for a participant. Returns the new
    roster entry, or ``None`` if the league is missing / the user already has an
    entry in this league (duplicate request)."""
    league = get_league(league_id)
    if league is None:
        return None
    for pl in league.get("roster", []):
        if pl.get("uid") == uid:
            return None  # already registered / requested
    return add_pilot(
        league_id, bib, name, glider, aliases=None,
        uid=uid, contact=contact, glider_class=glider_class, source="self", status="pending",
    )


def set_pilot_status(league_id: str, pid: str, status: str) -> dict | None:
    league = get_league(league_id)
    if league is None:
        return None
    for pl in league.get("roster", []):
        if pl["pid"] == pid:
            pl["status"] = status
            _save(league)
            return pl
    return None


def memberships_for_user(uid: str) -> list[dict]:
    """Every league this participant has requested/joined, with status.
    Used by the participant dashboard to show join state per league."""
    _ensure_dir()
    out: list[dict] = []
    for fp in sorted(DATA_DIR.glob("*.json")):
        try:
            lg = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for pl in lg.get("roster", []):
            if pl.get("uid") == uid:
                out.append(
                    {
                        "league_id": lg["id"],
                        "league_name": lg["name"],
                        "status": pl.get("status", "approved"),
                        "pid": pl["pid"],
                    }
                )
                break
    return out


def update_pilot(league_id: str, pid: str, fields: dict) -> dict | None:
    league = get_league(league_id)
    if league is None:
        return None
    for pl in league.get("roster", []):
        if pl["pid"] == pid:
            for k in ("bib", "name", "glider", "glider_class", "contact"):
                if k in fields:
                    pl[k] = (fields[k] or "").strip()
            if "aliases" in fields:
                pl["aliases"] = [a.strip() for a in (fields["aliases"] or []) if a.strip()]
            _save(league)
            return pl
    return None


def delete_pilot(league_id: str, pid: str) -> bool:
    league = get_league(league_id)
    if league is None:
        return False
    roster = league.get("roster", [])
    before = len(roster)
    league["roster"] = [pl for pl in roster if pl["pid"] != pid]
    if len(league["roster"]) == before:
        return False
    _save(league)
    return True


def import_pilots(league_id: str, pilots: list[dict]) -> dict | None:
    """Bulk-add pilots (e.g. extracted from IGC headers), de-duplicating against
    the existing roster by bib, then by normalized name. Returns counts."""
    league = get_league(league_id)
    if league is None:
        return None
    roster = league.setdefault("roster", [])
    bib_idx, name_idx = _index(league)
    added = 0
    for p in pilots:
        bib = (p.get("bib") or "").strip()
        name = (p.get("name") or "").strip()
        glider = (p.get("glider") or "").strip()
        if bib and bib in bib_idx:
            continue
        if name and _norm(name) in name_idx:
            continue
        new = {
            "pid": _id(), "bib": bib, "name": name, "glider": glider, "glider_class": "",
            "aliases": [], "uid": None, "contact": "", "source": "igc", "status": "approved",
        }
        roster.append(new)
        if bib:
            bib_idx[bib] = new["pid"]
        if name:
            name_idx[_norm(name)] = new["pid"]
        added += 1
    _save(league)
    return {"added": added, "roster_size": len(roster)}


def _index(league: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Build (bib -> pid, normalized-name -> pid) lookup tables from the roster.

    Only *approved* pilots are indexed — pending/rejected self-registrations do
    not resolve, so their tracks stay 미등록 and they are absent from standings
    until an organizer approves them."""
    bib_idx: dict[str, str] = {}
    name_idx: dict[str, str] = {}
    for pl in league.get("roster", []):
        if not _is_approved(pl):
            continue
        if pl.get("bib"):
            bib_idx[str(pl["bib"]).strip()] = pl["pid"]
        if pl.get("name"):
            name_idx[_norm(pl["name"])] = pl["pid"]
        for a in pl.get("aliases", []):
            name_idx[_norm(a)] = pl["pid"]
    return bib_idx, name_idx


def _match(row: dict, bib_idx: dict[str, str], name_idx: dict[str, str]) -> str | None:
    """Resolve a result row to a roster pid: bib first (authoritative), then name."""
    bib = str(row.get("bib") or "").strip()
    if bib and bib in bib_idx:
        return bib_idx[bib]
    return name_idx.get(_norm(row.get("name")))


def _resolve(row: dict, bib_idx, name_idx, roster) -> tuple[str, dict]:
    """Return (aggregation_key, identity dict) for one result row."""
    pid = _match(row, bib_idx, name_idx)
    if pid:
        pl = roster[pid]
        return pid, {
            "pid": pid, "name": pl["name"], "bib": pl.get("bib"),
            "glider": pl.get("glider"), "glider_class": pl.get("glider_class") or None,
            "registered": True,
        }
    key = "name::" + _norm(row.get("name"))
    return key, {
        "pid": None, "name": row.get("name") or "(이름없음)", "bib": row.get("bib"),
        "glider": row.get("glider"), "glider_class": None, "registered": False,
    }


def _rank(standings: list[dict]) -> list[dict]:
    """Sort by total descending and assign ranks (ties share a rank)."""
    standings.sort(key=lambda x: x["total"], reverse=True)
    prev_total = None
    prev_rank = 0
    for i, row in enumerate(standings, start=1):
        if prev_total is None or abs(row["total"] - prev_total) > 1e-9:
            row["rank"] = i
            prev_rank = i
            prev_total = row["total"]
        else:
            row["rank"] = prev_rank
    return standings


# --------------------------------------------------------------------------- #
# Standings
# --------------------------------------------------------------------------- #
def _meet_totals(meet: dict, bib_idx, name_idx, roster) -> dict[str, dict]:
    """Per-pilot totals within one meet, keyed by identity. ``per_task`` maps each
    task id to that pilot's points (best score if a pilot somehow appears twice)."""
    pilots: dict[str, dict] = {}
    for task in meet.get("tasks", []):
        tid = task["id"]
        for r in task["result"].get("results", []):
            key, ident = _resolve(r, bib_idx, name_idx, roster)
            p = pilots.setdefault(key, {**ident, "total": 0.0, "per_task": {}})
            pts = float(r.get("total", 0.0))
            p["per_task"][tid] = round(max(pts, p["per_task"].get(tid, 0.0)), 1)
            p["total"] = round(sum(p["per_task"].values()), 1)
    return pilots


def meet_standings(league: dict, meet: dict) -> list[dict]:
    """Ranked standings within a meet: sum of each pilot's task totals."""
    roster = {pl["pid"]: pl for pl in league.get("roster", [])}
    bib_idx, name_idx = _index(league)
    return _rank(list(_meet_totals(meet, bib_idx, name_idx, roster).values()))


def league_standings(league: dict) -> list[dict]:
    """Ranked season standings: sum of each pilot's meet totals across all meets.
    ``per_meet`` maps each meet id to that pilot's subtotal for the meet."""
    roster = {pl["pid"]: pl for pl in league.get("roster", [])}
    bib_idx, name_idx = _index(league)
    agg: dict[str, dict] = {}
    for meet in league.get("meets", []):
        mid = meet["id"]
        for key, p in _meet_totals(meet, bib_idx, name_idx, roster).items():
            a = agg.setdefault(
                key,
                {k: p[k] for k in ("pid", "name", "bib", "glider", "glider_class", "registered")}
                | {"total": 0.0, "per_meet": {}},
            )
            a["per_meet"][mid] = p["total"]
            a["total"] = round(sum(a["per_meet"].values()), 1)
            # a later meet may resolve to a registered identity the first didn't
            a["registered"] = a["registered"] or p["registered"]
    return _rank(list(agg.values()))


# --------------------------------------------------------------------------- #
# Summaries (lightweight, for list views)
# --------------------------------------------------------------------------- #
def meet_summaries(league: dict) -> list[dict]:
    out = []
    for m in league.get("meets", []):
        tasks = m.get("tasks", [])
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "created": m.get("created"),
                "params": m.get("params", {}),
                "task_count": len(tasks),
            }
        )
    return out


def task_summaries(meet: dict) -> list[dict]:
    out = []
    for t in meet.get("tasks", []):
        c = t["result"]
        dq = c.get("day_quality", {})
        out.append(
            {
                "id": t["id"],
                "name": t["name"],
                "created": t.get("created"),
                "task_distance_km": c.get("task_distance_km"),
                "num_flying": c.get("num_flying"),
                "num_in_goal": c.get("num_in_goal"),
                "day_quality": dq.get("quality"),
            }
        )
    return out
