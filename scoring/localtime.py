"""Local-time helpers for display.

The engine works entirely in UTC seconds (elapsed times are timezone-independent,
so scoring is unaffected). Only the *display* of absolute clock times needs an
offset — competition times are read in the local timezone of the flying site.

Offset resolution, in order:
  1. the IANA timezone recorded by the device (e.g. XCTrack's "Asia/Seoul"),
     evaluated on the flight date so DST is handled correctly;
  2. a longitude-based estimate (``round(lon / 15)`` hours) from the task — a
     reasonable display fallback when no tz is known (ignores DST).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Task, Track


def offset_from_timezone(tzname: str, on: date) -> int | None:
    """UTC offset in seconds for ``tzname`` on date ``on`` (None if unknown tz)."""
    try:
        tz = ZoneInfo(tzname)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    dt = datetime(on.year, on.month, on.day, 12, tzinfo=tz)
    off = dt.utcoffset()
    return int(off.total_seconds()) if off is not None else None


def offset_from_longitude(lon: float) -> int:
    """Rough standard-time offset (seconds) from a longitude."""
    return round(lon / 15.0) * 3600


def resolve_offset(track: Track, task: Task) -> tuple[int, str]:
    """Return (utc_offset_seconds, label) for display.

    ``label`` is the IANA tz name when available, else a ``UTC±HH:MM`` string.
    """
    on = track.flight_date or date(2000, 1, 1)
    if track.timezone:
        off = offset_from_timezone(track.timezone, on)
        if off is not None:
            return off, track.timezone

    lon = task.turnpoints[0].lon if task.turnpoints else 0.0
    off = offset_from_longitude(lon)
    sign = "+" if off >= 0 else "-"
    a = abs(off)
    return off, f"UTC{sign}{a // 3600:02d}:{(a % 3600) // 60:02d}"
