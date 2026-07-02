"""Geodesy helpers (WGS84 via GeographicLib, MIT).

All distances are in metres along the WGS84 ellipsoid geodesic, matching modern
CIVL/Airscore practice (see DECISIONS D2). A legacy FAI-sphere mode is provided
for cross-checking against older official results.
"""

from __future__ import annotations

import math

from geographiclib.geodesic import Geodesic

_WGS84 = Geodesic.WGS84
FAI_SPHERE_RADIUS = 6_371_000.0  # metres


def distance(lat1: float, lon1: float, lat2: float, lon2: float, *, model: str = "wgs84") -> float:
    """Geodesic distance in metres between two WGS84 points."""
    if model == "fai_sphere":
        return _haversine(lat1, lon1, lat2, lon2)
    return _WGS84.Inverse(lat1, lon1, lat2, lon2)["s12"]


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on the FAI sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * FAI_SPHERE_RADIUS * math.asin(min(1.0, math.sqrt(a)))


def destination(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Point reached by travelling ``dist_m`` from (lat, lon) on ``bearing_deg``."""
    r = _WGS84.Direct(lat, lon, bearing_deg, dist_m)
    return r["lat2"], r["lon2"]


def point_on_segment_nearest(
    plat: float, plon: float, alat: float, alon: float, blat: float, blon: float
) -> tuple[float, float, float]:
    """Closest point on geodesic segment A→B to point P.

    Returns (lat, lon, distance_to_P_metres). Uses a small planar approximation in
    a local tangent frame, which is accurate at task scale (cylinder radii).
    """
    # Local equirectangular projection centred on A (metres).
    coslat = math.cos(math.radians(alat))
    m_per_deg = 111_320.0

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        return ((lon - alon) * m_per_deg * coslat, (lat - alat) * m_per_deg)

    px, py = to_xy(plat, plon)
    ax, ay = 0.0, 0.0
    bx, by = to_xy(blat, blon)

    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    cx, cy = ax + t * dx, ay + t * dy

    clat = alat + cy / m_per_deg
    clon = alon + cx / (m_per_deg * coslat)
    d = distance(plat, plon, clat, clon)
    return clat, clon, d
