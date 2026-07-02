"""FastAPI app — Phase 1 single-track analysis.

POST /analyze: multipart upload of an IGC tracklog + an XCTrack .xctsk task,
returns the parsed track, task geometry, optimized route and the analysis result
for map rendering. The static single-page UI is served at /.
"""

from __future__ import annotations

from pathlib import Path

from pathlib import PurePath

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scoring.igc import IGCParseError, parse_igc
from scoring.localtime import resolve_offset
from scoring.params import ScoringParams
from scoring.result import Competitor, score_competition
from scoring.task import TaskParseError, parse_xctsk
from scoring.validate import analyze

from . import auth, store
from . import users as users_store
from .serialize import analysis_to_dict, competition_to_dict, task_to_dict, track_to_dict

app = FastAPI(title="패러글라이딩 XC 경기 성적 계산기", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --- auth ------------------------------------------------------------------ #
def _set_session_cookie(response: Response, user: dict) -> None:
    token = auth.make_token(user["uid"], user["role"])
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=auth.TOKEN_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )


@app.post("/api/auth/signup")
def signup_endpoint(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(...),
    pilot_name: str = Form(""),
    bib: str = Form(""),
    glider: str = Form(""),
    contact: str = Form(""),
    glider_class: str = Form(""),
) -> dict:
    try:
        user = users_store.create_user(
            email, password, display_name, role, pilot_name, bib, glider, contact, glider_class
        )
    except users_store.UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_session_cookie(response, user)
    return {"user": users_store.public(user)}


