"""Optimized task distance — the shortest path that touches every cylinder in order.

Competition distance is *not* the sum of centre-to-centre legs: a pilot only has
to clip the edge of each cylinder, so the scored course is the shortest polyline
that visits each cylinder (SSS, turnpoints, ESS, goal) in sequence.

Algorithm (matches the approach used by FS / Airscore, implemented clean-room):

1. Project all cylinder centres into a local equirectangular plane (metres). At
   task scale this is accurate enough to *locate* the optimal crossing points.
2. Seed each route point at its cylinder centre, then iteratively relax: each
   interior point moves to the spot on its own circle that minimises the sum of
   distances to its two neighbours; each endpoint moves to the spot on its circle
   nearest its single neighbour. Sweep until the total length stops shrinking.
3. Convert the optimal points back to lat/lon and **re-measure every leg with the
   WGS84 geodesic** (GeographicLib) so the reported distance matches official
   scoring (see DECISIONS D2).

A point whose cylinder radius is 0 (e.g. a goal *line*, modelled as its centre)
is held fixed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import geo
from .models import Task, Turnpoint

_M_PER_DEG = 111_320.0


@dataclass(slots=True)
class OptimizedRoute:
    """Result of optimising a task course."""

    points: list[tuple[float, float]]   # optimal (lat, lon) per turnpoint, in order
    legs: list[float]                   # WGS84 leg distances (m); legs[i] = point[i]->point[i+1]
    total: float                        # total optimized distance (m)
    cum_from_start: list[float]         # distance from first point to point[i] (m)
    to_goal: list[float]                # remaining distance from point[i] to the last point (m)


class _Projection:
    """Local equirectangular projection centred on a reference latitude."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.cos0 = math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return ((lon - self.lon0) * _M_PER_DEG * self.cos0, (lat - self.lat0) * _M_PER_DEG)

    def to_ll(self, x: float, y: float) -> tuple[float, float]:
        lat = self.lat0 + y / _M_PER_DEG
        lon = self.lon0 + x / (_M_PER_DEG * self.cos0)
        return lat, lon


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _best_on_circle_two(
    cx: float, cy: float, r: float, ax: float, ay: float, bx: float, by: float
) -> tuple[float, float]:
    """Point on circle (cx,cy,r) minimising dist to A plus dist to B.

    Numeric: coarse angular scan then golden-section refine on the best arc. The
    objective is smooth and unimodal on the near-side arc, so this is robust and
    cheap for the handful of turnpoints in a task.
    """

    def f(theta: float) -> float:
        px = cx + r * math.cos(theta)
        py = cy + r * math.sin(theta)
        return _dist(px, py, ax, ay) + _dist(px, py, bx, by)

    # Coarse scan (1-degree steps).
    best_t = 0.0
    best_v = math.inf
    steps = 360
    for i in range(steps):
        t = 2 * math.pi * i / steps
        v = f(t)
        if v < best_v:
            best_v, best_t = v, t

    # Golden-section refine in a +/- one-step window.
    win = 2 * math.pi / steps
    lo, hi = best_t - win, best_t + win
    gr = (math.sqrt(5) - 1) / 2
    c = hi - gr * (hi - lo)
    d = lo + gr * (hi - lo)
    fc, fd = f(c), f(d)
    for _ in range(40):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - gr * (hi - lo)
            fc = f(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + gr * (hi - lo)
            fd = f(d)
    t = (lo + hi) / 2
    return cx + r * math.cos(t), cy + r * math.sin(t)


def _best_on_circle_one(
    cx: float, cy: float, r: float, ax: float, ay: float
) -> tuple[float, float]:
    """Point on circle nearest to a single neighbour A (endpoint case)."""
    dx, dy = ax - cx, ay - cy
    d = math.hypot(dx, dy)
    if d == 0:
        return cx + r, cy  # neighbour at centre: any edge point; pick +x
    return cx + r * dx / d, cy + r * dy / d


def optimize_route(task: Task, *, max_sweeps: int = 100, tol: float = 0.1) -> OptimizedRoute:
    """Compute the optimized course through all turnpoint cylinders in order."""
    tps: list[Turnpoint] = task.turnpoints
    n = len(tps)
    if n == 0:
        return OptimizedRoute([], [], 0.0, [], [])
    if n == 1:
        return OptimizedRoute([(tps[0].lat, tps[0].lon)], [], 0.0, [0.0], [0.0])

    lat0 = sum(t.lat for t in tps) / n
    lon0 = sum(t.lon for t in tps) / n
    proj = _Projection(lat0, lon0)

    centres = [proj.to_xy(t.lat, t.lon) for t in tps]
    radii = [t.radius for t in tps]
    pts = [list(c) for c in centres]  # seed at centres

    def total_len() -> float:
        return sum(_dist(*pts[i], *pts[i + 1]) for i in range(n - 1))

    prev_len = total_len()
    for _ in range(max_sweeps):
        for i in range(n):
            r = radii[i]
            if r <= 0:
                continue  # fixed point (e.g. line goal modelled as centre)
            cx, cy = centres[i]
            if i == 0:
                bx, by = pts[1]
                pts[i] = list(_best_on_circle_one(cx, cy, r, bx, by))
            elif i == n - 1:
                ax, ay = pts[i - 1]
                pts[i] = list(_best_on_circle_one(cx, cy, r, ax, ay))
            else:
                ax, ay = pts[i - 1]
                bx, by = pts[i + 1]
                pts[i] = list(_best_on_circle_two(cx, cy, r, ax, ay, bx, by))
        cur_len = total_len()
        if abs(prev_len - cur_len) < tol:
            break
        prev_len = cur_len

    latlon = [proj.to_ll(x, y) for x, y in pts]

    # Re-measure legs with the WGS84 geodesic for an accurate reported distance.
    legs: list[float] = []
    for i in range(n - 1):
        legs.append(
            geo.distance(*latlon[i], *latlon[i + 1], model=task.earth_model)
        )
    total = sum(legs)

    cum = [0.0]
    for leg in legs:
        cum.append(cum[-1] + leg)
    to_goal = [total - c for c in cum]

    return OptimizedRoute(points=latlon, legs=legs, total=total, cum_from_start=cum, to_goal=to_goal)
