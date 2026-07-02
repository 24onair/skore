"""Per-pilot GAP point components: distance, time (speed), leading.

PG convention (see DECISIONS D3): distance is linear (difficulty is HG-only),
arrival is off. Each function returns points already scaled by the available pool
for that component.

⚠️ UNVERIFIED constants — see :mod:`scoring.params` and DECISIONS D1. The leading
formula in particular needs calibration against a real scored competition before
any official use.
"""

from __future__ import annotations

import math


def distance_points(distance: float, best_distance: float, avail: float, min_distance: float) -> float:
    """Linear distance points: avail × max(dist, MinDist) / bestDistance."""
    if best_distance <= 0:
        return 0.0
    d = max(distance, min_distance)
    return avail * min(1.0, d / best_distance)


def speed_fraction(ss_time: float, best_time: float) -> float:
    """GAP2023 speed fraction (PWCA / flat-decline): exponent 5/6, in decimal hours.

    ``SpeedFraction = max(0, 1 − ((Ptime − BestTime)/√BestTime)^(5/6))`` with times
    in hours. Inputs here are in **seconds** and converted. The hour units matter:
    the ``√BestTime`` scaling makes the formula unit-dependent. SpeedFraction hits 0
    at ``Ptime = BestTime + √BestTime`` (the FSDB ``max_time_to_get_time_points``).
    """
    if best_time <= 0 or ss_time <= 0:
        return 0.0
    if ss_time <= best_time:
        return 1.0
    bt_h = best_time / 3600.0
    pt_h = ss_time / 3600.0
    base = (pt_h - bt_h) / math.sqrt(bt_h)
    return max(0.0, 1.0 - base ** (5.0 / 6.0))


def time_points(ss_time: float | None, best_time: float | None, avail: float) -> float:
    """Speed points for a pilot who reached ESS; 0 otherwise."""
    if ss_time is None or best_time is None:
        return 0.0
    return avail * speed_fraction(ss_time, best_time)


def leading_factor(lc: float, lc_min: float) -> float:
    """1 − ((LC − LCmin)/√LCmin)^(2/3), floored at 0. LCmin = the leader's LC."""
    if lc_min <= 0:
        return 1.0 if lc <= 0 else 0.0
    if lc <= lc_min:
        return 1.0
    base = (lc - lc_min) / math.sqrt(lc_min)
    return max(0.0, 1.0 - (base * base) ** (1.0 / 3.0))


def leading_points(lc: float | None, lc_min: float | None, avail: float) -> float:
    """Leading points from the pilot's leading coefficient vs the field minimum."""
    if lc is None or lc_min is None:
        return 0.0
    return avail * leading_factor(lc, lc_min)
