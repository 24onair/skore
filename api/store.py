"""League store — Postgres (Supabase) backed (3-tier: league → meet → task).

A **league** (리그/시즌) accumulates **meets** (차전), each of which accumulates
**tasks** (일차 타스크). Each task is scored once and the per-pilot result is
persisted as a JSONB snapshot.

  * meet standings  = sum of a pilot's task totals within that meet
  * league standings = sum of a pilot's meet totals across the whole season

The **roster** lives at the *league* level; identity is resolved against it **at
read time** (bib → normalized name → aliases), so editing the roster retroactively
consolidates results across the season without rescoring.

Persistence is normalized Postgres tables (``leagues``/``meets``/``tasks``/
``roster``); the read side assembles a plain league **dict** and the pure scoring
functions below operate on that dict exactly as before (unchanged, verified).
"""

from __future__ import annotations

from datetime import datetime

from .db import Jsonb, connect


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _iso(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if isinstance(dt, datetime) else dt


def _sid(v) -> str | None:
    return str(v) if v is not None else None


# --------------------------------------------------------------------------- #
# League CRUD
# --------------------------------------------------------------------------- #
def create_league(name: str, params: dict, owner_id: str | None = None) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into leagues (name, params, owner_id) values (%s, %s, %s::uuid) returning id",
            (name or "Untitled league", Jsonb(params or {}), owner_id),
        )
        new_id = cur.fetchone()["id"]
    return get_league(str(new_id))


def list_leagues() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select l.id, l.name, l.created, l.owner_id,
                   (select count(*) from meets  m where m.league_id = l.id) as meet_count,
                   (select count(*) from roster r where r.league_id = l.id) as roster_size
            from leagues l
            order by l.created desc
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "created": _iso(r["created"]),
            "owner_id": _sid(r["owner_id"]),
            "meet_count": r["meet_count"],
            "roster_size": r["roster_size"],
        }
        for r in rows
    ]


def get_league(league_id: str) -> dict | None:
    """Assemble the full league dict (params + roster + meets + tasks) that the pure
    standings functions expect. Returns None if the league doesn't exist."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, owner_id, name, params, created from leagues where id = %s::uuid",
            (league_id,),
        )
        lg = cur.fetchone()
        if lg is None:
            return None
        cur.execute(
            "select id, name, params, created from meets where league_id = %s::uuid order by ord, created",
            (league_id,),
        )
        meets = cur.fetchall()
        cur.execute(
            """
            select t.id, t.meet_id, t.name, t.result, t.created
            from tasks t join meets m on m.id = t.meet_id
            where m.league_id = %s::uuid
            order by t.ord, t.created
            """,
            (league_id,),
        )
        tasks = cur.fetchall()
        cur.execute(
            """
            select id, uid, bib, name, glider, glider_class, aliases, contact, source, status
            from roster where league_id = %s::uuid order by created
            """,
            (league_id,),
        )
        roster = cur.fetchall()

    tasks_by_meet: dict[str, list] = {}
    for t in tasks:
        tasks_by_meet.setdefault(str(t["meet_id"]), []).append(
            {"id": str(t["id"]), "name": t["name"], "created": _iso(t["created"]), "result": t["result"] or {}}
        )
    return {
        "id": str(lg["id"]),
        "name": lg["name"],
        "created": _iso(lg["created"]),
        "owner_id": _sid(lg["owner_id"]),
        "params": lg["params"] or {},
        "roster": [
            {
                "pid": str(pl["id"]),
                "uid": _sid(pl["uid"]),
                "bib": pl["bib"],
                "name": pl["name"],
                "glider": pl["glider"],
                "glider_class": pl["glider_class"],
                "aliases": pl["aliases"] or [],
                "contact": pl["contact"],
                "source": pl["source"],
                "status": pl["status"],
            }
            for pl in roster
        ],
        "meets": [
            {
                "id": str(m["id"]),
                "name": m["name"],
                "created": _iso(m["created"]),
                "params": m["params"] or {},
                "tasks": tasks_by_meet.get(str(m["id"]), []),
            }
            for m in meets
        ],
    }


def delete_league(league_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("delete from leagues where id = %s::uuid", (league_id,))
        return cur.rowcount > 0


def set_league_owner(league_id: str, owner_id: str) -> bool:
    """Claim an ownerless league (used by POST /claim)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "update leagues set owner_id = %s::uuid where id = %s::uuid", (owner_id, league_id)
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Meets (차전)
# --------------------------------------------------------------------------- #
def add_meet(league_id: str, name: str, params: dict | None) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select params from leagues where id = %s::uuid", (league_id,))
        lg = cur.fetchone()
        if lg is None:
            return None
        cur.execute("select count(*) as n from meets where league_id = %s::uuid", (league_id,))
        n = cur.fetchone()["n"]
        cur.execute(
            "insert into meets (league_id, name, params, ord) values (%s::uuid, %s, %s, %s) "
            "returning id, name, params, created",
            (league_id, name or f"{n + 1}차전", Jsonb(params or dict(lg["params"] or {})), n),
        )
        m = cur.fetchone()
    return {"id": str(m["id"]), "name": m["name"], "created": _iso(m["created"]),
            "params": m["params"] or {}, "tasks": []}


