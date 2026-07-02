"""Reproduce & diagnose the 남부리그 4차전 scoring discrepancy (goal/ESS false-positive).

Drop the real files into ``samples/nambu4/``:
  - one ``*.xctsk`` task file ("2일차-양산-말양-운문")
  - the pilot IGC tracks (``*.igc`` / ``*.IGC``) — 박진택 required, full field ideal

Then run:
  .venv/bin/python scripts/repro_nambu4.py                 # score the whole field
  .venv/bin/python scripts/repro_nambu4.py --pilot jin     # per-fix tagging trace for one track

The trace shows, fix by fix, when each turnpoint (…→ESS→GOAL) gets tagged and the
distance-to-centre vs radius at that moment — so we can see exactly why a pilot who
landed short is being credited with goal.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scoring.igc import parse_igc                       # noqa: E402
from scoring.task import parse_xctsk                    # noqa: E402
from scoring.params import gap2023_korea                # noqa: E402
from scoring.result import Competitor, score_competition  # noqa: E402
from scoring import geo                                 # noqa: E402
from scoring.validate import analyze, _dist, _reached   # noqa: E402

FIX_DIR = ROOT / "samples" / "nambu4"


def _load_task() -> object:
    tasks = sorted(FIX_DIR.glob("*.xctsk")) + sorted(FIX_DIR.glob("*.json"))
    if not tasks:
        sys.exit(f"과제 파일(.xctsk)이 없습니다 → {FIX_DIR} 에 넣어주세요.")
    print(f"[task] {tasks[0].name}")
    return parse_xctsk(tasks[0].read_text(encoding="utf-8"))


def _load_igcs() -> list[tuple[str, object]]:
    igcs = sorted(FIX_DIR.glob("*.igc")) + sorted(FIX_DIR.glob("*.IGC"))
    if not igcs:
        sys.exit(f"IGC 파일이 없습니다 → {FIX_DIR} 에 넣어주세요.")
    out = []
    for f in igcs:
        tr = parse_igc(f.read_text(encoding="latin-1"))
        out.append((f.stem, tr))
    return out


def score_field(task) -> None:
    comps = []
    for stem, tr in _load_igcs():
        a = analyze(tr, task)
        comps.append(Competitor(pilot_id=stem, name=tr.pilot_name or stem,
                                 analysis=a, bib=(tr.raw_headers.get("FCID") or "").strip() or None,
                                 glider=tr.glider))
    r = score_competition(comps, gap2023_korea(), num_present=len(comps))
    print(f"\nnum_flying={r.num_flying} num_in_goal={r.num_in_goal} "
          f"best_dist_km={r.best_distance/1000:.2f} best_time={r.best_time}")
    print(f"pool: dist={r.pool.distance:.1f} time={r.pool.time:.1f} lead={r.pool.leading:.1f}")
    print(f"\n{'#':>2} {'name':16}{'dist_km':>8}{'goal':>5}{'ess':>4}{'dp':>8}{'tp':>8}{'lp':>8}{'total':>9}")
    for p in r.results:
        print(f"{p.rank:>2} {p.name[:15]:16}{p.distance/1000:8.2f}{str(p.in_goal)[0]:>5}"
              f"{str(p.reached_ess)[0]:>4}{p.distance_points:8.1f}{p.time_points:8.1f}"
              f"{p.leading_points:8.1f}{p.total:9.1f}")


def trace_pilot(task, needle: str) -> None:
    """Re-walk the tagging loop for the matching track, printing every tag decision."""
    match = [(s, t) for s, t in _load_igcs() if needle.lower() in s.lower()]
    if not match:
        sys.exit(f"'{needle}' 를 포함하는 IGC를 찾지 못했습니다.")
    stem, tr = match[0]
    a = analyze(tr, task)
    model = task.earth_model
    tps = task.turnpoints
    print(f"[trace] {stem}  → in_goal={a.in_goal} reached_ess={a.reached_ess} "
          f"dist_km={a.distance_flown/1000:.2f} ss_elapsed={a.ss_elapsed}")
    print("\ncourse turnpoints:")
    for i, tp in enumerate(tps):
        print(f"  [{i}] {tp.kind.value:8} r={tp.radius:>7.0f} {tp.name or ''}")
    print("\ntagged (from analyze):")
    for ev in a.tags:
        print(f"  idx={ev.index} {ev.kind.value:8} @t={ev.time}  {ev.name}")
    # closest approach of the track to ESS and GOAL centres
    ess = next((tp for tp in tps if tp.kind.value == "ess"), None)
    goal = next((tp for tp in tps if tp.kind.value == "goal"), None)
    for label, tp in (("ESS", ess), ("GOAL", goal)):
        if tp is None:
            continue
        dmin = min(_dist(fx, tp, model) for fx in tr.fixes)
        print(f"\n{label} {tp.name}: radius={tp.radius:.0f}m  트랙 최근접={dmin:.0f}m  "
              f"→ 진입? {'예' if dmin <= tp.radius else '아니오'}")


if __name__ == "__main__":
    task = _load_task()
    if len(sys.argv) >= 3 and sys.argv[1] == "--pilot":
        trace_pilot(task, sys.argv[2])
    else:
        score_field(task)
