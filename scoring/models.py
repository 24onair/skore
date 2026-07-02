"""Core data models for tracks and tasks.

These are plain dataclasses with no scoring logic — they are the shared vocabulary
used by the parser (``igc.py``), task import (``task.py``), the optimizer
(``optimize.py``), the validator (``validate.py``) and the scorer (``gap.py``).

Coordinates are WGS84 decimal degrees. Altitudes are metres. Times are seconds
since UTC midnight of the flight's start date unless noted otherwise — keeping a
single monotonic seconds axis makes day-quality / leading-coefficient integrals
straightforward and sidesteps timezone math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


# --------------------------------------------------------------------------- #
# Track (parsed from an IGC file)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Fix:
    """A single GPS fix from an IGC B-record."""

    time: int           # seconds since UTC midnight of the flight date (rollover-corrected)
    lat: float          # WGS84 decimal degrees
    lon: float          # WGS84 decimal degrees
    pressure_alt: int   # metres (ICAO 1013.25 datum); 0 if not recorded
    gnss_alt: int       # metres (GNSS/ellipsoidal); 0 if not recorded
    valid: bool         # B-record validity byte: True for a 3D ('A') fix

    @property
    def alt(self) -> int:
        """Best available altitude — prefer GNSS, fall back to pressure."""
        return self.gnss_alt or self.pressure_alt


@dataclass(slots=True)
class Track:
    """A pilot's flight: an ordered, time-monotonic sequence of fixes."""

    fixes: list[Fix]
    pilot_name: str | None = None
    glider: str | None = None
    flight_date: date | None = None
    fr_id: str | None = None          # flight recorder / device id (IGC A-record)
    timezone: str | None = None       # IANA tz from the device (e.g. "Asia/Seoul"), if known
    raw_headers: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:  # convenience
        return len(self.fixes)

    @property
    def start_time(self) -> int | None:
        return self.fixes[0].time if self.fixes else None

    @property
    def end_time(self) -> int | None:
        return self.fixes[-1].time if self.fixes else None


# --------------------------------------------------------------------------- #
# Task definition
# --------------------------------------------------------------------------- #
class TurnpointKind(str, Enum):
    """Role of a turnpoint within the task."""

    TAKEOFF = "takeoff"
    SSS = "sss"          # Start of Speed Section
    TURNPOINT = "turnpoint"
    ESS = "ess"          # End of Speed Section
    GOAL = "goal"


class GoalType(str, Enum):
    CYLINDER = "cylinder"
    LINE = "line"


class StartDirection(str, Enum):
    """How the SSS cylinder must be crossed to register a valid start."""

    EXIT = "exit"        # pilot must leave the cylinder (most common)
    ENTER = "enter"      # pilot must enter the cylinder


class TaskType(str, Enum):
    RACE_TO_GOAL = "race_to_goal"
    ELAPSED_TIME = "elapsed_time"   # Phase 3
    OPEN_DISTANCE = "open_distance"  # Phase 3


@dataclass(frozen=True, slots=True)
class Turnpoint:
    """A waypoint with a cylinder radius. Lat/lon is the cylinder centre."""

    lat: float
    lon: float
    radius: float                 # metres
    kind: TurnpointKind = TurnpointKind.TURNPOINT
    name: str = ""
    altitude: float = 0.0         # centre ground altitude (m), informational
    goal_type: GoalType = GoalType.CYLINDER  # only meaningful for GOAL turnpoints


@dataclass(slots=True)
class Task:
    """A Race-to-Goal task definition.

    ``turnpoints`` is the ordered course including SSS/ESS/Goal markers. The
    start gate is expressed in seconds since UTC midnight to match :class:`Fix`.
    """

    turnpoints: list[Turnpoint]
    start_time: int                       # SSS opening time (s since UTC midnight)
    task_type: TaskType = TaskType.RACE_TO_GOAL
    start_direction: StartDirection = StartDirection.EXIT
    task_deadline: int | None = None      # task close time (s); None = no deadline
    earth_model: str = "wgs84"            # "wgs84" | "fai_sphere" (see DECISIONS D2)
    name: str = ""

    # --- convenience accessors for the special turnpoints --------------------
    def _first(self, kind: TurnpointKind) -> Turnpoint | None:
        return next((t for t in self.turnpoints if t.kind == kind), None)

    @property
    def sss(self) -> Turnpoint | None:
        return self._first(TurnpointKind.SSS)

    @property
    def ess(self) -> Turnpoint | None:
        return self._first(TurnpointKind.ESS)

    @property
    def goal(self) -> Turnpoint | None:
        return self._first(TurnpointKind.GOAL)

    @property
    def has_goal(self) -> bool:
        return self.goal is not None
