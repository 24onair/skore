"""GAP scoring parameters.

These are the competition-configurable values a meet director sets, plus the
fixed polynomial constants from the CIVL GAP formula. Defaults follow the GAP
2021/2022 PG convention (arrival points OFF, distance difficulty HG-only).

⚠️ UNVERIFIED: the polynomial constants and the nominal defaults were taken from
the GlideAngle/CIVL-GAP source, not yet diffed against the FAI S7F 2024 PDF or a
real scored competition (see DECISIONS D1). Treat absolute scores as provisional
until calibrated against golden fixtures. Structure is correct; constants may
need a one-line tweak each.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ScoringParams:
    # --- meet-director configurable (per task / per comp) --------------------
    nominal_launch: float = 0.0       # fraction expected to launch; 0 => launch validity = 1
    nominal_distance: float = 30_000  # NomDist, metres
    nominal_time: float = 3_600       # NomTime, seconds
    nominal_goal: float = 0.20        # NomGoal, fraction of pilots expected in goal
    min_distance: float = 5_000       # MinDist, metres — everyone flying is credited at least this

    # --- discipline switches -------------------------------------------------
    arrival_points: bool = False      # PG / PWCA: arrival OFF
    leading_points: bool = True       # leading points on

    # --- GAP2023 Leading-Time-Ratio (splits the non-distance pool) -----------
    # LeadingWeight = (1-DistanceWeight)·LTR ; TimeWeight = (1-DistanceWeight)·(1-LTR).
    # FS default 0.26; the 2026 남부리그 golden task used ≈0.3539.
    leading_time_ratio: float = 0.26

    # --- leading-coefficient normalisation -----------------------------------
    leading_time_ref: float = 1_800.0  # PWCA reference (s) in LC = ∫g·dt / (1800·SS_km)


def gap2023_korea() -> "ScoringParams":
    """Preset matching the 2025~2026 남부리그 FS GAP2023 settings (golden fixture)."""
    return ScoringParams(
        nominal_launch=0.96,
        nominal_distance=30_000,
        nominal_time=5_400,      # 1.5 h
        nominal_goal=0.25,
        min_distance=7_000,
        leading_time_ratio=0.353866,
    )
