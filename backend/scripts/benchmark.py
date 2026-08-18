#!/usr/bin/env python3
"""RoboFleet load test.

Measures, for a sweep of fleet sizes, on the real simulation code path:

* throughput in tasks per simulated hour
* per-tick compute time (mean / p50 / p95 / max) in real milliseconds
* how much of the frame budget a tick consumes at the demo tick rate
* collisions (must be zero) and execution-guard interventions

Nothing here is estimated. Every number printed is measured in this process.

Usage
-----
    python scripts/benchmark.py                      # default sweep
    python scripts/benchmark.py --fleets 8 16 32 64  # custom sweep
    python scripts/benchmark.py --ticks 1200 --json out.json --markdown out.md
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
class BenchResult:
    fleet: int
    ticks: int
    wall_seconds: float
    tasks_completed: int
    tasks_per_hour: float
    avg_task_seconds: float
    tick_ms_mean: float
    tick_ms_p50: float
    tick_ms_p95: float
    tick_ms_max: float
    budget_ms: float
    budget_used_pct: float
    max_sustainable_tps: float
    collisions: int
    guard_interventions: int
    failed_plans: int
    replans: int
    utilization: float
    pending_at_end: int


def run_case(
    fleet: int,
    ticks: int,
    warmup: int,
    tps: float,
    spawn_rate: Optional[float],
    seed: int,
) -> BenchResult:
    """Run one fleet size and measure it."""
    # Default to the shipping demand model (auto-scaled per robot, throttled by
    # queue depth) so the benchmark measures the configuration that actually
    # runs in the demo. --spawn-rate pins demand for apples-to-apples sweeps.
    config = SimConfig(
        fleet_size=fleet, task_spawn_rate=spawn_rate, seed=seed, initial_tasks=fleet
    )
    engine = SimulationEngine(config)

    for _ in range(warmup):
        engine.step()

    samples: List[float] = []
    completed_before = engine.metrics.total_completed
    collisions_before = engine.metrics.collisions
    guard_before = engine.metrics.guard_interventions
    failed_before = engine.metrics.failed_plans
    replans_before = engine.metrics.replans

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
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
    budget = 1000.0 / tps
    active = sum(1 for r in engine.robots if r.status != "idle")

    return BenchResult(
        fleet=fleet,
        ticks=ticks,
        wall_seconds=round(wall, 3),
        tasks_completed=completed,
        tasks_per_hour=round(tasks_per_hour, 1),
        avg_task_seconds=round(engine.metrics.avg_cycle_ticks() * config.seconds_per_tick, 1),
        tick_ms_mean=round(statistics.fmean(samples), 3),
        tick_ms_p50=round(p50, 3),
        tick_ms_p95=round(p95, 3),
        tick_ms_max=round(max(samples), 3),
        budget_ms=round(budget, 1),
        budget_used_pct=round(p95 / budget * 100.0, 1),
        max_sustainable_tps=round(1000.0 / p95, 1),
        collisions=engine.metrics.collisions - collisions_before,
        guard_interventions=engine.metrics.guard_interventions - guard_before,
        failed_plans=engine.metrics.failed_plans - failed_before,
        replans=engine.metrics.replans - replans_before,
        utilization=round(active / max(1, len(engine.robots)), 3),
        pending_at_end=len(engine.pending),
    )


def to_markdown(results: List[BenchResult], meta: Dict[str, Any]) -> str:
    lines = [
        "| Fleet | Tasks/hour | Avg task (s) | Tick mean (ms) | Tick p95 (ms) | "
        "Budget used @6Hz | Max tick rate | Collisions | Guard stops |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {r.fleet} | {r.tasks_per_hour:,.0f} | {r.avg_task_seconds} | "
            f"{r.tick_ms_mean} | {r.tick_ms_p95} | {r.budget_used_pct}% | "
            f"{r.max_sustainable_tps} Hz | {r.collisions} | {r.guard_interventions} |"
        )
    lines.append("")
    lines.append(
        f"_Measured on {meta['machine']}, Python {meta['python']}, "
        f"{meta['ticks']} ticks per fleet size after {meta['warmup']} warmup ticks, "
        f"grid {meta['grid']}._"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="RoboFleet benchmark")
    parser.add_argument("--fleets", type=int, nargs="+", default=[4, 8, 16, 24, 32, 48, 64, 96])
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--tps", type=float, default=6.0, help="demo tick rate for budget math")
    parser.add_argument("--spawn-rate", type=float, default=None)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", type=str, default=None)
    parser.add_argument("--markdown", type=str, default=None)
    args = parser.parse_args()

    # Report the *generated* floor size: the layout trims trailing empty rows.
    reference_world = World(SimConfig())
    meta = {
        "machine": f"{platform.machine()} {platform.system()}",
        "python": platform.python_version(),
        "ticks": args.ticks,
        "warmup": args.warmup,
        "grid": f"{reference_world.width}x{reference_world.height}",
        "walkableCells": len(reference_world.passable_cells()),
        "tickRateHz": args.tps,
    }

    print(f"RoboFleet benchmark — {meta['machine']}, Python {meta['python']}")
    print(f"{args.ticks} measured ticks per fleet size (+{args.warmup} warmup)\n")
    header = f"{'fleet':>6} {'tasks/h':>9} {'mean ms':>9} {'p95 ms':>8} {'max Hz':>8} {'coll':>5} {'guard':>6}"
    print(header)
    print("-" * len(header))

    results: List[BenchResult] = []
    for fleet in args.fleets:
        result = run_case(fleet, args.ticks, args.warmup, args.tps, args.spawn_rate, args.seed)
        results.append(result)
        print(
            f"{result.fleet:>6} {result.tasks_per_hour:>9,.0f} {result.tick_ms_mean:>9.3f} "
            f"{result.tick_ms_p95:>8.3f} {result.max_sustainable_tps:>8.1f} "
            f"{result.collisions:>5} {result.guard_interventions:>6}"
        )

    total_collisions = sum(r.collisions for r in results)
    print(f"\nTotal collisions across all runs: {total_collisions}")
    smooth = [r.fleet for r in results if r.budget_used_pct <= 50.0]
    if smooth:
        print(f"Largest fleet under 50% of the {1000/args.tps:.0f}ms tick budget: {max(smooth)} robots")

    peak = max(results, key=lambda r: r.tasks_per_hour)
    print(f"Peak throughput: {peak.tasks_per_hour:,.0f} tasks/h at {peak.fleet} robots")

    payload = {"meta": meta, "results": [asdict(r) for r in results]}
    for target, render in ((args.json, lambda: json.dumps(payload, indent=2)),
                           (args.markdown, lambda: to_markdown(results, meta))):
        if not target:
            continue
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render())
        print(f"wrote {path}")

    return 0 if total_collisions == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
