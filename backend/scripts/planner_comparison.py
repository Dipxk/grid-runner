#!/usr/bin/env python3
"""Compare windowed space-time WHCA* vs a reservation-free baseline planner.

Both modes run on identical seeded scenarios so differences reflect planner
architecture, not random layout variation. The baseline still passes through
the execution guard so benchmarking stays controlled even when plans conflict.

Usage
-----
    python scripts/planner_comparison.py
    python scripts/planner_comparison.py --fleets 16 32 --ticks 800 \\
        --json ../benchmarks/planner_comparison.json \\
        --markdown ../benchmarks/planner_comparison.md
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SimConfig  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.world import World  # noqa: E402


@dataclass
class PlannerRun:
    planner: str
    fleet: int
    ticks: int
    wall_seconds: float
    tasks_completed: int
    tasks_per_hour: float
    avg_task_seconds: float
    tick_ms_mean: float
    tick_ms_p95: float
    guard_interventions: int
    blocked_ticks: int
    replans: int
    collisions: int
    failed_plans: int


def run_mode(
    planner: str,
    fleet: int,
    ticks: int,
    warmup: int,
    seed: int,
) -> PlannerRun:
    config = SimConfig(fleet_size=fleet, seed=seed, planner_mode=planner, initial_tasks=fleet)
    engine = SimulationEngine(config)

    for _ in range(warmup):
        engine.step()

    blocked_before = sum(r.blocked_ticks for r in engine.robots)
    completed_before = engine.metrics.total_completed
    guard_before = engine.metrics.guard_interventions
    replans_before = engine.metrics.replans
    collisions_before = engine.metrics.collisions
    failed_before = engine.metrics.failed_plans

    samples: List[float] = []
    started = time.perf_counter()
    for _ in range(ticks):
        t0 = time.perf_counter()
        engine.step()
        samples.append((time.perf_counter() - t0) * 1000.0)
    wall = time.perf_counter() - started

    completed = engine.metrics.total_completed - completed_before
    sim_seconds = ticks * config.seconds_per_tick
    tasks_per_hour = completed * 3600.0 / sim_seconds if sim_seconds else 0.0
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]

    return PlannerRun(
        planner=planner,
        fleet=fleet,
        ticks=ticks,
        wall_seconds=round(wall, 3),
        tasks_completed=completed,
        tasks_per_hour=round(tasks_per_hour, 1),
        avg_task_seconds=round(engine.metrics.avg_cycle_ticks() * config.seconds_per_tick, 1),
        tick_ms_mean=round(statistics.fmean(samples), 3),
        tick_ms_p95=round(p95, 3),
        guard_interventions=engine.metrics.guard_interventions - guard_before,
        blocked_ticks=sum(r.blocked_ticks for r in engine.robots) - blocked_before,
        replans=engine.metrics.replans - replans_before,
        collisions=engine.metrics.collisions - collisions_before,
        failed_plans=engine.metrics.failed_plans - failed_before,
    )


def to_markdown(runs: List[PlannerRun], meta: Dict[str, Any]) -> str:
    lines = [
        "# Planner comparison — WHCA* vs baseline",
        "",
        "Controlled comparison on identical seeds. **WHCA*** uses vertex + edge "
        "space-time reservations; **baseline** uses independent spatial A* with "
        "execution-guard conflict resolution only.",
        "",
        "| Planner | Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | "
        "Guard stops | Blocked ticks | Replans | Collisions |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in runs:
        lines.append(
            f"| {r.planner} | {r.fleet} | {r.tasks_per_hour:,.0f} | {r.avg_task_seconds} | "
            f"{r.tick_ms_mean} | {r.tick_ms_p95} | {r.guard_interventions} | "
            f"{r.blocked_ticks} | {r.replans} | {r.collisions} |"
        )
    lines.extend(
        [
            "",
            f"_Measured on {meta['machine']}, Python {meta['python']}, "
            f"{meta['ticks']} ticks per run after {meta['warmup']} warmup ticks, "
            f"seed {meta['seed']}, grid {meta['grid']}._",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Grid Runner planner comparison")
    parser.add_argument("--fleets", type=int, nargs="+", default=[16, 32])
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", type=str, default=None)
    parser.add_argument("--markdown", type=str, default=None)
    args = parser.parse_args()

    reference_world = World(SimConfig())
    meta = {
        "machine": f"{platform.machine()} {platform.system()}",
        "python": platform.python_version(),
        "ticks": args.ticks,
        "warmup": args.warmup,
        "seed": args.seed,
        "grid": f"{reference_world.width}x{reference_world.height}",
    }

    print(f"Planner comparison — {meta['machine']}, Python {meta['python']}")
    print(f"WHCA* (whca) vs reservation-free baseline on seed {args.seed}\n")

    runs: List[PlannerRun] = []
    for fleet in args.fleets:
        for planner in ("whca", "baseline"):
            result = run_mode(planner, fleet, args.ticks, args.warmup, args.seed)
            runs.append(result)
            print(
                f"{planner:>8} fleet={fleet:>2}  tasks/h={result.tasks_per_hour:>6,.0f}  "
                f"p95={result.tick_ms_p95:>7.2f}ms  guard={result.guard_interventions:>4}  "
                f"coll={result.collisions}"
            )

    payload = {"meta": meta, "runs": [asdict(r) for r in runs]}
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nWrote {args.json}")
    if args.markdown:
        Path(args.markdown).write_text(to_markdown(runs, meta) + "\n")
        print(f"Wrote {args.markdown}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
