"""Fault injection, recovery, and resilience scenario tests."""

from __future__ import annotations

import random

import pytest

from app.allocator import apply_assignment
from app.config import SimConfig
from app.engine import RESILIENCE_TEST, SimulationEngine
from app.faults import FaultState, FaultType
from app.models import RobotStatus, TaskState


@pytest.fixture
def engine():
    cfg = SimConfig(fleet_size=8, seed=11, initial_tasks=4, task_spawn_rate=0.0)
    return SimulationEngine(cfg)


def _positions(engine: SimulationEngine):
    return [r.pos for r in engine.robots]


def _run_resilience():
    spec = RESILIENCE_TEST
    eng = SimulationEngine(
        SimConfig(
            fleet_size=spec["fleet"],
            seed=spec["seed"],
            initial_tasks=spec["initial_tasks"],
            task_spawn_rate=0.08,
        )
    )
    eng.begin_resilience_test()
    snapshots = []
    for _ in range(spec["duration"] + 30):
        snapshots.append(eng.step())
    return eng, snapshots


def test_offline_robot_releases_future_reservations(engine):
    robot = engine.robots[0]
    engine.table.commit_path(robot.id, [robot.pos, (robot.pos[0] + 1, robot.pos[1])], engine.tick)
    assert engine.table.is_vertex_free((robot.pos[0] + 1, robot.pos[1]), engine.tick + 1, robot.id + 1) is False
    engine.inject_fault(robot.id, FaultType.ROBOT_OFFLINE.value)
    assert engine.table.is_vertex_free((robot.pos[0] + 1, robot.pos[1]), engine.tick + 1, robot.id + 1) is True


def test_unpicked_task_is_reassigned_after_robot_failure(engine):
    if not engine.pending:
        engine._spawn_task(rush=True)
    apply = engine.allocator.allocate(engine.robots, engine.pending, engine.tick)
    assert apply
    robot, task = apply[0]
    apply_assignment(robot, task, engine.tick)
    engine.pending.remove(task)
    before = robot.pos
    engine.inject_fault(robot.id, FaultType.ROBOT_OFFLINE.value)
    assert task.state == TaskState.PENDING
    assert task in engine.pending
    assert robot.task is None
    for _ in range(20):
        engine.step()
    assert robot.pos == before


def test_task_reassigned_after_pre_pickup_offline_failure(engine):
    test_unpicked_task_is_reassigned_after_robot_failure(engine)


def test_offline_robot_never_moves(engine):
    robot = engine.robots[1]
    start = robot.pos
    engine.inject_fault(robot.id, FaultType.ROBOT_OFFLINE.value)
    for _ in range(30):
        engine.step()
    assert robot.pos == start


def test_slow_robot_never_breaks_collision_invariant(engine):
    engine.inject_fault(engine.robots[2].id, FaultType.SLOW_ROBOT.value, {"stride": 3})
    for _ in range(120):
        engine.step()
    assert engine.metrics.collisions == 0


def test_planner_failure_causes_safe_hold(engine):
    robot = engine.robots[3]
    engine.inject_fault(robot.id, FaultType.PLANNER_FAILURE.value, {"hold_ticks": 12})
    engine.step()
    assert robot.plan == [robot.pos]
    assert engine.faults.is_planner_blocked(robot.id, engine.tick)


def test_robot_recovers_after_planner_failure(engine):
    robot = engine.robots[4]
    engine.inject_fault(robot.id, FaultType.PLANNER_FAILURE.value, {"hold_ticks": 4})
    for _ in range(6):
        engine.step()
    engine.clear_fault(robot.id)
    for _ in range(40):
        engine.step()
    rec = engine.faults._record(robot.id)
    assert rec.recovery_count >= 1
    assert rec.fault_state == FaultState.NORMAL


def test_planner_failure_recovers_after_retry(engine):
    test_robot_recovers_after_planner_failure(engine)


def test_fault_recovery_is_deterministic():
    def run(seed: int):
        eng = SimulationEngine(SimConfig(fleet_size=6, seed=seed, initial_tasks=2, task_spawn_rate=0.0))
        eng.inject_fault(0, FaultType.ROBOT_OFFLINE.value)
        eng.clear_fault(0)
        for _ in range(40):
            eng.step()
        return eng.metrics.total_completed, eng.faults.successful_recoveries, _positions(eng)

    assert run(5) == run(5)


def test_ci_fast_suite_is_deterministic():
    a = SimulationEngine(SimConfig(fleet_size=6, seed=3, initial_tasks=2, task_spawn_rate=0.0))
    b = SimulationEngine(SimConfig(fleet_size=6, seed=3, initial_tasks=2, task_spawn_rate=0.0))
    for _ in range(25):
        a.step()
        b.step()
    assert a.metrics.collisions == b.metrics.collisions == 0
    assert _positions(a) == _positions(b)