def get_meet(league: dict, meet_id: str) -> dict | None:
    return next((m for m in league.get("meets", []) if m["id"] == meet_id), None)


def delete_meet(league_id: str, meet_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from meets where id = %s::uuid and league_id = %s::uuid", (meet_id, league_id)
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Tasks (일차 타스크)
# --------------------------------------------------------------------------- #
def add_task(league_id: str, meet_id: str, task_name: str, result: dict) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from meets where id = %s::uuid and league_id = %s::uuid", (meet_id, league_id)
        )
        if cur.fetchone() is None:
            return None
        cur.execute("select count(*) as n from tasks where meet_id = %s::uuid", (meet_id,))
        n = cur.fetchone()["n"]
        cur.execute(
            "insert into tasks (meet_id, name, result, ord) values (%s::uuid, %s, %s, %s) "
            "returning id, name, result, created",
            (meet_id, task_name or f"{n + 1}일차", Jsonb(result), n),
        )
        t = cur.fetchone()
    return {"id": str(t["id"]), "name": t["name"], "created": _iso(t["created"]), "result": t["result"] or {}}


def get_task(league: dict, meet_id: str, task_id: str) -> dict | None:
    meet = get_meet(league, meet_id)
    if meet is None:
        return None
    return next((t for t in meet.get("tasks", []) if t["id"] == task_id), None)


