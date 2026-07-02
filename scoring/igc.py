"""IGC tracklog parser (clean-room, fixed-column).

IGC is the FAI standard format emitted by flight instruments (XCTrack, Flymaster,
Skytraxx, ...). Records are line-oriented; the first character is the record type.
We only need a handful of record types for scoring:

  A  — flight recorder manufacturer/id (first line)
  H  — headers; we read HFDTE (flight date), HFPLT (pilot), HFGTY/HFGID (glider)
  B  — fix records (the bulk of the file)

B-record layout is **fixed-column** (parse by byte offset, never by splitting):

    B HHMMSS DDMMmmm N DDDMMmmm E V PPPPP GGGGG ...
    0 1      7         15         24 25   30
      |time  |latitude  |longitude  |valid |palt |galt

  * time      cols 1-6   HHMMSS (UTC)
  * latitude  cols 7-14  DDMMmmm + N/S   (mmm = thousandths of a minute)
  * longitude cols 15-23 DDDMMmmm + E/W
  * validity  col 24     'A' = 3D fix, 'V' = 2D/invalid
  * press alt cols 25-29 metres (ICAO 1013.25)
  * gnss alt  cols 30-34 metres (ellipsoidal)

Times in B-records are wall-clock UTC and wrap at midnight. We unwrap them into a
monotonic "seconds since the flight's UTC midnight" axis so downstream integrals
are simple.
"""

from __future__ import annotations

import base64
import json
from datetime import date

from .models import Fix, Track


class IGCParseError(ValueError):
    """Raised when a file cannot be parsed as IGC."""


def _coord(degrees: int, minutes_thousandths: int, hemi: str) -> float:
    """DDMMmmm encoding -> signed decimal degrees.

    ``minutes_thousandths`` is minutes * 1000 (e.g. 30123 == 30.123 minutes).
    """
    deg = degrees + (minutes_thousandths / 1000.0) / 60.0
    if hemi in ("S", "W"):
        deg = -deg
    return deg


def _parse_b_record(line: str) -> tuple[int, float, float, int, int, bool] | None:
    """Parse one B-record. Returns ``None`` for malformed/short lines.

    Returns (utc_seconds_of_day, lat, lon, pressure_alt, gnss_alt, valid).
    """
    if len(line) < 35:
        return None
    try:
        hh = int(line[1:3])
        mm = int(line[3:5])
        ss = int(line[5:7])
        secs = hh * 3600 + mm * 60 + ss

        lat = _coord(int(line[7:9]), int(line[9:14]), line[14])
        lon = _coord(int(line[15:18]), int(line[18:23]), line[23])

        valid = line[24] == "A"
        pressure_alt = int(line[25:30])
        gnss_alt = int(line[30:35])
    except (ValueError, IndexError):
        return None
    return secs, lat, lon, pressure_alt, gnss_alt, valid


def _parse_hfdte(line: str) -> date | None:
    """Parse a flight-date header.

    Two common shapes::

        HFDTE150724                  (legacy: DDMMYY at fixed offset)
        HFDTEDATE:150724,01          (current IGC: DDMMYY after a colon)
    """
    body = line[5:].strip()
    if body.upper().startswith("DATE:"):
        body = body[5:]
    digits = "".join(ch for ch in body if ch.isdigit())
    if len(digits) < 6:
        return None
    dd, mm, yy = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _recover_utf8(s: str) -> str:
    """Recover UTF-8 text read through a latin-1 byte mapping (e.g. Korean names).

    IGC files are parsed as latin-1 so byte offsets stay stable, but header values
    like the pilot name are often UTF-8. Re-encoding to latin-1 bytes and decoding
    as UTF-8 restores them; if that fails the original (likely ASCII) is kept.
    """
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _header_value(line: str) -> str:
    """Extract the value part of an H-record (after the last colon, else after code)."""
    raw = line.split(":", 1)[1].strip() if ":" in line else line[5:].strip()
    return _recover_utf8(raw)


def parse_igc(text: str) -> Track:
    """Parse IGC text into a :class:`Track`.

    Fixes are returned in file order with a monotonic ``time`` axis (seconds since
    the flight's UTC midnight), unwrapping any midnight rollover. Invalid ('V')
    fixes are kept — callers decide whether to use them — but zero/garbage
    coordinate lines that fail to parse are skipped.
    """
    flight_date: date | None = None
    pilot = glider_type = glider_id = fr_id = None
    headers: dict[str, str] = {}
    device_b64: list[str] = []

    raw_fixes: list[tuple[int, float, float, int, int, bool]] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        rec = line[0]

        if rec == "B":
            parsed = _parse_b_record(line)
            if parsed is not None:
                raw_fixes.append(parsed)
        elif rec == "L" and line.startswith("LXCTDEVICE"):
            device_b64.append(line[len("LXCTDEVICE"):].strip())
        elif rec == "H":
            code = line[1:5].upper()
            if code.startswith("FDTE"):
                flight_date = _parse_hfdte(line) or flight_date
            elif code == "FPLT":
                pilot = _header_value(line) or pilot
            elif code == "FGTY":
                glider_type = _header_value(line) or glider_type
            elif code == "FGID":
                glider_id = _header_value(line) or glider_id
            headers[code] = _header_value(line)
        elif rec == "A":
            fr_id = line[1:].strip() or fr_id

    if not raw_fixes:
        raise IGCParseError("No valid B-records found in IGC file")

    # Unwrap midnight rollover: whenever UTC seconds-of-day decreases, add a day.
    fixes: list[Fix] = []
    day_offset = 0
    prev_secs = raw_fixes[0][0]
    for secs, lat, lon, palt, galt, valid in raw_fixes:
        if secs < prev_secs - 1:  # 1s slack for out-of-order jitter
            day_offset += 86400
        prev_secs = secs
        fixes.append(Fix(secs + day_offset, lat, lon, palt, galt, valid))

    glider = " ".join(p for p in (glider_type, glider_id) if p) or None
    timezone = _extract_timezone(device_b64)

    return Track(
        fixes=fixes,
        pilot_name=pilot,
        glider=glider,
        flight_date=flight_date,
        fr_id=fr_id,
        timezone=timezone,
        raw_headers=headers,
    )


def _extract_timezone(device_b64: list[str]) -> str | None:
    """Decode XCTrack's ``LXCTDEVICE`` base64 JSON blob and read the IANA tz name.

    XCTrack splits a base64-encoded device-info JSON across many ``LXCTDEVICE``
    lines. The JSON carries ``{"os": {"timezone": "Asia/Seoul", ...}}``. Best-effort:
    any decode/parse failure simply yields ``None``.
    """
    if not device_b64:
        return None
    blob = "".join(device_b64)
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4))
        data = json.loads(raw.decode("utf-8", errors="ignore"))
    except (ValueError, json.JSONDecodeError):
        return None
    tz = (data.get("os") or {}).get("timezone")
    return tz if isinstance(tz, str) and tz else None


def parse_igc_file(path: str) -> Track:
    """Read and parse an IGC file from disk (latin-1 tolerant)."""
    with open(path, encoding="latin-1") as fh:
        return parse_igc(fh.read())
