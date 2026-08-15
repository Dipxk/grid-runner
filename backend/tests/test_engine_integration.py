"""Integration tests: task allocation, lifecycle, event injection, metrics."""

from __future__ import annotations

from app.config import SimConfig
from app.engine import SimulationEngine
from app.models import RobotStatus, TaskState


def test_tasks_get_assigned_and_completed(engine: SimulationEngine):
    engine.run(220)
    completed = [t for t in engine.tasks.values() if t.state == TaskState.DONE]
    assert completed, "no task ever completed"
    for task in completed:
        assert task.assigned_tick is not None
        assert task.picked_tick is not None
        assert task.done_tick is not None
        assert task.created_tick <= task.assigned_tick <= task.picked_tick <= task.done_tick
    assert engine.metrics.total_completed == len(completed)


def test_robot_lifecycle_visits_pickup_then_dropoff(engine: SimulationEngine):
    seen_pickup = False
    seen_carrying = False
    for _ in range(240):
        engine.step()
        for robot in engine.robots:
            if robot.status == RobotStatus.TO_PICKUP:
                seen_pickup = True
            if robot.status == RobotStatus.CARRYING:
                seen_carrying = True
                assert robot.task is not None
                assert robot.task.state == TaskState.CARRIED
    assert seen_pickup and seen_carrying


def test_idle_robots_pick_up_new_work_after_a_burst(engine: SimulationEngine):
    engine.run(30)
    before = engine.metrics.total_completed
    created = engine.add_task_burst(25)
    assert created == 25
    engine.run(200)
    assert engine.metrics.total_completed > before
    assert any(r.task is not None for r in engine.robots)


def test_burst_increases_throughput(small_config: SimConfig):
    quiet = SimulationEngine(small_config.replace(task_spawn_rate=0.0, initial_tasks=2))
    quiet.run(200)

    busy = SimulationEngine(small_config.replace(task_spawn_rate=0.0, initial_tasks=2))
    busy.add_task_burst(40)
    busy.run(200)

    assert busy.metrics.total_completed > quiet.metrics.total_completed


def test_jam_forces_a_reroute(engine: SimulationEngine):
    engine.run(40)
    # Find a robot with a real plan and jam the cell it is about to use.
    target = None
    for robot in engine.robots:
        if len(robot.plan) > 3:
            target = robot
            break
    assert target is not None
    blocked_cell = target.plan[2]
    reroutes_before = target.reroutes

    result = engine.toggle_jam(blocked_cell)
    assert result["ok"] and result["action"] == "added"
    assert target.reroutes == reroutes_before + 1
    assert target.plan == []  # plan was invalidated immediately

    engine.step()
    assert blocked_cell not in target.plan or engine.world.is_jammed(blocked_cell, engine.tick) is False


def test_jam_toggles_off_and_expires(engine: SimulationEngine):
    engine.run(10)
    cell = sorted(engine.world.passable_cells())[len(engine.world.passable_cells()) // 2]
    assert engine.toggle_jam(cell, duration=6)["action"] == "added"
    assert engine.world.is_jammed(cell, engine.tick)
    assert engine.toggle_jam(cell)["action"] == "cleared"
    assert not engine.world.is_jammed(cell, engine.tick)

    engine.toggle_jam(cell, duration=5)
    engine.run(8)
    assert not engine.world.is_jammed(cell, engine.tick)


def test_fleet_resize_keeps_simulation_consistent(engine: SimulationEngine):
    engine.run(40)
    assert engine.set_fleet_size(14) == 14
    assert len({r.id for r in engine.robots}) == 14
    assert len({r.pos for r in engine.robots}) == 14  # no two robots stacked
    engine.run(40)

    assert engine.set_fleet_size(5) == 5
    engine.run(40)
    assert len(engine.robots) == 5
    assert engine.metrics.collisions == 0


def test_metrics_are_measured_not_invented(engine: SimulationEngine):
    engine.run(150)
    snapshot = engine.snapshot()
    metrics = snapshot["metrics"]

    assert metrics["tickComputeMs"] > 0
    assert metrics["tasksCompleted"] == engine.metrics.total_completed
    assert metrics["collisions"] == 0
    assert 0 <= metrics["utilization"] <= 1
    assert metrics["fleetSize"] == len(engine.robots)
    assert len(metrics["throughputHistory"]) > 0
    if metrics["tasksCompleted"] > 0:
        assert metrics["tasksPerHour"] > 0
        assert metrics["avgTaskSeconds"] > 0


def test_snapshot_payload_shape_matches_client_expectations(engine: SimulationEngine):
    engine.run(25)
    snapshot = engine.snapshot()
    assert snapshot["type"] == "tick"
    robot = snapshot["robots"][0]
    for key in ("id", "x", "y", "status", "facing", "path", "stats", "queue"):
        assert key in robot
    assert robot["status"] in RobotStatus.ALL
    # Paths must be relative to the robot's current cell and 4-connected.
    for r in snapshot["robots"]:
        cells = [(r["x"], r["y"])] + [tuple(c) for c in r["path"]]
        for a, b in zip(cells, cells[1:]):
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1


def test_determinism_same_seed_same_history(small_config: SimConfig):
    a = SimulationEngine(small_config)
    b = SimulationEngine(small_config)
    a.run(120)
    b.run(120)
    assert [r.pos for r in a.robots] == [r.pos for r in b.robots]
    assert a.metrics.total_completed == b.metrics.total_completed


def test_events_are_emitted_and_drained(engine: SimulationEngine):
    engine.run(120)
    snapshot = engine.snapshot()
    kinds = {e["type"] for e in snapshot["events"]} if snapshot["events"] else set()
    engine.run(1)
    # Events are drained by each snapshot so clients never replay them twice.
    assert isinstance(kinds, set)
    engine.add_task_burst(3)
    snap2 = engine.snapshot()
    assert any(e["type"] == "burst" for e in snap2["events"])
    assert all(e["type"] != "burst" for e in engine.snapshot()["events"])


def test_dense_fleet_keeps_delivering_and_never_deadlocks():
    """Regression: a crowded floor used to funnel into one dropoff and lock up.

    Before dropoff rebalancing + step-aside recovery, 75 robots settled into a
    standoff around a single station: throughput fell ~25x and dozens of robots
    stood still for the rest of the run. This asserts the floor keeps flowing.
    """
    config = SimConfig(fleet_size=75, task_spawn_rate=1.4, seed=17, initial_tasks=75)
    engine = SimulationEngine(config)
    engine.run(200)  # warm up past the initial rush

    before = engine.metrics.total_completed
    engine.run(600)
    delivered = engine.metrics.total_completed - before

    assert engine.metrics.collisions == 0
    # Deadlocked runs delivered <40 here; healthy runs clear several hundred.
    assert delivered > 300, f"throughput collapsed: {delivered} deliveries in 600 ticks"
    worst_stuck = max(r.stuck_ticks for r in engine.robots)
    assert worst_stuck < 60, f"a robot stood still for {worst_stuck} ticks"


def test_loaded_robots_spread_across_dropoff_stations():
    """Deliveries should use every bay, not pile into the nearest one."""
    config = SimConfig(fleet_size=60, task_spawn_rate=1.2, seed=5, initial_tasks=60)
    engine = SimulationEngine(config)
    engine.run(400)

    used = {tuple(r.task.dropoff) for r in engine.robots if r.task is not None}
    stations = {tuple(c) for c in engine.world.dropoffs}
    assert len(used & stations) >= min(3, len(stations)), f"only {used} in use"
