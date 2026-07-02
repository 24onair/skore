"""Tests for the task-distance optimizer."""

import pytest

from scoring import geo
from scoring.models import GoalType, Task, Turnpoint, TurnpointKind
from scoring.optimize import optimize_route


def _tp(lat, lon, r, kind=TurnpointKind.TURNPOINT):
    return Turnpoint(lat=lat, lon=lon, radius=r, kind=kind)


def test_two_points_endpoint_pulled_in():
    # Start cylinder r=1000, goal as a point (r=0). Optimal clips the start edge
    # nearest goal, so distance = centre distance - 1000.
    task = Task(
        turnpoints=[
            _tp(46.0, 8.0, 1000, TurnpointKind.SSS),
            _tp(46.0, 8.1, 0, TurnpointKind.GOAL),
        ],
        start_time=0,
    )
    centre = geo.distance(46.0, 8.0, 46.0, 8.1)
    route = optimize_route(task)
    assert route.total == pytest.approx(centre - 1000, abs=2.0)
    assert len(route.legs) == 1
    assert route.cum_from_start == pytest.approx([0.0, route.total])
    assert route.to_goal[0] == pytest.approx(route.total)
    assert route.to_goal[-1] == pytest.approx(0.0)


def test_collinear_middle_cylinder_free():
    # Three collinear points; the middle cylinder sits on the straight line, so
    # the optimal course is just the straight start->goal distance.
    task = Task(
        turnpoints=[
            _tp(46.0, 8.00, 0, TurnpointKind.SSS),
            _tp(46.0, 8.05, 2000, TurnpointKind.TURNPOINT),
            _tp(46.0, 8.10, 0, TurnpointKind.GOAL),
        ],
        start_time=0,
    )
    straight = geo.distance(46.0, 8.0, 46.0, 8.1)
    route = optimize_route(task)
    assert route.total == pytest.approx(straight, abs=5.0)


def test_total_between_bounds():
    # An off-line turnpoint: optimized total must be <= sum of centre legs and
    # >= straight start->goal distance.
    tps = [
        _tp(46.0, 8.0, 0, TurnpointKind.SSS),
        _tp(46.2, 8.2, 3000, TurnpointKind.TURNPOINT),
        _tp(46.0, 8.4, 400, TurnpointKind.GOAL),
    ]
    task = Task(turnpoints=tps, start_time=0)
    centre_sum = geo.distance(46.0, 8.0, 46.2, 8.2) + geo.distance(46.2, 8.2, 46.0, 8.4)
    straight = geo.distance(46.0, 8.0, 46.0, 8.4)
    route = optimize_route(task)
    assert straight - 1 <= route.total <= centre_sum + 1
    # The turnpoint clip should save roughly its radius vs the centre route.
    assert route.total < centre_sum - 1000


def test_cum_and_to_goal_consistent():
    task = Task(
        turnpoints=[
            _tp(46.0, 8.0, 0, TurnpointKind.SSS),
            _tp(46.1, 8.1, 1000),
            _tp(46.2, 8.2, 0, TurnpointKind.GOAL),
        ],
        start_time=0,
    )
    route = optimize_route(task)
    assert route.cum_from_start[-1] == pytest.approx(route.total)
    for c, g in zip(route.cum_from_start, route.to_goal):
        assert c + g == pytest.approx(route.total)
