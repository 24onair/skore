"""Tests for GAP day-quality, point components and competition assembly."""

import pytest

from scoring import gap
from scoring.params import ScoringParams
from scoring.result import Competitor, score_competition
from scoring.validate import TrackAnalysis
from scoring.validity import (
    distance_validity,
    launch_validity,
    points_pool,
    time_validity,
)

P = ScoringParams(nominal_distance=30_000, nominal_time=3_600, min_distance=5_000)


# --- validity ---------------------------------------------------------------
def test_launch_validity_default_one():
    # nominal_launch = 0 disables launch validity (=1).
    assert launch_validity(50, 40, 0.0) == 1.0


def test_launch_validity_in_range():
    v = launch_validity(100, 50, 0.5)
    assert 0.0 <= v <= 1.0


def test_distance_validity_capped():
    dists = [40_000, 35_000, 30_000, 10_000]
    v = distance_validity(dists, len(dists), max(dists), P)
    assert 0.0 <= v <= 1.0


def test_time_validity_short_task_penalised():
    # A very fast best time (short task) should yield lower validity than a long one.
    short = time_validity(600, 40_000, True, P)    # 10 min
    long = time_validity(3_600, 40_000, True, P)   # 60 min == nominal
    assert short < long
    assert 0.0 <= short <= 1.0 and 0.0 <= long <= 1.0


def test_points_pool_sums_to_available():
    pool = points_pool(0.8, 0.3, P)
    total = pool.distance + pool.time + pool.leading + pool.arrival
    assert total == pytest.approx(pool.available)
    assert pool.available == pytest.approx(800.0)
    assert pool.leading > 0  # leading on by default


def test_points_pool_leading_off():
    pool = points_pool(0.8, 0.3, ScoringParams(leading_points=False))
    assert pool.leading == 0.0
    assert pool.distance + pool.time == pytest.approx(pool.available)


# --- point components -------------------------------------------------------
def test_distance_points_linear():
    assert gap.distance_points(50_000, 50_000, 400, 5_000) == pytest.approx(400)
    assert gap.distance_points(25_000, 50_000, 400, 5_000) == pytest.approx(200)


def test_speed_fraction_best_is_one():
    assert gap.speed_fraction(1_000, 1_000) == 1.0
    assert 0.0 <= gap.speed_fraction(1_500, 1_000) < 1.0


def test_leading_factor_leader_full():
    assert gap.leading_factor(100, 100) == 1.0
    assert 0.0 <= gap.leading_factor(400, 100) < 1.0


# --- competition assembly ---------------------------------------------------
def _analysis(dist, ess=False, ss=None, goal=False, lc=None, task=50_000):
    return TrackAnalysis(
        task_distance=task,
        distance_flown=dist,
        started=True,
        reached_ess=ess,
        ss_elapsed=ss,
        in_goal=goal,
        leading_coefficient=lc,
    )


def test_competition_ranking():
    comp = [
        Competitor("p1", "Fast Goal", _analysis(50_000, ess=True, ss=1_200, goal=True, lc=100)),
        Competitor("p2", "Slow Goal", _analysis(50_000, ess=True, ss=1_400, goal=True, lc=150)),
        Competitor("p3", "ESS only", _analysis(30_000, ess=False, lc=300)),
        Competitor("p4", "Landout", _analysis(9_000, ess=False, lc=500)),
    ]
    res = score_competition(comp, P)

    assert res.num_flying == 4
    assert res.num_in_goal == 2
    assert res.best_time == 1_200
    # Pool integrity
    assert res.pool.distance + res.pool.time + res.pool.leading + res.pool.arrival == pytest.approx(
        res.pool.available
    )
    # Ranking: fast goal first, then slow goal, then by distance.
    order = [r.pilot_id for r in res.results]
    assert order[0] == "p1"
    assert order[1] == "p2"
    assert res.results[0].rank == 1
    # Winner gets full time + leading share (best time, lowest LC).
    assert res.results[0].time_points == pytest.approx(res.pool.time)
    assert res.results[0].leading_points == pytest.approx(res.pool.leading)
    # Both goal pilots get full distance share (both at best distance).
    assert res.results[0].distance_points == pytest.approx(res.pool.distance)
    # Totals are descending.
    totals = [r.total for r in res.results]
    assert totals == sorted(totals, reverse=True)


def test_min_distance_floor():
    comp = [Competitor("p1", "A", _analysis(1_000)), Competitor("p2", "B", _analysis(40_000))]
    res = score_competition(comp, P)
    a = next(r for r in res.results if r.pilot_id == "p1")
    assert a.distance == P.min_distance  # floored up to MinDist


def test_tie_shares_rank():
    comp = [
        Competitor("p1", "A", _analysis(30_000, lc=200)),
        Competitor("p2", "B", _analysis(30_000, lc=200)),
    ]
    res = score_competition(comp, P)
    assert res.results[0].rank == res.results[1].rank == 1
