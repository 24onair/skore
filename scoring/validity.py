"""Day quality (task validity) and the available-points split.

Task validity = LaunchValidity × DistanceValidity × TimeValidity, each in [0,1].
The total available pool is ``1000 × TaskValidity``, split between distance, time
and leading (arrival is off for PG).

⚠️ UNVERIFIED constants — see :mod:`scoring.params` and DECISIONS D1.
"""

from __future__ import annotations

from dataclasses import dataclass

from .params import ScoringParams


@dataclass(slots=True)
class DayQuality:
    launch: float
    distance: float
    time: float

    @property
    def quality(self) -> float:
        return self.launch * self.distance * self.time


@dataclass(slots=True)
class PointsPool:
    available: float   # 1000 × dayQuality
    distance: float
    time: float
    leading: float
    arrival: float


def launch_validity(num_present: int, num_flying: int, nominal_launch: float) -> float:
    """LV = 0.027·r + 2.917·r² − 1.944·r³, r = min(1, flying/(present·nominalLaunch))."""
    if nominal_launch <= 0 or num_present <= 0:
        return 1.0
    r = min(1.0, num_flying / (num_present * nominal_launch))
    return max(0.0, min(1.0, 0.027 * r + 2.917 * r**2 - 1.944 * r**3))


def distance_validity(
    distances: list[float], num_flying: int, best_distance: float, p: ScoringParams
) -> float:
    """Area-under-curve distance validity, capped at 1."""
    if num_flying <= 0:
        return 0.0
    area = (
        (p.nominal_goal + 1) * (p.nominal_distance - p.min_distance)
        + max(0.0, p.nominal_goal * (best_distance - p.nominal_distance))
    ) / 2.0
    if area <= 0:
        return 0.0
    sum_over_min = sum(max(0.0, d - p.min_distance) for d in distances)
    return min(1.0, sum_over_min / (num_flying * area))


def time_validity(best_time: float | None, best_distance: float, any_ess: bool, p: ScoringParams) -> float:
    """TV polynomial in r, where r measures the task against its nominal size.

    Penalises tasks that are too short: r = bestTime/nomTime (or bestDist/nomDist
    when no one reached ESS), capped at 1.
    """
    if any_ess and best_time and best_time > 0:
        r = min(1.0, best_time / p.nominal_time)
    else:
        r = min(1.0, best_distance / p.nominal_distance) if p.nominal_distance > 0 else 0.0
    tv = -0.271 + 2.912 * r - 2.098 * r**2 + 0.457 * r**3
    return max(0.0, min(1.0, tv))


def day_quality(
    num_present: int,
    num_flying: int,
    distances: list[float],
    best_distance: float,
    best_time: float | None,
    any_ess: bool,
    p: ScoringParams,
) -> DayQuality:
    return DayQuality(
        launch=launch_validity(num_present, num_flying, p.nominal_launch),
        distance=distance_validity(distances, num_flying, best_distance, p),
        time=time_validity(best_time, best_distance, any_ess, p),
    )


def points_pool(quality: float, goal_ratio: float, p: ScoringParams) -> PointsPool:
    """Split the 1000×quality pool into distance / time / leading / arrival.

    GAP2023 Leading-Time-Ratio (LTR) model: the distance weight is the cubic in the
    goal ratio; the remaining ``(1-DistanceWeight)`` is split between leading and
    time by ``LTR`` (leading) and ``1-LTR`` (time). With no goal, leading takes the
    whole remainder. Arrival is off for PG.
    """
    avail = 1000.0 * quality
    gr = max(0.0, min(1.0, goal_ratio))
    dist_w = 0.9 - 1.665 * gr + 1.713 * gr**2 - 0.587 * gr**3
    dist_w = max(0.0, min(1.0, dist_w))
    rest = 1 - dist_w
    if not p.leading_points:
        lead_w = 0.0
    elif gr <= 0:
        lead_w = rest  # no goal: all non-distance weight goes to leading
    else:
        lead_w = rest * p.leading_time_ratio
    arr_w = 0.0  # PG: arrival off (see DECISIONS D3)
    time_w = max(0.0, rest - lead_w)
    return PointsPool(
        available=avail,
        distance=dist_w * avail,
        time=time_w * avail,
        leading=lead_w * avail,
        arrival=arr_w * avail,
    )