def delete_task(league_id: str, meet_id: str, task_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            delete from tasks t using meets m
            where t.id = %s::uuid and t.meet_id = m.id
              and m.id = %s::uuid and m.league_id = %s::uuid
            """,
            (task_id, meet_id, league_id),
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Roster (league-level: bib / name / glider / class / aliases)
# --------------------------------------------------------------------------- #
def _norm(s: str | None) -> str:
    """Normalize a name for matching: drop all whitespace, casefold."""
    return "".join((s or "").split()).casefold()


def _row_to_pilot(r: dict) -> dict:
    return {
        "pid": str(r["id"]),
        "uid": _sid(r["uid"]),
        "bib": r["bib"],
        "name": r["name"],
        "glider": r["glider"],
        "glider_class": r["glider_class"],
        "aliases": r["aliases"] or [],
        "contact": r["contact"],
        "source": r["source"],
        "status": r["status"],
    }


_ROSTER_COLS = "id, uid, bib, name, glider, glider_class, aliases, contact, source, status"


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
    alias_list = [a.strip() for a in (aliases or []) if a.strip()]
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select 1 from leagues where id = %s::uuid", (league_id,))
        if cur.fetchone() is None:
            return None
        cur.execute(
            f"""
            insert into roster (league_id, uid, bib, name, glider, glider_class, aliases, contact, source, status)
            values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            returning {_ROSTER_COLS}
            """,
            (league_id, uid, (bib or "").strip(), (name or "").strip(), (glider or "").strip(),
             (glider_class or "").strip(), Jsonb(alias_list), (contact or "").strip(), source, status),
        )
        return _row_to_pilot(cur.fetchone())


def update_pilot(league_id: str, pid: str, fields: dict) -> dict | None:
    sets, vals = [], []
    for k in ("bib", "name", "glider", "glider_class", "contact"):
        if k in fields:
            sets.append(f"{k} = %s")
            vals.append((fields[k] or "").strip())
    if "aliases" in fields:
        sets.append("aliases = %s")
        vals.append(Jsonb([a.strip() for a in (fields["aliases"] or []) if a.strip()]))
    if not sets:
        return _get_pilot(league_id, pid)
    vals += [pid, league_id]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update roster set {', '.join(sets)} where id = %s::uuid and league_id = %s::uuid "
            f"returning {_ROSTER_COLS}",
            vals,
        )
        row = cur.fetchone()
    return _row_to_pilot(row) if row else None


def _get_pilot(league_id: str, pid: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"select {_ROSTER_COLS} from roster where id = %s::uuid and league_id = %s::uuid",
            (pid, league_id),
        )
        row = cur.fetchone()
    return _row_to_pilot(row) if row else None


def delete_pilot(league_id: str, pid: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from roster where id = %s::uuid and league_id = %s::uuid", (pid, league_id)
        )
        return cur.rowcount > 0


def import_pilots(league_id: str, pilots: list[dict]) -> dict | None:
    """Bulk-add pilots (from IGC headers), de-duplicating against the existing roster
    by bib then by normalized name. Returns counts."""
    league = get_league(league_id)
    if league is None:
        return None
    bib_idx, name_idx = _index(league)
    seen_names = set(name_idx)
    seen_bibs = set(bib_idx)
    added = 0
    with connect() as conn, conn.cursor() as cur:
        for p in pilots:
            bib = (p.get("bib") or "").strip()
            name = (p.get("name") or "").strip()
            glider = (p.get("glider") or "").strip()
            if bib and bib in seen_bibs:
                continue
            if name and _norm(name) in seen_names:
                continue
            cur.execute(
                """
                insert into roster (league_id, bib, name, glider, source, status)
                values (%s::uuid, %s, %s, %s, 'igc', 'approved')
                """,
                (league_id, bib, name, glider),
            )
            if bib:
                seen_bibs.add(bib)
            if name:
                seen_names.add(_norm(name))
            added += 1
        cur.execute("select count(*) as n from roster where league_id = %s::uuid", (league_id,))
        size = cur.fetchone()["n"]
    return {"added": added, "roster_size": size}


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
    """Create a *pending* self-registration. Returns the new roster entry, or None if
    the league is missing / the user already has an entry in this league."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select 1 from leagues where id = %s::uuid", (league_id,))
        if cur.fetchone() is None:
            return None
        cur.execute(
            "select 1 from roster where league_id = %s::uuid and uid = %s::uuid", (league_id, uid)
        )
        if cur.fetchone() is not None:
            return None  # already registered / requested
    return add_pilot(
        league_id, bib, name, glider, aliases=None,
        uid=uid, contact=contact, glider_class=glider_class, source="self", status="pending",
    )


def set_pilot_status(league_id: str, pid: str, status: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"update roster set status = %s where id = %s::uuid and league_id = %s::uuid "
            f"returning {_ROSTER_COLS}",
            (status, pid, league_id),
        )
        row = cur.fetchone()
    return _row_to_pilot(row) if row else None


def memberships_for_user(uid: str) -> list[dict]:
    """Every league this participant has requested/joined, with status (for the
    participant dashboard)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select r.league_id, l.name as league_name, r.status, r.id as pid
            from roster r join leagues l on l.id = r.league_id
            where r.uid = %s::uuid
            order by l.created desc
            """,
            (uid,),
        )
        rows = cur.fetchall()
    return [
        {"league_id": str(r["league_id"]), "league_name": r["league_name"],
         "status": r["status"], "pid": str(r["pid"])}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Identity resolution + standings  (PURE — operate on the assembled dict)
# --------------------------------------------------------------------------- #
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
