"""Tests for XCTrack .xctsk task import."""

import json

import pytest

from scoring.models import GoalType, StartDirection, TurnpointKind
from scoring.task import TaskParseError, hms_to_seconds, parse_xctsk

XCTSK = json.dumps(
    {
        "taskType": "CLASSIC",
        "version": 1,
        "earthModel": "WGS84",
        "turnpoints": [
            {"type": "TAKEOFF", "radius": 400,
             "waypoint": {"name": "TO", "lat": 46.0, "lon": 8.0, "altSmoothed": 1200}},
            {"type": "SSS", "radius": 5000,
             "waypoint": {"name": "SSS", "lat": 46.1, "lon": 8.1, "altSmoothed": 1000}},
            {"radius": 2000,
             "waypoint": {"name": "T01", "lat": 46.3, "lon": 8.3, "altSmoothed": 900}},
            {"type": "ESS", "radius": 3000,
             "waypoint": {"name": "ESS", "lat": 46.5, "lon": 8.5, "altSmoothed": 800}},
            {"radius": 400,
             "waypoint": {"name": "GOAL", "lat": 46.55, "lon": 8.55, "altSmoothed": 780}},
        ],
        "sss": {"type": "RACE", "direction": "EXIT", "timeGates": ["12:30:00"]},
        "goal": {"type": "LINE", "deadline": "18:00:00"},
    }
)


def test_hms():
    assert hms_to_seconds("12:30:00") == 12 * 3600 + 30 * 60
    assert hms_to_seconds("01:02:03") == 3723
    assert hms_to_seconds("12:30") == 12 * 3600 + 30 * 60


def test_hms_utc_z_suffix():
    # XCTrack emits gates like "03:40:00Z" (UTC marker).
    assert hms_to_seconds("03:40:00Z") == 3 * 3600 + 40 * 60
    assert hms_to_seconds("14:00:00Z") == 14 * 3600


def test_hms_timezone_offset_dropped():
    assert hms_to_seconds("12:00:00+09:00") == 12 * 3600


def test_bad_time_raises():
    with pytest.raises(TaskParseError):
        hms_to_seconds("not:a:time")


def test_parse_basic():
    task = parse_xctsk(XCTSK)
    assert len(task.turnpoints) == 5
    assert task.start_time == 12 * 3600 + 30 * 60
    assert task.start_direction == StartDirection.EXIT
    assert task.earth_model == "wgs84"
    assert task.task_deadline == 18 * 3600


def test_special_turnpoint_kinds():
    task = parse_xctsk(XCTSK)
    kinds = [tp.kind for tp in task.turnpoints]
    assert kinds == [
        TurnpointKind.TAKEOFF,
        TurnpointKind.SSS,
        TurnpointKind.TURNPOINT,
        TurnpointKind.ESS,
        TurnpointKind.GOAL,
    ]
    assert task.sss.name == "SSS"
    assert task.ess.name == "ESS"
    assert task.goal.name == "GOAL"
    assert task.goal.goal_type == GoalType.LINE


def test_radius_and_coords():
    task = parse_xctsk(XCTSK)
    sss = task.sss
    assert sss.radius == 5000
    assert sss.lat == 46.1


def test_no_turnpoints_raises():
    with pytest.raises(TaskParseError):
        parse_xctsk(json.dumps({"turnpoints": [], "sss": {"timeGates": ["12:00:00"]}}))


def test_no_gate_raises():
    bad = json.dumps(
        {"turnpoints": [{"radius": 400, "waypoint": {"lat": 1, "lon": 2}}], "sss": {}}
    )
    with pytest.raises(TaskParseError):
        parse_xctsk(bad)
