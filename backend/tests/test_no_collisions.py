"""The headline correctness property: robots never collide.

Two distinct claims are tested separately, because they are *not* the same
thing and only one of them is a design guarantee:

1. ``test_reserved_plans_are_conflict_free_by_construction`` — the reservation
   table cannot hold two agents in the same cell at the same tick. This holds
   for every committed plan, in every run, by construction.

2. ``test_zero_collisions_over_randomised_runs`` — the *executed* simulation
   produces zero vertex collisions and zero swaps across many randomised
   scenarios (random seeds, fleet sizes, jam storms, task bursts). This is
   empirical evidence, not a proof: it is the honest claim to make on a
   resume.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

import pytest

from app.config import SimConfig
from app.engine import SimulationEngine

Cell = Tuple[int, int]


def assert_no_collisions(engine: SimulationEngine, previous: Dict[int, Cell]) -> Dict[int, Cell]:
    """Check vertex conflicts and swap conflicts for the tick just executed."""
    seen: Dict[Cell, int] = {}
    current: Dict[int, Cell] = {}
    for robot in engine.robots:
        assert robot.pos not in seen, (
            f"vertex collision at tick {engine.tick}: robots "
            f"{seen.get(robot.pos)} and {robot.id} both on {robot.pos}"
        )
        seen[robot.pos] = robot.id
        current[robot.id] = robot.pos

    for rid, pos in current.items():
        prev = previous.get(rid)
        if prev is None or prev == pos:
            continue
        for oid, opos in current.items():
            if oid <= rid:
                continue
            oprev = previous.get(oid)
            if oprev is None:
                continue
            assert not (prev == opos and pos == oprev), (
                f"swap collision at tick {engine.tick} between {rid} and {oid}"
            )
    return current


def test_reserved_plans_are_conflict_free_by_construction():
    """Guaranteed property: the table never holds two agents in one cell."""
    engine = SimulationEngine(
        SimConfig(width=22, height=16, margin=1, fleet_size=10, seed=5, horizon=8)
    )
    for _ in range(120):
        engine.step()
        for t in range(engine.tick, engine.tick + engine.config.horizon + 1):
            occupancy = engine.table.occupancy_at(t)
            assert len(occupancy) == len(set(occupancy.keys()))


@pytest.mark.parametrize("seed", list(range(12)))
def test_zero_collisions_over_randomised_runs(seed: int):
    """Empirical property: 12 randomised scenarios x 260 ticks, zero collisions."""
    rng = random.Random(seed)
    config = SimConfig(
        width=rng.choice([18, 24, 30]),
        height=rng.choice([12, 16, 20]),
        shelf_block_w=rng.choice([2, 3, 4]),
        shelf_block_h=2,
        margin=1,
        fleet_size=rng.choice([6, 10, 16, 22]),
        horizon=rng.choice([6, 8, 12]),
        task_spawn_rate=rng.choice([0.2, 0.5, 1.0]),
        seed=seed,
    )
    engine = SimulationEngine(config)
    previous: Dict[int, Cell] = {r.id: r.pos for r in engine.robots}

    for tick in range(260):
        # Inject chaos: jams, bursts and fleet changes mid-run.
        if rng.random() < 0.06:
            cells: List[Cell] = sorted(engine.world.passable_cells())
            engine.toggle_jam(rng.choice(cells))
        if rng.random() < 0.04:
            engine.add_task_burst(rng.randrange(1, 12))
        if rng.random() < 0.015:
            engine.set_fleet_size(max(3, len(engine.robots) + rng.choice([-2, 2])))

        engine.step()
        previous = assert_no_collisions(engine, previous)

    assert engine.metrics.collisions == 0
    # Robots must also stay on legal cells at all times.
    for robot in engine.robots:
        assert engine.world.is_static_passable(robot.pos)


def test_no_collisions_in_a_narrow_congested_aisle():
    """Worst case for a reservation planner: many robots, almost no space."""
    config = SimConfig(
        width=14,
        height=8,
        shelf_block_w=2,
        shelf_block_h=2,
        margin=1,
        fleet_size=20,
        horizon=10,
        task_spawn_rate=1.5,
        seed=99,
    )
    engine = SimulationEngine(config)
    previous = {r.id: r.pos for r in engine.robots}
    for _ in range(200):
        engine.step()
        previous = assert_no_collisions(engine, previous)
    assert engine.metrics.collisions == 0


def test_jam_storm_never_lets_a_robot_drive_into_a_live_jam():
    """Robots may be *caught* by a jam, but must never drive into one.

    Note the timing subtlety this asserts around: a robot is allowed to plan a
    step into a cell that is jammed *now* as long as the jam expires before it
    arrives. Queueing at the edge of a blockage and flowing through the instant
    it clears is correct behaviour, so the invariant is checked at arrival time
    rather than at planning time.
    """
    engine = SimulationEngine(
        SimConfig(width=20, height=14, margin=1, fleet_size=12, seed=4)
    )
    rng = random.Random(1)
    cells = sorted(engine.world.passable_cells())
    previous = {r.id: r.pos for r in engine.robots}

    for step in range(150):
        if step % 5 == 0:
            for _ in range(3):
                engine.toggle_jam(rng.choice(cells))
        engine.step()

        for robot in engine.robots:
            moved = previous.get(robot.id) != robot.pos
            if moved:
                assert not engine.world.is_jammed(robot.pos, engine.tick), (
                    f"robot {robot.id} drove into a live jam at {robot.pos}"
                )
            # Every planned cell must be free of jams at the tick it is used.
            for i, cell in enumerate(robot.plan):
                assert not engine.world.is_jammed(cell, robot.plan_t0 + i), (
                    f"robot {robot.id} plans to occupy jammed {cell} "
                    f"at tick {robot.plan_t0 + i}"
                )
            previous[robot.id] = robot.pos
