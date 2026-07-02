"""Competition assembly: turn a field of analyzed tracks into a ranked result.

Takes the per-pilot :class:`~scoring.validate.TrackAnalysis` objects, computes the
day quality and the available-points split once for the task, then scores every
pilot's distance / time / leading components and ranks them.

⚠️ Absolute scores are provisional until calibrated against a real scored comp
(see DECISIONS D1). The pipeline shape — validity → pool → per-pilot → rank — is
the standard GAP structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import gap
from .params import ScoringParams
from .validity import DayQuality, PointsPool, day_quality, points_pool
from .validate import TrackAnalysis, _leading_coefficient


@dataclass(slots=True)
class Competitor:
    pilot_id: str
    name: str
    analysis: TrackAnalysis
    bib: str | None = None     # competition id from IGC header (HFCID), if present
    glider: str | None = None  # glider from IGC header (HFGTY/HFGID), if present


@dataclass(slots=True)
class PilotResult:
    pilot_id: str
    name: str
    bib: str | None
    glider: str | None
    distance: float            # scored distance (m), floored at MinDist
    in_goal: bool
    reached_ess: bool
    ss_time: int | None
    leading_coefficient: float | None
    distance_points: float
    time_points: float
    leading_points: float
    total: float
    rank: int = 0


@dataclass(slots=True)
class CompetitionResult:
    task_distance: float
    num_flying: int
    num_present: int
    num_in_goal: int
    best_distance: float
    best_time: int | None
    day_quality: DayQuality
    pool: PointsPool
    results: list[PilotResult] = field(default_factory=list)


def score_competition(
    competitors: list[Competitor],
    params: ScoringParams | None = None,
    num_present: int | None = None,
) -> CompetitionResult:
    """Score the field. ``num_present`` is the registered/present pilot count used
    for launch validity; defaults to the number of pilots flown (uploaded tracks).
    """
    p = params or ScoringParams()
    n = len(competitors)
    present = max(num_present or n, n)  # present is never fewer than those who flew

    # Scored distance: every pilot who flew is credited at least MinDist.
    scored_dist = {c.pilot_id: max(c.analysis.distance_flown, p.min_distance) for c in competitors}
    distances = list(scored_dist.values())
    best_distance = max(distances) if distances else 0.0

    ess_times = [c.analysis.ss_elapsed for c in competitors if c.analysis.reached_ess and c.analysis.ss_elapsed]
    best_time = min(ess_times) if ess_times else None
    any_ess = bool(ess_times)

    num_in_goal = sum(1 for c in competitors if c.analysis.in_goal)
    goal_ratio = num_in_goal / n if n else 0.0

    quality = day_quality(
        num_present=present,
        num_flying=n,
        distances=distances,
        best_distance=best_distance,
        best_time=best_time,
        any_ess=any_ess,
        p=p,
    )
    pool = points_pool(quality.quality, goal_ratio, p)

    # Leading coefficient, recomputed field-wide: a pilot who lands before ESS has
    # their leading integral held at the final "distance still to fly" until the
    # LAST pilot's time (ESS or landing). Without this, an early-landing pilot's
    # integral stops early and they falsely appear to have led. Goal/ESS pilots are
    # unaffected (their integral ends at ESS).
    _end_times = [
        (c.analysis.ess_time if c.analysis.reached_ess and c.analysis.ess_time
         else c.analysis.landing_time)
        for c in competitors
        if c.analysis.landing_time is not None
    ]
    field_max_time = max(_end_times) if _end_times else None
    lc_by_pilot: dict[str, float | None] = {}
    for c in competitors:
        a = c.analysis
        if a.lead_samples:
            lc_by_pilot[c.pilot_id] = _leading_coefficient(
                a.lead_samples, a.lead_gate, a.lead_sss_course, a.lead_ess_course,
                a.ess_time, a.reached_ess, max_time=field_max_time,
            )
        else:
            lc_by_pilot[c.pilot_id] = a.leading_coefficient
    lcs = [lc for lc in lc_by_pilot.values() if lc is not None]
    lc_min = min(lcs) if lcs else None

    results: list[PilotResult] = []
    for c in competitors:
        a = c.analysis
        d = scored_dist[c.pilot_id]
        lc = lc_by_pilot[c.pilot_id]
        dp = gap.distance_points(d, best_distance, pool.distance, p.min_distance)
        tp = gap.time_points(a.ss_elapsed if a.reached_ess else None, best_time, pool.time)
        lp = gap.leading_points(lc, lc_min, pool.leading) if p.leading_points else 0.0
        results.append(
            PilotResult(
                pilot_id=c.pilot_id,
                name=c.name,
                bib=c.bib,
                glider=c.glider,
                distance=d,
                in_goal=a.in_goal,
                reached_ess=a.reached_ess,
                ss_time=a.ss_elapsed,
                leading_coefficient=a.leading_coefficient,
                distance_points=dp,
                time_points=tp,
                leading_points=lp,
                total=dp + tp + lp,
            )
        )

    # Rank by total descending; ties share a rank (standard competition ranking).
    results.sort(key=lambda r: r.total, reverse=True)
    prev_total: float | None = None
    prev_rank = 0
    for i, r in enumerate(results, start=1):
        if prev_total is None or abs(r.total - prev_total) > 1e-9:
            r.rank = i
            prev_rank = i
            prev_total = r.total
        else:
            r.rank = prev_rank

    task_distance = competitors[0].analysis.task_distance if competitors else 0.0
    return CompetitionResult(
        task_distance=task_distance,
        num_flying=n,
        num_present=present,
        num_in_goal=num_in_goal,
        best_distance=best_distance,
        best_time=best_time,
        day_quality=quality,
        pool=pool,
        results=results,
    )
