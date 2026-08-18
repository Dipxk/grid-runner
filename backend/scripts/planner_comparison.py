#!/usr/bin/env python3
"""Compare windowed space-time WHCA* vs a reservation-free baseline planner.

Both planners share identical scenario inputs. The only intentional difference is
whether future vertex/edge space-time reservations are committed during planning.

Held constant
-------------
* map layout and seed
* fleet size and initial task backlog
* task allocator and demand model (``tasks_per_robot_per_tick``)
* planning horizon and replan refresh triggers
* execution guard and runtime verifier
* warmup and measured tick window

Differs
-------
* **whca** — space-time A* with vertex + edge reservations
* **baseline** — spatial A* segments, no future reservations; guard resolves conflicts
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SimConfig  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.experiments import build_run_record, experiment_store_from_env  # noqa: E402
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
    failed_plans: int
    collisions: int
    avg_route_length: float
    avg_distance_per_task: float


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return "unknown"


def _spawn_rate(fleet: int) -> float:
    return fleet * SimConfig().tasks_per_robot_per_tick


def run_mode(
    planner: str,
    fleet: int,
    ticks: int,
    warmup: int,
    seed: int,
) -> PlannerRun:
    config = SimConfig(
        fleet_size=fleet,
        seed=seed,
        planner_mode=planner,
        initial_tasks=fleet,
        task_spawn_rate=_spawn_rate(fleet),
    )
    engine = SimulationEngine(config)

    for _ in range(warmup):
        engine.step()

    blocked_before = sum(r.blocked_ticks for r in engine.robots)
    completed_before = engine.metrics.total_completed
    guard_before = engine.metrics.guard_interventions
    replans_before = engine.metrics.replans
    collisions_before = engine.metrics.collisions
    failed_before = engine.metrics.failed_plans
    distance_before = sum(r.distance_travelled for r in engine.robots)
    route_sum_before = sum(max(0, len(r.plan) - 1) for r in engine.robots)

    samples: List[float] = []
    started = time.perf_counter()
    route_samples: List[int] = []
    for _ in range(ticks):
        t0 = time.perf_counter()
        engine.step()
        samples.append((time.perf_counter() - t0) * 1000.0)
        route_samples.append(sum(max(0, len(r.plan) - 1) for r in engine.robots))
    wall = time.perf_counter() - started

    completed = engine.metrics.total_completed - completed_before
    sim_seconds = ticks * config.seconds_per_tick
    tasks_per_hour = completed * 3600.0 / sim_seconds if sim_seconds else 0.0
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
    distance_delta = sum(r.distance_travelled for r in engine.robots) - distance_before
    avg_route = statistics.fmean(route_samples) if route_samples else 0.0

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
        failed_plans=engine.metrics.failed_plans - failed_before,
        collisions=engine.metrics.collisions - collisions_before,
        avg_route_length=round(avg_route, 2),
        avg_distance_per_task=round(distance_delta / max(1, completed), 2),
    )


def to_markdown(runs: List[PlannerRun], meta: Dict[str, Any]) -> str:
    lines = [
        "# Planner comparison — WHCA* vs baseline",
        "",
        "## Methodology",
        "",
        "Identical seeded scenarios; shared allocator, horizon, replan triggers, "
        "demand model, execution guard, warmup, and measurement window.",
        "",
        "| Held constant | Value |",
        "| --- | --- |",
        f"| Seed | {meta['seed']} |",
        f"| Warmup ticks | {meta['warmup']} |",
        f"| Measured ticks | {meta['ticks']} |",
        f"| Horizon | {meta['horizon']} |",
        f"| Demand | fleet × {meta['demandPerRobot']} tasks/tick |",
        "",
        "| Differs | WHCA* | Baseline |",
        "| --- | --- | --- |",
        "| Planner | space-time A* + reservations | spatial A*, no reservations |",
        "| Conflict handling | reserved windows | execution guard at runtime |",
        "",
        "| Planner | Fleet | Tasks/h | Avg task (s) | Tick mean | Tick p95 | "
        "Guard | Blocked | Replans | Failed | Collisions | Avg route | Dist/task |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in runs:
        lines.append(
            f"| {r.planner} | {r.fleet} | {r.tasks_per_hour:,.0f} | {r.avg_task_seconds} | "
            f"{r.tick_ms_mean} | {r.tick_ms_p95} | {r.guard_interventions} | "
            f"{r.blocked_ticks} | {r.replans} | {r.failed_plans} | {r.collisions} | "
            f"{r.avg_route_length} | {r.avg_distance_per_task} |"
        )
    lines.extend(
        [
            "",
            f"_Measured on {meta['machine']}, Python {meta['python']}, grid {meta['grid']}._",
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
    parser.add_argument("--store", action="store_true", help="Persist summaries to ExperimentStore")
    args = parser.parse_args()

    reference_world = World(SimConfig())
    cfg = SimConfig()
    meta = {
        "machine": f"{platform.machine()} {platform.system()}",
        "python": platform.python_version(),
        "ticks": args.ticks,
        "warmup": args.warmup,
        "seed": args.seed,
        "grid": f"{reference_world.width}x{reference_world.height}",
        "horizon": cfg.horizon,
        "demandPerRobot": cfg.tasks_per_robot_per_tick,
        "git_commit": _git_commit(),
    }

    print(f"Planner comparison — {meta['machine']}, Python {meta['python']}")
    print(f"WHCA* vs baseline on seed {args.seed} (fair replan + demand parity)\n")

    store = experiment_store_from_env() if args.store else None
    runs: List[PlannerRun] = []
    for fleet in args.fleets:
        for planner in ("whca", "baseline"):
            result = run_mode(planner, fleet, args.ticks, args.warmup, args.seed)
            runs.append(result)
            print(
                f"{planner:>8} fleet={fleet:>2}  tasks/h={result.tasks_per_hour:>6,.0f}  "
                f"guard={result.guard_interventions:>4}  failed={result.failed_plans:>4}  "
                f"coll={result.collisions}"
            )
            if store is not None:
                store.save_run(
                    build_run_record(
                        scenario="planner_comparison",
                        planner=planner,
                        fleet_size=fleet,
                        seed=args.seed,
                        git_commit=meta["git_commit"],
                        tasks_completed=result.tasks_completed,
                        tasks_per_hour=result.tasks_per_hour,
                        tick_mean_ms=result.tick_ms_mean,
                        tick_p95_ms=result.tick_ms_p95,
                        guard_interventions=result.guard_interventions,
                        collisions=result.collisions,
                        replans=result.replans,
                        failed_plans=result.failed_plans,
                        avg_route_length=result.avg_route_length,
                        avg_distance_per_task=result.avg_distance_per_task,
                    )
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
