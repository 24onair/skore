"""Regression: landing detection strips post-landing retrieve movement.

남부리그 4차전 "2일차-양산-말양-운문": Park Jintaek (FN13) landed at ~54.6 km, but his
LiveTrack kept logging the retrieve car driving home *through the goal cylinder*
(ESS+GOAL are both at C23011). Before landing detection the car earned him a false
goal — full distance + time + leading (724.8 pts). FS scored his real flight:
54.59 km, distance-only, 376.3 pts.

These tests pin the fix using the real fixtures under ``samples/nambu4/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scoring.igc import parse_igc
from scoring.task import parse_xctsk
from scoring.params import gap2023_korea
from scoring.result import Competitor, score_competition
from scoring.validate import analyze

FIX = Path(__file__).resolve().parent.parent.parent / "samples" / "nambu4"
pytestmark = pytest.mark.skipif(
    not (FIX / "task.xctsk").is_file() or not any(FIX.glob("*.igc")),
    reason="samples/nambu4 fixtures not present",
)


def _task():
    return parse_xctsk((FIX / "task.xctsk").read_text(encoding="utf-8"))


def _igc(needle: str):
    f = next(FIX.glob(f"*{needle}*.igc"))
    return parse_igc(f.read_text(encoding="latin-1"))


def test_park_jintaek_lands_short_not_goal():
    """The retrieve drive must not credit goal — he landed at ~54.6 km."""
    a = analyze(_igc("Jintaek"), _task())
    assert a.in_goal is False
    assert a.reached_ess is False
    assert 53.0 < a.distance_km < 56.0   # FS: 54.59 km


def test_field_goal_count_and_no_retrieve_inflation():
    comps = []
    for f in sorted(FIX.glob("*.igc")):
        tr = parse_igc(f.read_text(encoding="latin-1"))
        name = f.stem.split("(")[-1].split(")")[0] if "(" in f.stem else f.stem
        comps.append(Competitor(pilot_id=name, name=name, analysis=analyze(tr, _task())))
    r = score_competition(comps, gap2023_korea(), num_present=len(comps))

    by = {p.name: p for p in r.results}
    assert r.num_in_goal == 3                       # FS: 3 in goal (was 4 with the false goal)
    pj = by["Park Jintaek"]
    assert pj.in_goal is False
    assert pj.total < 450                           # was 724.8; FS 376.3
    assert pj.time_points == 0.0                    # landed before ESS
    # goal pilots keep their leading points (field-wide LC tail, not the early-landers)
    assert by["Min Byungdo"].in_goal is True
    assert by["Min Byungdo"].leading_points > 50
