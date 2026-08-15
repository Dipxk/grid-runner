"""Unit tests for windowed space-time A*."""

from __future__ import annotations

from app.config import SimConfig
from app.pathfinding import plan_path, static_path
from app.reservation import ReservationTable
from app.world import World


def make_world(**kwargs) -> World:
    cfg = SimConfig(width=16, height=12, shelf_block_w=2, shelf_block_h=2, margin=1, **kwargs)
    return World(cfg)


def test_path_starts_at_start_and_covers_full_window():
    world = make_world()
    table = ReservationTable()
    start = (0, 0)
    goal = (0, 5)
    result = plan_path(world, table, agent=1, start=start, goal=goal, t0=0, horizon=8)
    assert result is not None
    assert result.path[0] == start
    # Full-window coverage is what makes reservations gap-free.
    assert len(result.path) == 9


def test_path_never_enters_a_shelf():
    world = make_world()
    table = ReservationTable()
    result = plan_path(world, table, agent=1, start=(0, 0), goal=(15, 11), t0=0, horizon=30)
    assert result is not None
    for cell in result.path:
        assert world.is_static_passable(cell)


def test_planner_respects_existing_reservations():
    world = make_world()
    table = ReservationTable()
    # Agent 1 parks in a corridor cell for the whole window.
    blocked = [(3, 0)] * 9
    table.commit_path(agent=1, path=blocked, t0=0)

    result = plan_path(world, table, agent=2, start=(0, 0), goal=(6, 0), t0=0, horizon=8)
    assert result is not None
    for i, cell in enumerate(result.path):
        assert not (cell == (3, 0)), "planner walked through a reserved cell"
        assert table.can_commit(2, result.path, 0)
        break


def test_committed_plans_are_mutually_conflict_free():
    world = make_world()
    table = ReservationTable()
    starts = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1)]
    goals = [(10, 5), (9, 5), (8, 5), (10, 6), (9, 6)]
    for agent, (s, g) in enumerate(zip(starts, goals)):
        result = plan_path(world, table, agent=agent, start=s, goal=g, t0=0, horizon=10)
        assert result is not None
        table.commit_path(agent, result.path, 0)

    for t in range(11):
        occupancy = table.occupancy_at(t)
        assert len(occupancy) == len(starts)  # every agent has exactly one cell


def test_planner_routes_around_a_jam():
    world = make_world()
    table = ReservationTable()
    baseline = plan_path(world, table, agent=1, start=(0, 4), goal=(6, 4), t0=0, horizon=12)
    assert baseline is not None
    assert (3, 4) in baseline.path or (2, 4) in baseline.path

    for cell in [(x, 4) for x in range(1, 6)]:
        world.add_jam(cell, tick=0, duration=50)
    rerouted = plan_path(world, table, agent=1, start=(0, 4), goal=(6, 4), t0=0, horizon=12)
    assert rerouted is not None
    for cell in rerouted.path[1:]:
        assert not world.is_jammed(cell, 1)


def test_partial_plan_when_goal_is_outside_the_window():
    world = make_world()
    table = ReservationTable()
    result = plan_path(world, table, agent=1, start=(0, 0), goal=(15, 11), t0=0, horizon=3)
    assert result is not None
    assert result.complete is False
    assert len(result.path) == 4
    # A partial plan must still make progress toward the goal.
    assert abs(result.path[-1][0] - 15) + abs(result.path[-1][1] - 11) < 15 + 11


def test_static_path_matches_manhattan_on_open_floor():
    world = make_world()
    path = static_path(world, (0, 0), (0, 5))
    assert path is not None
    assert len(path) == 6