@app.post("/api/auth/login")
def login_endpoint(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
) -> dict:
    user = users_store.verify_login(email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    _set_session_cookie(response, user)
    return {"user": users_store.public(user)}


@app.post("/api/auth/logout")
def logout_endpoint(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me_endpoint(skore_session: str | None = Cookie(default=None)) -> dict:
    user = auth.current_user(skore_session)
    return {"user": users_store.public(user)}


@app.patch("/api/me/profile")
def update_profile_endpoint(
    pilot_name: str = Form(None),
    bib: str = Form(None),
    display_name: str = Form(None),
    glider: str = Form(None),
    contact: str = Form(None),
    glider_class: str = Form(None),
    user: dict = Depends(auth.require_user),
) -> dict:
    """Let a participant fix the name/bib/glider/class/contact used for their profile."""
    fields: dict = {}
    for key, val in (
        ("pilot_name", pilot_name), ("bib", bib), ("display_name", display_name),
        ("glider", glider), ("contact", contact), ("glider_class", glider_class),
    ):
        if val is not None:
            fields[key] = val
    updated = users_store.update_user(user["uid"], fields)
    return {"user": users_store.public(updated)}


@app.get("/api/me/results")
def my_results_endpoint(user: dict = Depends(auth.require_user)) -> dict:
    """A participant's own results across every league, auto-matched by their
    pilot name / bib against each league's standings (reuses store matching)."""
    want_bib = (user.get("bib") or "").strip()
    want_name = store._norm(user.get("pilot_name") or user.get("display_name"))
    out: list[dict] = []
    for summary in store.list_leagues():
        league = store.get_league(summary["id"])
        if league is None:
            continue
        standings = store.league_standings(league)
        mine = None
        for row in standings:
            if want_bib and str(row.get("bib") or "").strip() == want_bib:
                mine = row
                break
            if want_name and store._norm(row.get("name")) == want_name:
                mine = row
                break
        if mine is None:
            continue
        meets = [
            {"id": m["id"], "name": m["name"], "points": mine.get("per_meet", {}).get(m["id"])}
            for m in league.get("meets", [])
        ]
        out.append(
            {
                "league_id": league["id"],
                "league_name": league["name"],
                "rank": mine["rank"],
                "total": mine["total"],
                "field_size": len(standings),
                "meets": meets,
            }
        )
    out.sort(key=lambda r: r["total"], reverse=True)
    return {"results": out, "profile": users_store.public(user)}


@app.get("/api/me/memberships")
def my_memberships_endpoint(user: dict = Depends(auth.require_participant)) -> dict:
    """Which leagues this participant has requested/joined, with approval status."""
    return {"memberships": store.memberships_for_user(user["uid"])}


@app.post("/api/analyze")
async def analyze_endpoint(
    igc: UploadFile = File(..., description="IGC tracklog"),
    task: UploadFile = File(..., description="XCTrack .xctsk task"),
) -> dict:
    igc_text = (await igc.read()).decode("latin-1")
    task_text = (await task.read()).decode("utf-8")

    try:
        track = parse_igc(igc_text)
    except IGCParseError as exc:
        raise HTTPException(status_code=422, detail=f"IGC parse error: {exc}") from exc
    try:
        task_obj = parse_xctsk(task_text)
    except TaskParseError as exc:
        raise HTTPException(status_code=422, detail=f"Task parse error: {exc}") from exc

    try:
        result = analyze(track, task_obj)
    except Exception as exc:  # surface the real reason instead of a bare 500
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    utc_offset, tz_label = resolve_offset(track, task_obj)
    return {
        "track": track_to_dict(track),
        "task": task_to_dict(task_obj),
        "analysis": analysis_to_dict(result),
        "meta": {"utc_offset": utc_offset, "tz_label": tz_label},
    }


async def _score_batch(
    igcs: list[UploadFile], task_obj, params: ScoringParams, num_present: int
) -> dict:
    """Parse a batch of IGCs against a task and score the field."""
    competitors: list[Competitor] = []
    errors: list[dict] = []
    tz_offset, tz_label = 0, "UTC"
    for f in igcs:
        stem = PurePath(f.filename or "track").stem
        text = (await f.read()).decode("latin-1")
        try:
            track = parse_igc(text)
            analysis = analyze(track, task_obj)
        except Exception as exc:  # one bad file shouldn't kill the batch
            errors.append({"file": f.filename, "error": str(exc)})
            continue
        if not competitors:  # take timezone from the first good track
            tz_offset, tz_label = resolve_offset(track, task_obj)
        bib = (track.raw_headers.get("FCID") or "").strip() or None
        competitors.append(
            Competitor(
                pilot_id=stem,
                name=track.pilot_name or stem,
                analysis=analysis,
                bib=bib,
                glider=track.glider,
            )
        )

    if not competitors:
        raise HTTPException(status_code=422, detail="No valid IGC tracks could be scored")

    result = score_competition(competitors, params, num_present=num_present or None)
    payload = competition_to_dict(result)
    payload["errors"] = errors
    payload["meta"] = {"utc_offset": tz_offset, "tz_label": tz_label}
    return payload


async def _parse_task(task: UploadFile):
    task_text = (await task.read()).decode("utf-8")
    try:
        return parse_xctsk(task_text)
    except TaskParseError as exc:
        raise HTTPException(status_code=422, detail=f"Task parse error: {exc}") from exc


@app.post("/api/score")
async def score_endpoint(
    igcs: list[UploadFile] = File(..., description="Pilot IGC tracklogs"),
    task: UploadFile = File(..., description="XCTrack .xctsk task"),
    nominal_distance: float = Form(30_000),
    nominal_time: float = Form(3_600),
    nominal_launch: float = Form(0.0),
    num_present: int = Form(0),
    leading_points: bool = Form(True),
) -> dict:
    """Ad-hoc single-task scoring (not persisted)."""
    task_obj = await _parse_task(task)
    params = ScoringParams(
        nominal_distance=nominal_distance,
        nominal_time=nominal_time,
        nominal_launch=nominal_launch,
        leading_points=leading_points,
    )
    payload = await _score_batch(igcs, task_obj, params, num_present)
    payload["task"] = task_to_dict(task_obj)
    return payload


# --- leagues (persisted, 3-tier: league → meet → task) --------------------- #
def _params_from_dict(d: dict) -> ScoringParams:
    return ScoringParams(
        nominal_distance=d.get("nominal_distance", 30_000),
        nominal_time=d.get("nominal_time", 5_400),
        nominal_launch=d.get("nominal_launch", 0.0),
        nominal_goal=d.get("nominal_goal", 0.25),
        min_distance=d.get("min_distance", 7_000),
        leading_time_ratio=d.get("leading_time_ratio", 0.26),
        leading_points=d.get("leading_points", True),
    )


def _params_dict(
    nominal_distance: float, nominal_time: float, nominal_launch: float,
    nominal_goal: float, min_distance: float, leading_time_ratio: float, leading_points: bool,
) -> dict:
    return {
        "nominal_distance": nominal_distance,
        "nominal_time": nominal_time,
        "nominal_launch": nominal_launch,
        "nominal_goal": nominal_goal,
        "min_distance": min_distance,
        "leading_time_ratio": leading_time_ratio,
        "leading_points": leading_points,
    }


def _require_league(league_id: str) -> dict:
    league = store.get_league(league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    return league


@app.post("/api/leagues")
async def create_league_endpoint(
    name: str = Form(...),
    nominal_distance: float = Form(30_000),
    nominal_time: float = Form(5_400),
    nominal_launch: float = Form(0.0),
    nominal_goal: float = Form(0.25),
    min_distance: float = Form(7_000),
    leading_time_ratio: float = Form(0.26),
    leading_points: bool = Form(True),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    params = _params_dict(nominal_distance, nominal_time, nominal_launch, nominal_goal,
                          min_distance, leading_time_ratio, leading_points)
    return store.create_league(name, params, owner_id=user["uid"])


@app.get("/api/leagues")
def list_leagues_endpoint(
    mine: int = 0,
    skore_session: str | None = Cookie(default=None),
) -> dict:
    """List leagues. With ``?mine=1`` returns only the caller's owned leagues
    (organizer dashboard). Each summary carries an ``owned`` flag for the UI."""
    user = auth.current_user(skore_session)
    uid = user["uid"] if user else None
    leagues = store.list_leagues()
    for lg in leagues:
        lg["owned"] = bool(uid and lg.get("owner_id") == uid)
    if mine:
        leagues = [lg for lg in leagues if lg["owned"]]
    return {"leagues": leagues}


@app.get("/api/leagues/{league_id}")
def get_league_endpoint(
    league_id: str,
    skore_session: str | None = Cookie(default=None),
) -> dict:
    league = _require_league(league_id)
    user = auth.current_user(skore_session)
    # Roster is readable by anyone, but ``contact`` is private — only the owner's
    # registrations endpoint exposes it. Strip it here, and hide pending/rejected
    # self-registrations from this public view (they belong on the roster page).
    roster = [
        {k: v for k, v in pl.items() if k != "contact"}
        for pl in league.get("roster", [])
        if store._is_approved(pl)
    ]
    return {
        "id": league["id"],
        "name": league["name"],
        "created": league.get("created"),
        "owner_id": league.get("owner_id"),
        "owned": bool(user and league.get("owner_id") == user["uid"]),
        "params": league["params"],
        "roster": roster,
        "meets": store.meet_summaries(league),
        "standings": store.league_standings(league),
    }


@app.post("/api/leagues/{league_id}/claim")
def claim_league_endpoint(
    league_id: str,
    user: dict = Depends(auth.require_organizer),
) -> dict:
    """Let an organizer take ownership of an *ownerless* league (e.g. a league
    created before authentication existed). Already-owned leagues are rejected."""
    league = _require_league(league_id)
    if league.get("owner_id") is not None:
        raise HTTPException(status_code=403, detail="이미 소유자가 있는 리그입니다.")
    league["owner_id"] = user["uid"]
    store._save(league)
    return {"claimed": league_id, "owner_id": user["uid"]}


@app.delete("/api/leagues/{league_id}")
def delete_league_endpoint(
    league_id: str,
    user: dict = Depends(auth.require_organizer),
) -> dict:
    auth.require_owner(league_id, user)
    store.delete_league(league_id)
    return {"deleted": league_id}


# --- meets (차전) ----------------------------------------------------------- #
@app.post("/api/leagues/{league_id}/meets")
async def create_meet_endpoint(
    league_id: str,
    name: str = Form(""),
    nominal_distance: float = Form(None),
    nominal_time: float = Form(None),
    nominal_launch: float = Form(None),
    nominal_goal: float = Form(None),
    min_distance: float = Form(None),
    leading_time_ratio: float = Form(None),
    leading_points: bool = Form(None),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    league = auth.require_owner(league_id, user)
    base = dict(league.get("params", {}))
    # only override fields the caller actually supplied; rest inherit league defaults
    overrides = {
        "nominal_distance": nominal_distance, "nominal_time": nominal_time,
        "nominal_launch": nominal_launch, "nominal_goal": nominal_goal,
        "min_distance": min_distance, "leading_time_ratio": leading_time_ratio,
        "leading_points": leading_points,
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    meet = store.add_meet(league_id, name, base)
    return {"meet": meet}


@app.get("/api/leagues/{league_id}/meets/{meet_id}")
def get_meet_endpoint(league_id: str, meet_id: str) -> dict:
    league = _require_league(league_id)
    meet = store.get_meet(league, meet_id)
    if meet is None:
        raise HTTPException(status_code=404, detail="Meet not found")
    return {
        "id": meet["id"],
        "name": meet["name"],
        "league_id": league["id"],
        "league_name": league["name"],
        "created": meet.get("created"),
        "params": meet.get("params", {}),
        "tasks": store.task_summaries(meet),
        "standings": store.meet_standings(league, meet),
    }


@app.delete("/api/leagues/{league_id}/meets/{meet_id}")
def delete_meet_endpoint(
    league_id: str, meet_id: str, user: dict = Depends(auth.require_organizer)
) -> dict:
    auth.require_owner(league_id, user)
    if not store.delete_meet(league_id, meet_id):
        raise HTTPException(status_code=404, detail="Meet not found")
    return {"deleted": meet_id}


# --- tasks (일차 타스크) ---------------------------------------------------- #
@app.post("/api/leagues/{league_id}/meets/{meet_id}/tasks")
async def add_task_endpoint(
    league_id: str,
    meet_id: str,
    igcs: list[UploadFile] = File(...),
    task: UploadFile = File(...),
    task_name: str = Form(""),
    num_present: int = Form(0),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    league = auth.require_owner(league_id, user)
    meet = store.get_meet(league, meet_id)
    if meet is None:
        raise HTTPException(status_code=404, detail="Meet not found")
    task_obj = await _parse_task(task)
    params = _params_from_dict(meet.get("params", {}))
    result = await _score_batch(igcs, task_obj, params, num_present)
    result["task"] = task_to_dict(task_obj)
    saved = store.add_task(league_id, meet_id, task_name, result)
    return {"task": saved}


@app.get("/api/leagues/{league_id}/meets/{meet_id}/tasks/{task_id}")
def get_task_endpoint(league_id: str, meet_id: str, task_id: str) -> dict:
    league = _require_league(league_id)
    task = store.get_task(league, meet_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.delete("/api/leagues/{league_id}/meets/{meet_id}/tasks/{task_id}")
def delete_task_endpoint(
    league_id: str, meet_id: str, task_id: str, user: dict = Depends(auth.require_organizer)
) -> dict:
    auth.require_owner(league_id, user)
    if not store.delete_task(league_id, meet_id, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": task_id}


# --- roster (league-level: bib / name / glider / aliases) ------------------ #
@app.post("/api/leagues/{league_id}/roster")
async def add_pilot_endpoint(
    league_id: str,
    bib: str = Form(""),
    name: str = Form(""),
    glider: str = Form(""),
    glider_class: str = Form(""),
    aliases: str = Form(""),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    auth.require_owner(league_id, user)
    alias_list = list((aliases or "").split(","))
    pilot = store.add_pilot(league_id, bib, name, glider, alias_list, glider_class=glider_class)
    if pilot is None:
        raise HTTPException(status_code=404, detail="League not found")
    return {"pilot": pilot}


@app.patch("/api/leagues/{league_id}/roster/{pid}")
async def update_pilot_endpoint(
    league_id: str,
    pid: str,
    bib: str = Form(None),
    name: str = Form(None),
    glider: str = Form(None),
    glider_class: str = Form(None),
    contact: str = Form(None),
    aliases: str = Form(None),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    auth.require_owner(league_id, user)
    fields: dict = {}
    if bib is not None:
        fields["bib"] = bib
    if name is not None:
        fields["name"] = name
    if glider is not None:
        fields["glider"] = glider
    if glider_class is not None:
        fields["glider_class"] = glider_class
    if contact is not None:
        fields["contact"] = contact
    if aliases is not None:
        fields["aliases"] = aliases.split(",")
    pilot = store.update_pilot(league_id, pid, fields)
    if pilot is None:
        raise HTTPException(status_code=404, detail="Pilot or league not found")
    return {"pilot": pilot}


@app.delete("/api/leagues/{league_id}/roster/{pid}")
def delete_pilot_endpoint(
    league_id: str, pid: str, user: dict = Depends(auth.require_organizer)
) -> dict:
    auth.require_owner(league_id, user)
    if not store.delete_pilot(league_id, pid):
        raise HTTPException(status_code=404, detail="Pilot or league not found")
    return {"deleted": pid}


@app.post("/api/leagues/{league_id}/roster/import")
async def import_roster_endpoint(
    league_id: str,
    igcs: list[UploadFile] = File(..., description="IGC files to extract pilots from"),
    user: dict = Depends(auth.require_organizer),
) -> dict:
    """Build/extend the league roster from IGC headers (bib=HFCID, name=HFPLT, glider).

    No scoring — a fast way to seed a roster from a tracker dump. Existing pilots
    (same bib, or same normalized name) are skipped.
    """
    auth.require_owner(league_id, user)
    pilots: list[dict] = []
    errors: list[dict] = []
    for f in igcs:
        text = (await f.read()).decode("latin-1")
        try:
            track = parse_igc(text)
        except IGCParseError as exc:
            errors.append({"file": f.filename, "error": str(exc)})
            continue
        pilots.append(
            {
                "bib": (track.raw_headers.get("FCID") or "").strip(),
                "name": track.pilot_name or "",
                "glider": track.glider or "",
            }
        )
    res = store.import_pilots(league_id, pilots)
    return {**res, "errors": errors, "roster": store.get_league(league_id).get("roster", [])}


# --- league membership (participant self-registration → organizer approval) - #
@app.post("/api/leagues/{league_id}/register")
def register_for_league_endpoint(
    league_id: str,
    user: dict = Depends(auth.require_participant),
) -> dict:
    """A participant requests to join a league. Uses their saved profile
    (name/bib/glider/contact) to create a *pending* roster entry."""
    _require_league(league_id)
    pilot = store.request_membership(
        league_id,
        uid=user["uid"],
        name=(user.get("pilot_name") or user.get("display_name") or "").strip(),
        bib=user.get("bib", ""),
        glider=user.get("glider", ""),
        contact=user.get("contact", ""),
        glider_class=user.get("glider_class", ""),
    )
    if pilot is None:
        raise HTTPException(status_code=409, detail="이미 이 리그에 신청했거나 등록된 선수입니다.")
    return {"registration": pilot}


def _registration_view(pl: dict) -> dict:
    """Enrich a roster entry with the linked account's email for the owner view."""
    email = None
    if pl.get("uid"):
        acct = users_store.get_user(pl["uid"])
        email = acct.get("email") if acct else None
    return {**pl, "account_email": email}


@app.get("/api/leagues/{league_id}/registrations")
def list_registrations_endpoint(
    league_id: str,
    user: dict = Depends(auth.require_organizer),
) -> dict:
    """Owner-only full roster incl. private contact + account email + status.
    Backs the organizer's dedicated 등록 선수 명단 page."""
    league = auth.require_owner(league_id, user)
    return {"registrations": [_registration_view(pl) for pl in league.get("roster", [])]}


@app.post("/api/leagues/{league_id}/registrations/{pid}/approve")
def approve_registration_endpoint(
    league_id: str, pid: str, user: dict = Depends(auth.require_organizer)
) -> dict:
    auth.require_owner(league_id, user)
    pl = store.set_pilot_status(league_id, pid, "approved")
    if pl is None:
        raise HTTPException(status_code=404, detail="선수 신청을 찾을 수 없습니다.")
    return {"registration": _registration_view(pl)}


@app.post("/api/leagues/{league_id}/registrations/{pid}/reject")
def reject_registration_endpoint(
    league_id: str, pid: str, user: dict = Depends(auth.require_organizer)
) -> dict:
    auth.require_owner(league_id, user)
    pl = store.set_pilot_status(league_id, pid, "rejected")
    if pl is None:
        raise HTTPException(status_code=404, detail="선수 신청을 찾을 수 없습니다.")
    return {"registration": _registration_view(pl)}


# --- static UI -------------------------------------------------------------- #
if WEB_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "landing.html")

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
