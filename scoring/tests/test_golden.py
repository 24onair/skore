"""Golden regression test against an official FS GAP2023 result.

Fixture: 2025~2026 남부리그 5차전 2라운드 (2026-06-28), Race to Goal 78.7 km.
The official FS-scored HTML and the pilots' IGC tracks live in ``samples/golden/``.

We verify the parts of our engine that are calibrated to match FS exactly:
distance made good (from launch), distance points, and time/speed points. Leading
points are intentionally NOT asserted here — the leading coefficient's reference
(LCmin) is a whole-field statistic that needs every pilot's track to compute, so
it cannot be validated from this three-pilot subset.
"""

from pathlib import Path

import pytest

from scoring import gap
from scoring.igc import parse_igc_file
from scoring.task import parse_xctsk_file
from scoring.validate import analyze

GOLDEN = Path(__file__).resolve().parent.parent.parent / "samples" / "golden"

# Day-level constants read from the official FS sheet (Task statistics).
AVAIL_DIST, AVAIL_TIME = 542.2, 295.8
BEST_DIST_KM = 78.657
BEST_TIME_S = 3.5481 * 3600  # fastest goal pilot's SS time

pytestmark = pytest.mark.skipif(not GOLDEN.is_dir(), reason="golden fixtures not present")


def _analyze(igc_name):
    task = parse_xctsk_file(str(GOLDEN / "task.xctsk"))
    return analyze(parse_igc_file(str(GOLDEN / igc_name)), task)


def _dist_points(dist_km):
    return AVAIL_DIST * min(dist_km, BEST_DIST_KM) / BEST_DIST_KM


# (file, official distance km, official distance points, official time points, in_goal)
CASES = [
    ("SongDaejin.igc", 78.66, 542.2, 226.7, True),   # rank 3, goal
    ("ParkJintaek.igc", 54.59, 376.3, None, False),  # rank 4, landout
    ("SonSungHoon.igc", 15.17, 104.6, None, False),  # rank 9, landout
]


@pytest.mark.parametrize("igc,off_dist,off_dp,off_tp,in_goal", CASES)
def test_distance_matches_official(igc, off_dist, off_dp, off_tp, in_goal):
    res = _analyze(igc)
    # Landout made-good is approximate; goal/clean tracks match to ~20 m.
    tol = 0.1 if in_goal or off_dist > 40 else 0.6
    assert res.distance_flown / 1000 == pytest.approx(off_dist, abs=tol)
    assert res.in_goal is in_goal


@pytest.mark.parametrize("igc,off_dist,off_dp,off_tp,in_goal", CASES)
def test_distance_points_match_official(igc, off_dist, off_dp, off_tp, in_goal):
    res = _analyze(igc)
    dp = _dist_points(res.distance_flown / 1000)
    tol = 1.0 if in_goal or off_dist > 40 else 6.0
    assert dp == pytest.approx(off_dp, abs=tol)


def test_goal_pilot_time_points_match_official():
    res = _analyze("SongDaejin.igc")
    assert res.reached_ess and res.in_goal
    tp = gap.time_points(res.ss_elapsed, BEST_TIME_S, AVAIL_TIME)
    assert tp == pytest.approx(226.7, abs=1.0)
    # SS elapsed time should match the official 03:52:37 exactly.
    assert res.ss_elapsed == 3 * 3600 + 52 * 60 + 37
