"""Track validation — judge one pilot's IGC track against a task.

Produces everything Phase 1 needs for single-track analysis and everything Phase 2
needs as per-pilot input to the GAP scorer:

  * did the pilot take a valid start (cross the SSS in the right direction after the
    gate)?
  * which turnpoints were tagged, in order, and when?
  * did the pilot reach ESS / goal, and at what (interpolated) time?
  * how far did the pilot get along the optimized course ("distance made good")?
  * speed-section elapsed time and speed.

Distance is measured along the optimized course **from the SSS onward** (the
takeoff cylinder is not part of the scored distance). Times are seconds since UTC
midnight, matching :class:`~scoring.models.Fix`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geo
from .models import Fix, GoalType, StartDirection, Task, TaskType, Track, Turnpoint, TurnpointKind
from .optimize import OptimizedRoute, optimize_route


@dataclass(slots=True)
class TagEvent:
    index: int          # index into the scoring turnpoint list
    name: str
    kind: TurnpointKind
    time: int           # seconds since UTC midnight (interpolated crossing)


@dataclass(slots=True)
class TrackAnalysis:
    task_distance: float                 # optimized SSS->goal distance (m)
    distance_flown: float                # distance made good (m)
    started: bool = False
    start_time: int | None = None        # actual SSS crossing time (s)
    tags: list[TagEvent] = field(default_factory=list)
    reached_ess: bool = False
    ess_time: int | None = None
    in_goal: bool = False
    goal_time: int | None = None
    ss_elapsed: int | None = None        # speed-section time (s)
    speed_kmh: float | None = None
    landing_time: int | None = None
    leading_coefficient: float | None = None  # GAP LC (lower = led more); None if no start
    route: OptimizedRoute | None = None
    # inputs kept so the field scorer can recompute LC with the field-wide max_time
    # (a landed-out pilot's leading tail must extend to the last pilot's time — see
    # result.score_competition). These are in-memory only (not serialized).
    lead_samples: list[tuple[int, float]] = field(default_factory=list)
    lead_gate: int = 0
    lead_sss_course: float = 0.0
    lead_ess_course: float = 0.0

    @property
    def distance_km(self) -> float:
        return self.distance_flown / 1000.0


def _dist(fix: Fix, tp: Turnpoint, model: str) -> float:
    return geo.distance(fix.lat, fix.lon, tp.lat, tp.lon, model=model)


def _inside(fix: Fix, tp: Turnpoint, model: str) -> bool:
    return _dist(fix, tp, model) <= tp.radius


def _interp_time(f0: Fix, d0: float, f1: Fix, d1: float, radius: float) -> int:
    """Interpolate the crossing time where distance-to-centre equals ``radius``.

    ``d0``/``d1`` are the distances to the cylinder centre at the bracketing fixes.
    """
    denom = d0 - d1
    if denom == 0:
        return f1.time
    frac = (d0 - radius) / denom
    frac = max(0.0, min(1.0, frac))
    return round(f0.time + frac * (f1.time - f0.time))


def _scoring_turnpoints(task: Task) -> tuple[list[Turnpoint], int]:
    """Return the turnpoints used for scoring (SSS..goal) and the SSS offset.

    The takeoff cylinder is dropped; distance is measured from the SSS.
    """
    start_idx = next(
        (i for i, t in enumerate(task.turnpoints) if t.kind == TurnpointKind.SSS), 0
    )
    return task.turnpoints[start_idx:], start_idx


def _find_start(fixes: list[Fix], sss: Turnpoint, gate: int, direction: StartDirection, model: str) -> int | None:
    """First valid SSS crossing at/after the gate, in the required direction."""
    want_inside = direction == StartDirection.ENTER  # ENTER: outside->inside
    prev: Fix | None = None
    prev_inside = False
    for fix in fixes:
        inside = _inside(fix, sss, model)
        if prev is not None and fix.time >= gate:
            crossed = inside == want_inside and prev_inside != want_inside
            if crossed:
                d0 = _dist(prev, sss, model)
                d1 = _dist(fix, sss, model)
                t = _interp_time(prev, d0, fix, d1, sss.radius)
                return max(t, gate)
        prev, prev_inside = fix, inside
    return None


def _landing_index(
    fixes: list[Fix],
    model: str,
    move: float = 100.0,
    radius: float = 30.0,
    hold: int = 180,
    alt_margin: float = 100.0,
) -> int:
    """Index of the fix where the pilot **landed** — everything after is ignored.

    LiveTracking / retrieve IGCs keep logging after the pilot lands: the retrieve
    car drives home, often back through turnpoint or goal cylinders, which would
    falsely credit full distance / goal / time. FS scores only the flight, so we do
    too: detect the landing as the first **sustained stationary** period (stayed
    within ``radius`` for ``hold`` seconds) at **low altitude** (within
    ``alt_margin`` of the track's minimum), searched only **after takeoff** (first
    fix more than ``move`` m from the launch point — this skips the pre-launch wait
    and avoids mistaking soaring-into-wind, which never stays put for minutes, for a
    landing). Returns ``len-1`` if no landing is detected (track already ends clean).
    """
    n = len(fixes)
    if n < 3:
        return n - 1
    p0 = fixes[0]
    takeoff = 0
    for i in range(1, n):
        if geo.distance(p0.lat, p0.lon, fixes[i].lat, fixes[i].lon, model=model) > move:
            takeoff = i
            break
    ceil = min(f.alt for f in fixes[takeoff:]) + alt_margin
    for i in range(takeoff, n):
        if fixes[i].alt > ceil:
            continue  # a landing is at ground level, not mid-air (soaring / thermalling)
        t_end = fixes[i].time + hold
        k = i
        stationary = True
        while k + 1 < n and fixes[k + 1].time <= t_end:
            if geo.distance(fixes[i].lat, fixes[i].lon, fixes[k + 1].lat, fixes[k + 1].lon, model=model) > radius:
                stationary = False
                break
            k += 1
        if stationary and fixes[k].time - fixes[i].time >= hold * 0.8:
            return i
    return n - 1


def analyze(track: Track, task: Task) -> TrackAnalysis:
    """Analyze a single track against a task.

    Distance is "made good" along the **full optimized course from the takeoff
    cylinder** (FS measures distance from launch, not from the SSS), and is
    credited independently of a valid start — a pilot who never starts the speed
    section still scores the distance flown. The valid SSS crossing only gates the
    speed-section time and leading points.

    The track is first truncated at the detected **landing** (see
    :func:`_landing_index`) so post-landing retrieve movement can't earn points.
    """
    model = task.earth_model
    score_tps = task.turnpoints  # full course, launch -> goal
    route = optimize_route(Task(turnpoints=score_tps, start_time=task.start_time, earth_model=model))

    result = TrackAnalysis(task_distance=route.total, distance_flown=0.0, route=route)
    fixes = track.fixes
    n = len(score_tps)
    if not fixes or n == 0:
        return result
    # drop everything after the pilot landed (retrieve drive, tracker artifacts)
    land_idx = _landing_index(fixes, model)
    fixes = fixes[: land_idx + 1]
    result.landing_time = fixes[-1].time

    sss_index = next((i for i, t in enumerate(score_tps) if t.kind == TurnpointKind.SSS), 0)
    has_ess = any(t.kind == TurnpointKind.ESS for t in score_tps)
    ess_index = next(
        (i for i, t in enumerate(score_tps) if t.kind == TurnpointKind.ESS), n - 1
    )

    # --- valid start (gates time/leading only, not distance) -----------------
    sss_tp = score_tps[sss_index]
    if sss_tp.kind == TurnpointKind.SSS:
        result.start_time = _find_start(fixes, sss_tp, task.start_time, task.start_direction, model)
        result.started = result.start_time is not None
    else:
        result.started = True

    # --- distance made good from launch; tag turnpoints in order -------------
    r = 1  # next turnpoint to tag (0 is the takeoff / course start)
    best_made_good = route.cum_from_start[0]
    prev_fix: Fix | None = None
    samples: list[tuple[int, float]] = []  # (fix.time, made_good) for leading-coefficient

    for fix in fixes:
        while r < n:
            tp = score_tps[r]
            d = _dist(fix, tp, model)
            if not _reached(tp, d):
                break
            t = fix.time
            if prev_fix is not None:
                pd = _dist(prev_fix, tp, model)
                if pd > tp.radius >= 0 and pd != d:
                    t = _interp_time(prev_fix, pd, fix, d, tp.radius)
            result.tags.append(TagEvent(r, tp.name or tp.kind.value, tp.kind, t))
            if r == ess_index:
                result.reached_ess = True
                result.ess_time = t
            if tp.kind == TurnpointKind.GOAL:
                result.in_goal = result.reached_ess or not has_ess
                result.goal_time = t
            r += 1

        if r < n:
            # Project the fix onto the current optimized leg (route[r-1] -> route[r])
            # for an accurate along-course distance, the way FS/airscore measure it.
            a_lat, a_lon = route.points[r - 1]
            b_lat, b_lon = route.points[r]
            plat, plon, _ = geo.point_on_segment_nearest(fix.lat, fix.lon, a_lat, a_lon, b_lat, b_lon)
            along = min(geo.distance(a_lat, a_lon, plat, plon, model=model), route.legs[r - 1])
            made_good = route.cum_from_start[r - 1] + along
        else:
            made_good = route.total
        best_made_good = max(best_made_good, made_good)
        samples.append((fix.time, made_good))
        prev_fix = fix

    result.distance_flown = min(best_made_good, route.total)

    # --- speed section: SS->ESS distance over elapsed time (needs valid start)-
    ss_course = route.cum_from_start[ess_index] - route.cum_from_start[sss_index]
    started_ok = result.started or sss_tp.kind != TurnpointKind.SSS
    if result.reached_ess and result.ess_time is not None and started_ok:
        if task.task_type == TaskType.ELAPSED_TIME and result.start_time is not None:
            ss_start = result.start_time
        else:  # Race to Goal: clock runs from the gate
            ss_start = task.start_time
        elapsed = result.ess_time - ss_start
        if elapsed > 0:
            result.ss_elapsed = elapsed
            result.speed_kmh = (ss_course / 1000.0) / (elapsed / 3600.0)

    # --- leading coefficient (over the speed section) ------------------------
    gate = task.start_time if task.task_type != TaskType.ELAPSED_TIME else (result.start_time or task.start_time)
    result.lead_samples = samples
    result.lead_gate = gate
    result.lead_sss_course = route.cum_from_start[sss_index]
    result.lead_ess_course = route.cum_from_start[ess_index]
    # provisional LC (tail to own landing); the field scorer recomputes with the
    # field-wide max_time so early-landing pilots don't appear to have "led".
    result.leading_coefficient = _leading_coefficient(
        samples, gate, result.lead_sss_course, result.lead_ess_course,
        result.ess_time, result.reached_ess,
    )

    return result


_LEADING_TIME_REF = 1800.0  # PWCA reference (s) in LC = ∫g·dt / (1800·SS_km)


def _leading_coefficient(
    samples: list[tuple[int, float]],
    gate: int,
    sss_course: float,
    ess_course: float,
    ess_time: int | None,
    reached_ess: bool,
    max_time: int | None = None,
) -> float | None:
    """PWCA2019 (linear) leading coefficient.

    ``LC = ∫ g(t) dt / (1800 · SS_length_km)`` where ``g`` is the running-minimum
    distance still to fly to ESS (km, never increases — backward flight doesn't
    count) and ``t`` is seconds since the start gate, over the speed section. A
    lower LC means the pilot kept ``g`` small early — i.e. led. ``use_pwca2019_for_lc``
    / ``use_distance_squared_for_LC=0`` selects this linear form (not the g² form).

    ``max_time`` (field-level: the last pilot's ESS/landing time) extends a tail for
    pilots who land before ESS; when unknown the integral simply stops at landing.
    """
    ss_length = (ess_course - sss_course) / 1000.0  # km
    if ss_length <= 0 or not samples:
        return None
    cutoff = ess_time if (reached_ess and ess_time is not None) else None

    seq: list[tuple[float, float]] = []
    gmin = ss_length
    for t_abs, mg in samples:
        if cutoff is not None and t_abs > cutoff:
            break
        t = t_abs - gate
        if t < 0:
            continue
        dist_ess = max(0.0, (ess_course - min(mg, ess_course)) / 1000.0)
        gmin = min(gmin, dist_ess)
        seq.append((float(t), gmin))
    if len(seq) < 2:
        return 0.0

    area = 0.0  # ∫ g dt, trapezoidal (km·s)
    for (t0, g0), (t1, g1) in zip(seq, seq[1:]):
        area += (t1 - t0) * (g0 + g1) / 2.0
    # Tail: pilot landed before ESS -> hold final g until the field's max time.
    if not reached_ess and max_time is not None:
        t_last, g_last = seq[-1]
        t_end = max_time - gate
        if t_end > t_last:
            area += (t_end - t_last) * g_last

    return area / (_LEADING_TIME_REF * ss_length)


def _reached(tp: Turnpoint, d: float) -> bool:
    """Whether ``tp`` is tagged given the fix's distance ``d`` to its centre.

    Cylinders: a fix inside the radius. Goal *line* (radius 0) is approximated as a
    proximity tag in the MVP — see DECISIONS/README; precise line-crossing is a
    Phase 3 refinement.
    """
    if tp.radius > 0:
        return d <= tp.radius
    if tp.kind == TurnpointKind.GOAL and tp.goal_type == GoalType.LINE:
        return d <= 50.0  # MVP proximity threshold for a zero-radius goal line
    return d <= 1.0