def test_fault_storm_produces_zero_collisions():
    eng = SimulationEngine(SimConfig(fleet_size=12, seed=99, initial_tasks=8, task_spawn_rate=0.05))
    rng = random.Random(99)
    for tick in range(200):
        if tick % 17 == 0:
            rid = rng.randrange(len(eng.robots))
            ftype = rng.choice(list(FaultType)).value
            eng.inject_fault(rid, ftype, {"stride": 3, "hold_ticks": 5, "delay_ticks": 3})
        if tick % 23 == 0 and eng.faults.active_faults():
            eng.clear_fault(rng.choice(eng.robots).id)
        eng.step()
    assert eng.metrics.collisions == 0


def test_fault_recovery_preserves_zero_collision_invariant(engine):
    test_fault_storm_produces_zero_collisions()


def test_resilience_scenario_finishes_without_collision():
    eng, _ = _run_resilience()
    assert eng.metrics.collisions == 0
    assert eng.faults.faults_injected >= 3


def test_resilience_schedule_injects_expected_faults():
    eng, snaps = _run_resilience()
    injected = []
    for snap in snaps:
        for ev in snap.get("events") or []:
            if ev.get("type") == "fault_detected":
                injected.append((ev.get("tick", snap["tick"]), ev["robot"], ev["fault"]))
    assert (40, 7, "robot_offline") in injected
    assert any(t == 70 and r == 14 and f == "slow_robot" for t, r, f in injected)
    assert any(t == 100 and r == 19 and f == "planner_failure" for t, r, f in injected)


def test_resilience_schedule_clears_expected_faults():
    eng, snaps = _run_resilience()
    cleared = []
    recovered = []
    for snap in snaps:
        for ev in snap.get("events") or []:
            if ev.get("type") == "recovery_started":
                cleared.append((ev.get("tick", snap["tick"]), ev["robot"]))
            if ev.get("type") == "recovery_completed":
                recovered.append((ev.get("tick", snap["tick"]), ev["robot"]))
    assert (58, 7) in cleared
    assert (90, 14) in cleared
    assert (110, 19) in cleared
    assert any(r == 7 for _, r in recovered)
    assert any(r == 14 for _, r in recovered)
    assert any(r == 19 for _, r in recovered)


def test_offline_robot_returns_to_normal_after_restore():
    eng, _ = _run_resilience()
    rec = eng.faults._record(7)
    assert rec.recovery_count >= 1
    assert rec.fault_state == FaultState.NORMAL
    assert rec.health.value == "healthy"
    assert eng.robots[7].operational is True


def test_slow_robot_returns_to_normal_after_clear():
    eng, _ = _run_resilience()
    rec = eng.faults._record(14)
    assert rec.fault_state == FaultState.NORMAL
    assert rec.active is None


def test_recovery_metrics_only_count_completed_recoveries():
    eng, _ = _run_resilience()
    sc = eng.scenario
    assert sc is not None
    assert sc["faultsRecovered"] >= 3
    assert sc["faultsRecovered"] == eng.faults.successful_recoveries - sc["startRecoveries"]
    for rid in (7, 14, 19):
        assert eng.faults._record(rid).recovery_count >= 1


def test_recovery_latency_is_measured_from_actual_state_transition():
    eng, _ = _run_resilience()
    rec = eng.faults._record(7)
    assert rec.recovery_started_tick is not None
    assert rec.recovery_completed_tick is not None
    assert rec.recovery_completed_tick >= rec.recovery_started_tick
    assert eng.faults.mean_recovery_ticks() > 0


def test_carrying_failure_enters_recovery_required(engine):
    if not engine.pending:
        engine._spawn_task()
    assigned = engine.allocator.allocate(engine.robots, engine.pending, engine.tick)
    assert assigned
    robot, task = assigned[0]
    apply_assignment(robot, task, engine.tick)
    engine.pending.remove(task)
    task.state = TaskState.CARRIED
    robot.status = RobotStatus.CARRYING
    engine.inject_fault(robot.id, FaultType.ROBOT_OFFLINE.value)
    assert task.state == TaskState.RECOVERY_REQUIRED
    assert robot.task is None


def test_metrics_report_real_fault_counts(engine):
    engine.inject_fault(0, FaultType.ROBOT_OFFLINE.value)
    engine.inject_fault(1, FaultType.SLOW_ROBOT.value, {"stride": 2})
    engine.step()
    snap = engine.snapshot()
    assert snap["metrics"]["faultsInjected"] >= 2
    assert snap["metrics"]["robotsOffline"] >= 1
