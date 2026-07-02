"""Task construction and import.

Primary import format is XCTrack ``.xctsk`` (JSON), the de-facto exchange format
for competition tasks (see DECISIONS D4). A manual dict builder is also provided
for the API/UI form.

XCTrack task shape (abridged)::

    {
      "taskType": "CLASSIC",
      "version": 1,
      "earthModel": "WGS84",
      "turnpoints": [
        {"type": "TAKEOFF"|"SSS"|"ESS"|<absent>,
         "radius": 400,
         "waypoint": {"name": "T01", "lat": 46.1, "lon": 8.2, "altSmoothed": 1200}},
        ...
      ],
      "sss":  {"type": "RACE"|"ELAPSED-TIME", "direction": "EXIT"|"ENTER",
               "timeGates": ["12:00:00"]},
      "goal": {"type": "CYLINDER"|"LINE", "deadline": "18:00:00"}
    }

The last turnpoint is always the goal. Only special turnpoints carry an explicit
``type``; regular ones omit it. When a task has no separate ESS turnpoint, the
goal doubles as the ESS for timing — that fallback lives in ``validate.py``.
"""

from __future__ import annotations

import json

from .models import (
    GoalType,
    StartDirection,
    Task,
    TaskType,
    Turnpoint,
    TurnpointKind,
)


class TaskParseError(ValueError):
    """Raised when a task definition cannot be parsed."""


def hms_to_seconds(value: str) -> int:
    """``"HH:MM:SS"`` (or ``"HH:MM"``) -> seconds since midnight.

    Tolerates a trailing ``Z`` (UTC marker, as emitted by XCTrack, e.g.
    ``"03:40:00Z"``) and a trailing timezone offset (``+09:00``), which is
    dropped — times are treated as UTC to match IGC B-record timestamps.
    """
    v = value.strip().upper().rstrip("Z").strip()
    # Drop a trailing timezone offset like "+09:00" / "-0930" if present.
    for sign in ("+", "-"):
        idx = v.find(sign, 1)
        if idx != -1:
            v = v[:idx]
            break
    parts = v.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError as exc:
        raise TaskParseError(f"Bad time value: {value!r}") from exc
    if len(nums) == 2:
        h, m, s = nums[0], nums[1], 0
    elif len(nums) == 3:
        h, m, s = nums
    else:
        raise TaskParseError(f"Bad time value: {value!r}")
    return h * 3600 + m * 60 + s


_TYPE_MAP = {
    "TAKEOFF": TurnpointKind.TAKEOFF,
    "SSS": TurnpointKind.SSS,
    "ESS": TurnpointKind.ESS,
}


def parse_xctsk(text: str) -> Task:
    """Parse an XCTrack ``.xctsk`` JSON string into a :class:`Task`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskParseError(f"Invalid JSON: {exc}") from exc

    raw_tps = data.get("turnpoints")
    if not raw_tps:
        raise TaskParseError("Task has no turnpoints")

    earth = "fai_sphere" if str(data.get("earthModel", "WGS84")).upper() == "FAI_SPHERE" else "wgs84"

    goal_block = data.get("goal") or {}
    goal_type = (
        GoalType.LINE if str(goal_block.get("type", "CYLINDER")).upper() == "LINE" else GoalType.CYLINDER
    )

    turnpoints: list[Turnpoint] = []
    last_idx = len(raw_tps) - 1
    for i, tp in enumerate(raw_tps):
        wp = tp.get("waypoint") or {}
        try:
            lat = float(wp["lat"])
            lon = float(wp["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskParseError(f"Turnpoint {i} missing lat/lon") from exc
        radius = float(tp.get("radius", 0))

        kind = _TYPE_MAP.get(str(tp.get("type", "")).upper(), TurnpointKind.TURNPOINT)
        gtype = GoalType.CYLINDER
        if i == last_idx:
            kind = TurnpointKind.GOAL  # last turnpoint is always the goal
            gtype = goal_type

        turnpoints.append(
            Turnpoint(
                lat=lat,
                lon=lon,
                radius=radius,
                kind=kind,
                name=str(wp.get("name", "") or ""),
                altitude=float(wp.get("altSmoothed", 0) or 0),
                goal_type=gtype,
            )
        )

    sss = data.get("sss") or {}
    gates = sss.get("timeGates") or []
    if not gates:
        raise TaskParseError("Task has no SSS time gate (start time)")
    start_time = hms_to_seconds(gates[0])

    direction = (
        StartDirection.ENTER if str(sss.get("direction", "EXIT")).upper() == "ENTER" else StartDirection.EXIT
    )
    ttype = (
        TaskType.ELAPSED_TIME
        if str(sss.get("type", "RACE")).upper() in ("ELAPSED-TIME", "ELAPSED_TIME")
        else TaskType.RACE_TO_GOAL
    )

    deadline = goal_block.get("deadline")
    task_deadline = hms_to_seconds(deadline) if deadline else None

    return Task(
        turnpoints=turnpoints,
        start_time=start_time,
        task_type=ttype,
        start_direction=direction,
        task_deadline=task_deadline,
        earth_model=earth,
        name=str(data.get("taskType", "") or ""),
    )


def parse_xctsk_file(path: str) -> Task:
    with open(path, encoding="utf-8") as fh:
        return parse_xctsk(fh.read())
