"""Serialize engine objects into JSON-friendly dicts for the API/UI."""

from __future__ import annotations

from scoring.models import Task, Track
from scoring.result import CompetitionResult
from scoring.validate import TrackAnalysis

_MAX_FIXES = 1500  # downsample track for map rendering


def track_to_dict(track: Track) -> dict:
    fixes = track.fixes
    step = max(1, len(fixes) // _MAX_FIXES)
    pts = [[round(f.lat, 6), round(f.lon, 6)] for f in fixes[::step]]
    return {
        "pilot": track.pilot_name,
        "glider": track.glider,
        "flight_date": track.flight_date.isoformat() if track.flight_date else None,
        "fix_count": len(fixes),
        "points": pts,
    }


def task_to_dict(task: Task) -> dict:
    return {
        "name": task.name,
        "start_time": task.start_time,
        "task_type": task.task_type.value,
        "start_direction": task.start_direction.value,
        "earth_model": task.earth_model,
        "task_deadline": task.task_deadline,
        "turnpoints": [
            {
                "lat": round(t.lat, 6),
                "lon": round(t.lon, 6),
                "radius": t.radius,
                "kind": t.kind.value,
                "name": t.name,
                "goal_type": t.goal_type.value,
            }
            for t in task.turnpoints
        ],
    }


def analysis_to_dict(res: TrackAnalysis) -> dict:
    route = res.route
    return {
        "started": res.started,
        "start_time": res.start_time,
        "in_goal": res.in_goal,
        "reached_ess": res.reached_ess,
        "ess_time": res.ess_time,
        "goal_time": res.goal_time,
        "landing_time": res.landing_time,
        "distance_km": round(res.distance_km, 2),
        "task_distance_km": round(res.task_distance / 1000.0, 2),
        "ss_elapsed": res.ss_elapsed,
        "speed_kmh": round(res.speed_kmh, 2) if res.speed_kmh else None,
        "tags": [
            {"index": t.index, "name": t.name, "kind": t.kind.value, "time": t.time}
            for t in res.tags
        ],
        "route": {
            "points": [[round(la, 6), round(lo, 6)] for la, lo in route.points] if route else [],
            "total_km": round(route.total / 1000.0, 2) if route else 0.0,
        },
    }


def competition_to_dict(res: CompetitionResult) -> dict:
    q = res.day_quality
    pool = res.pool
    return {
        "task_distance_km": round(res.task_distance / 1000.0, 2),
        "num_flying": res.num_flying,
        "num_present": res.num_present,
        "num_in_goal": res.num_in_goal,
        "best_distance_km": round(res.best_distance / 1000.0, 2),
        "best_time": res.best_time,
        "day_quality": {
            "launch": round(q.launch, 4),
            "distance": round(q.distance, 4),
            "time": round(q.time, 4),
            "quality": round(q.quality, 4),
        },
        "pool": {
            "available": round(pool.available, 1),
            "distance": round(pool.distance, 1),
            "time": round(pool.time, 1),
            "leading": round(pool.leading, 1),
            "arrival": round(pool.arrival, 1),
        },
        "results": [
            {
                "rank": r.rank,
                "pilot_id": r.pilot_id,
                "name": r.name,
                "bib": r.bib,
                "glider": r.glider,
                "distance_km": round(r.distance / 1000.0, 2),
                "in_goal": r.in_goal,
                "reached_ess": r.reached_ess,
                "ss_time": r.ss_time,
                "distance_points": round(r.distance_points, 1),
                "time_points": round(r.time_points, 1),
                "leading_points": round(r.leading_points, 1),
                "total": round(r.total, 1),
            }
            for r in res.results
        ],
    }
