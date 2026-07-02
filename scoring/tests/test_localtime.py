"""Tests for timezone extraction and local-time offset resolution."""

import base64
import json
from datetime import date

from scoring.igc import parse_igc
from scoring.localtime import offset_from_longitude, offset_from_timezone, resolve_offset
from scoring.models import Task, Turnpoint, TurnpointKind


def test_offset_from_timezone_seoul():
    # Korea has no DST: always +9h.
    assert offset_from_timezone("Asia/Seoul", date(2026, 6, 28)) == 9 * 3600


def test_offset_from_timezone_dst_aware():
    # Central Europe: +1h in winter, +2h in summer (DST).
    assert offset_from_timezone("Europe/Zurich", date(2024, 1, 15)) == 3600
    assert offset_from_timezone("Europe/Zurich", date(2024, 7, 15)) == 7200


def test_offset_from_longitude():
    assert offset_from_longitude(129.1) == 9 * 3600
    assert offset_from_longitude(8.0) == 3600


def test_igc_extracts_timezone():
    blob = base64.b64encode(json.dumps({"os": {"timezone": "Asia/Seoul"}}).encode()).decode()
    # split across two LXCTDEVICE lines like XCTrack does
    mid = len(blob) // 2
    igc = (
        "HFDTEDATE:280626,01\n"
        f"LXCTDEVICE {blob[:mid]}\n"
        f"LXCTDEVICE {blob[mid:]}\n"
        "B0254054550000N00650000EA0080000900\n"
    )
    track = parse_igc(igc)
    assert track.timezone == "Asia/Seoul"


def test_resolve_offset_prefers_timezone():
    blob = base64.b64encode(json.dumps({"os": {"timezone": "Asia/Seoul"}}).encode()).decode()
    igc = (
        "HFDTEDATE:280626,01\n"
        f"LXCTDEVICE {blob}\n"
        "B0254054550000N00650000EA0080000900\n"
    )
    track = parse_igc(igc)
    task = Task(turnpoints=[Turnpoint(35.7, 129.1, 0, TurnpointKind.GOAL)], start_time=0)
    off, label = resolve_offset(track, task)
    assert off == 9 * 3600
    assert label == "Asia/Seoul"


def test_resolve_offset_longitude_fallback():
    igc = "HFDTEDATE:280626,01\nB0254054550000N00650000EA0080000900\n"
    track = parse_igc(igc)  # no LXCTDEVICE -> no timezone
    task = Task(turnpoints=[Turnpoint(35.7, 129.1, 0, TurnpointKind.GOAL)], start_time=0)
    off, label = resolve_offset(track, task)
    assert off == 9 * 3600
    assert label == "UTC+09:00"
