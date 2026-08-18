"""Planner comparison fairness tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SimConfig
from app.engine import SimulationEngine
from app.models import RobotStatus
from scripts.planner_comparison import run_mode


def test_planner_baseline_uses_same_scenario_inputs():
    seed = 23
    fleet = 12
    whca = run_mode("whca", fleet, ticks=80, warmup=20, seed=seed)
    baseline = run_mode("baseline", fleet, ticks=80, warmup=20, seed=seed)
    assert whca.fleet == baseline.fleet
    assert whca.collisions == 0
    assert baseline.collisions == 0
    assert baseline.guard_interventions >= whca.guard_interventions


def test_baseline_replans_use_refresh_gate_not_every_tick():
    eng = SimulationEngine(
        SimConfig(fleet_size=6, seed=5, planner_mode="baseline", task_spawn_rate=0.0, initial_tasks=0)
    )
    for robot in eng.robots:
        robot.status = RobotStatus.IDLE
        robot.plan = [robot.pos] * (eng.config.horizon + 1)
        robot.plan_t0 = eng.tick
    before = eng.metrics.replans
    eng.step()
    assert eng.metrics.replans == before
