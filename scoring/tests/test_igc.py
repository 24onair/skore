"""Tests for the IGC parser."""

from datetime import date

import pytest

from scoring.igc import IGCParseError, parse_igc

# A tiny synthetic IGC: header date 15 Jul 2024 + a few B-records near Chamonix.
SAMPLE = """\
AXCT XCTrack
HFDTEDATE:150724,01
HFPLTPILOTINCHARGE:Jane Pilot
HFGTYGLIDERTYPE:Ozone Zeno
HFGIDGLIDERID:D-1234
B1200004550000N00650000EA0080000900
B1200304550500N00650500EA0081000910
B1201004551000N00651000EV0082000920
"""


def test_parses_headers_and_fixes():
    track = parse_igc(SAMPLE)
    assert track.flight_date == date(2024, 7, 15)
    assert track.pilot_name == "Jane Pilot"
    assert track.glider == "Ozone Zeno D-1234"
    assert len(track) == 3


def test_coordinate_decoding():
    track = parse_igc(SAMPLE)
    f = track.fixes[0]
    # 4550.000 N -> 45 + 50/60 deg ; 00650.000 E -> 6 + 50/60 deg
    assert f.lat == pytest.approx(45 + 50 / 60, abs=1e-6)
    assert f.lon == pytest.approx(6 + 50 / 60, abs=1e-6)
    assert f.pressure_alt == 800
    assert f.gnss_alt == 900
    assert f.valid is True


def test_validity_byte():
    track = parse_igc(SAMPLE)
    assert track.fixes[2].valid is False  # 'V' record


def test_time_axis_seconds_of_day():
    track = parse_igc(SAMPLE)
    assert track.fixes[0].time == 12 * 3600
    assert track.fixes[1].time == 12 * 3600 + 30
    assert track.fixes[2].time == 12 * 3600 + 60


def test_midnight_rollover():
    igc = (
        "HFDTEDATE:150724,01\n"
        "B2359504550000N00650000EA0080000900\n"  # 23:59:50
        "B0000104550500N00650500EA0081000910\n"  # 00:00:10 next day
    )
    track = parse_igc(igc)
    assert track.fixes[0].time == 23 * 3600 + 59 * 60 + 50
    # rolled over: previous + 20s, crossing into the next day
    assert track.fixes[1].time == track.fixes[0].time + 20


def test_legacy_hfdte():
    igc = "HFDTE150724\nB1200004550000N00650000EA0080000900\n"
    track = parse_igc(igc)
    assert track.flight_date == date(2024, 7, 15)


def test_empty_raises():
    with pytest.raises(IGCParseError):
        parse_igc("HFDTEDATE:150724,01\n")
