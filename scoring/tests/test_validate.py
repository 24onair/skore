"""Tests for single-track validation against a task."""

import pytest

from scoring import geo
from scoring.models import Fix, StartDirection, Task, Track, Turnpoint, TurnpointKind
from scoring.validate import analyze

GATE = 43_200  # 12:00:00

# Task: SSS cylinder (r=1000, exit) at (46,8) -> goal cylinder (r=400) at (46,8.2).
# Goal doubles as ESS (no separate ESS turnpoint).
TASK = Task(
    turnpoints=[
        Turnpoint(46.0, 8.0, 1000, TurnpointKind.SSS, "SSS"),
        Turnpoint(46.0, 8.2, 400, TurnpointKind.GOAL, "GOAL"),
    ],
    start_time=GATE,
    start_direction=StartDirection.EXIT,
)


def _line_track(lon_start: float, lon_end: float, n: int, t0: int = GATE, dt: int = 10) -> Track:
    """A track flying due east along latitude 46.0."""
    fixes = []
    for i in range(n):
        lon = lon_start + (lon_end - lon_start) * i / (n - 1)
        fixes.append(Fix(time=t0 + i * dt, lat=46.0, lon=lon, pressure_alt=1000, gnss_alt=1000, valid=True))
    return Track(fixes=fixes)


def test_full_flight_makes_goal():
    track = _line_track(8.0, 8.2, 41)
    res = analyze(track, TASK)
    assert res.started is True
    assert res.in_goal is True
    assert res.reached_ess is True
    # Made goal => distance flown equals the full task distance.
    assert res.distance_flown == pytest.approx(res.task_distance, abs=1.0)
    # Optimized distance ~ centre distance minus both cylinder radii.
    centre = geo.distance(46.0, 8.0, 46.0, 8.2)
    assert res.task_distance == pytest.approx(centre - 1400, abs=10.0)
    assert res.ss_elapsed is not None and res.ss_elapsed > 0
    assert res.speed_kmh is not None and res.speed_kmh > 0


def test_start_time_after_gate():
    track = _line_track(8.0, 8.2, 41)
    res = analyze(track, TASK)
    # Crossing the 1000 m SSS edge happens well after the gate.
    assert res.start_time >= GATE
    assert res.start_time > GATE  # had to fly out of the cylinder first


def test_landout_partial_distance():
    # Pilot only reaches the halfway point and lands.
    track = _line_track(8.0, 8.1, 21)
    res = analyze(track, TASK)
    assert res.started is True
    assert res.in_goal is False
    assert 0 < res.distance_flown < res.task_distance


def test_no_valid_start():
    # Pilot loiters inside the SSS cylinder and never exits.
    track = _line_track(8.0, 8.005, 10)
    res = analyze(track, TASK)
    assert res.started is False
    assert res.distance_flown == 0.0
    assert res.in_goal is False


def test_speed_consistent_with_distance_and_time():
    track = _line_track(8.0, 8.2, 41)
    res = analyze(track, TASK)
    expected = (res.task_distance / 1000.0) / (res.ss_elapsed / 3600.0)
    assert res.speed_kmh == pytest.approx(expected, rel=1e-6)
