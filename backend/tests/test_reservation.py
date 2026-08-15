"""Unit tests for the space-time reservation table."""

from __future__ import annotations

import pytest

from app.reservation import ReservationTable


def test_vertex_reservation_blocks_other_agent():
    table = ReservationTable()
    table.commit_path(agent=1, path=[(0, 0), (1, 0), (2, 0)], t0=0)

    assert not table.is_vertex_free((1, 0), 1, agent=2)
    assert table.is_vertex_free((1, 0), 1, agent=1)      # owner may re-plan
    assert table.is_vertex_free((1, 0), 5, agent=2)      # different tick is fine


def test_edge_reservation_blocks_head_on_swap():
    table = ReservationTable()
    # Agent 1 goes right: (0,0) -> (1,0) arriving at t=1.
    table.commit_path(agent=1, path=[(0, 0), (1, 0)], t0=0)
    # Agent 2 attempting (1,0) -> (0,0) at t=1 never shares a cell with agent 1
    # at any tick, yet the two would pass through each other.
    assert not table.is_edge_free((1, 0), (0, 0), 1, agent=2)
    assert table.is_edge_free((1, 0), (1, 1), 1, agent=2)


def test_commit_refuses_conflicting_path():
    table = ReservationTable()
    table.commit_path(agent=1, path=[(0, 0), (1, 0)], t0=0)
    with pytest.raises(ValueError):
        table.commit_path(agent=2, path=[(1, 1), (1, 0)], t0=0)


def test_release_agent_frees_everything_it_held():
    table = ReservationTable()
    table.commit_path(agent=1, path=[(0, 0), (1, 0), (1, 1)], t0=0)
    assert len(table) == 3
    table.release_agent(1)
    assert len(table) == 0
    table.commit_path(agent=2, path=[(0, 0), (1, 0), (1, 1)], t0=0)  # now legal


def test_advance_expires_the_past_only():
    table = ReservationTable()
    table.commit_path(agent=1, path=[(0, 0), (1, 0), (2, 0), (3, 0)], t0=0)
    table.advance_to(2)
    assert table.is_vertex_free((0, 0), 0, agent=2)     # expired
    assert not table.is_vertex_free((2, 0), 2, agent=2)  # still held
    assert not table.is_vertex_free((3, 0), 3, agent=2)


def test_waiting_in_place_is_allowed_and_reserved():
    table = ReservationTable()
    table.commit_path(agent=1, path=[(4, 4), (4, 4), (4, 4)], t0=10)
    assert not table.is_vertex_free((4, 4), 11, agent=2)
    # A wait creates no edge, so a neighbour may still traverse past it.
    assert table.is_edge_free((3, 4), (3, 5), 11, agent=2)


def test_no_two_agents_ever_share_a_reserved_cell():
    """Property check over many committed paths."""
    import random

    rng = random.Random(3)
    table = ReservationTable()
    committed = 0
    for agent in range(60):
        x, y = rng.randrange(0, 12), rng.randrange(0, 12)
        path = [(x, y)]
        for _ in range(rng.randrange(1, 9)):
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (0, 0)])
            path.append((path[-1][0] + dx, path[-1][1] + dy))
        if table.can_commit(agent, path, 0):
            table.commit_path(agent, path, 0)
            committed += 1

    assert committed > 5
    for t in range(12):
        occupancy = table.occupancy_at(t)
        assert len(occupancy) == len(set(occupancy.keys()))
