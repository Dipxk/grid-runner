"""Windowed space-time A* (WHCA*-style) over the reservation table.

The planner searches states ``(x, y, t)`` where ``t`` is an absolute tick.
Successors are the four grid moves plus an explicit *wait*. A successor is only
expanded if the reservation table says the cell **and** the traversal edge are
free at that tick, so any path returned is conflict-free against every plan
already committed.

Rolling horizon
---------------
Reservations are expensive to hold forever, and a robot's goal often lies far
outside the window, so the search is bounded to ``horizon`` ticks. Three
outcomes are possible:

1. **Complete** — the goal is reached inside the window *and* the robot can sit
   on the goal for the remaining ticks. The path is padded with waits so the
   whole window is reserved.
2. **Partial** — the goal is not reachable inside the window; the best frontier
   state (lowest heuristic, then lowest cost) is used. The robot makes real
   progress and replans when the window slides.
3. **Failed** — not even waiting in place is legal. The caller decides what to
   do (hold position without reservations; the engine's execution guard keeps
   that safe).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .reservation import ReservationTable
from .world import World, manhattan

Cell = Tuple[int, int]
State = Tuple[int, int, int]  # x, y, t


@dataclass
class PlanResult:
    """Outcome of a single planning call."""

    path: List[Cell]
    complete: bool
    expansions: int
    reached_goal_at: Optional[int] = None

    def __bool__(self) -> bool:
        return bool(self.path)


def plan_path(
    world: World,
    table: ReservationTable,
    agent: int,
    start: Cell,
    goal: Cell,
    t0: int,
    horizon: int,
    max_expansions: int = 6000,
    wait_cost: float = 1.05,
) -> Optional[PlanResult]:
    """Plan a conflict-free window for ``agent`` from ``start`` at tick ``t0``.

    The returned path always starts at ``start`` and has ``horizon + 1`` entries
    (index ``i`` is the cell occupied at tick ``t0 + i``), so committing it
    covers the entire window with no gaps.

    Returns ``None`` when even holding position is impossible.
    """
    if start == goal:
        held = _hold(world, table, agent, start, t0, horizon)
        if held is not None:
            return PlanResult(path=held, complete=True, expansions=0, reached_goal_at=t0)

    t_end = t0 + horizon

    # The start vertex must be free for us at t0 (it always is: the engine
    # releases the agent's own reservations before replanning and no other
    # robot may be standing on us).
    if not table.is_vertex_free(start, t0, agent):
        return None

    open_heap: List[Tuple[float, float, int, State]] = []
    came_from: Dict[State, State] = {}
    g_score: Dict[State, float] = {}

    start_state: State = (start[0], start[1], t0)
    g_score[start_state] = 0.0
    h0 = float(manhattan(start, goal))
    counter = 0
    heapq.heappush(open_heap, (h0, h0, counter, start_state))

    best_frontier: Optional[State] = None
    best_key: Tuple[float, float] = (float("inf"), float("inf"))
    expansions = 0

    while open_heap:
        _f, _h, _c, state = heapq.heappop(open_heap)
        x, y, t = state
        g = g_score[state]
        expansions += 1
        if expansions > max_expansions:
            break

        h = float(manhattan((x, y), goal))
        # Track the most promising state we could actually stop at.
        key = (h, g)
        if t == t_end and key < best_key:
            best_key = key
            best_frontier = state

        if (x, y) == goal:
            # Goal reached — try to park here for the rest of the window.
            path = _reconstruct(came_from, state, start_state)
            tail = _hold(world, table, agent, (x, y), t, t_end - t)
            if tail is not None:
                full = path + tail[1:]
                return PlanResult(
                    path=full, complete=True, expansions=expansions, reached_goal_at=t
                )
            # Cannot idle on the goal (someone else routes through it later);
            # keep searching for a later arrival.

        if t >= t_end:
            continue

        nt = t + 1
        # Wait action first (cheap to validate), then the four moves.
        successors: List[Tuple[Cell, float]] = [((x, y), wait_cost)]
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            successors.append((nxt, 1.0))

        for cell, step_cost in successors:
            if cell != (x, y):
                if not world.is_passable(cell, nt):
                    continue
            else:
                # Standing still on a cell that just became jammed is not
                # allowed — the robot must leave.
                if not world.is_static_passable(cell) or world.is_jammed(cell, nt):
                    continue
            if not table.is_vertex_free(cell, nt, agent):
                continue
            if not table.is_edge_free((x, y), cell, nt, agent):
                continue
            nstate: State = (cell[0], cell[1], nt)
            ng = g + step_cost
            if ng < g_score.get(nstate, float("inf")):
                g_score[nstate] = ng
                came_from[nstate] = state
                nh = float(manhattan(cell, goal))
                counter += 1
                heapq.heappush(open_heap, (ng + nh, nh, counter, nstate))

    if best_frontier is not None:
        path = _reconstruct(came_from, best_frontier, start_state)
        return PlanResult(path=path, complete=False, expansions=expansions)

    # No frontier state survived to the end of the window: fall back to holding
    # position for as long as it is legal, then bail.
    held = _hold(world, table, agent, start, t0, horizon)
    if held is not None and len(held) > 1:
        return PlanResult(path=held, complete=False, expansions=expansions)
    return None


def _hold(
    world: World,
    table: ReservationTable,
    agent: int,
    cell: Cell,
    t0: int,
    ticks: int,
) -> Optional[List[Cell]]:
    """Return a wait-in-place path covering ``[t0, t0+ticks]``, or ``None``."""
    if ticks < 0:
        return None
    path = [cell]
    for i in range(1, ticks + 1):
        t = t0 + i
        if world.is_jammed(cell, t) or not world.is_static_passable(cell):
            return None
        if not table.is_vertex_free(cell, t, agent):
            return None
        path.append(cell)
    return path


def _reconstruct(came_from: Dict[State, State], state: State, start: State) -> List[Cell]:
    cells: List[Cell] = []
    cur = state
    while cur != start:
        cells.append((cur[0], cur[1]))
        cur = came_from[cur]
    cells.append((start[0], start[1]))
    cells.reverse()
    return cells


def static_path(world: World, start: Cell, goal: Cell, tick: int = 0) -> Optional[List[Cell]]:
    """Plain A* ignoring other robots — used for distance estimates and tests."""
    if start == goal:
        return [start]
    open_heap: List[Tuple[float, int, Cell]] = []
    counter = 0
    heapq.heappush(open_heap, (float(manhattan(start, goal)), counter, start))
    came: Dict[Cell, Cell] = {}
    cost: Dict[Cell, float] = {start: 0.0}
    while open_heap:
        _f, _c, cur = heapq.heappop(open_heap)
        if cur == goal:
            out = [cur]
            while cur != start:
                cur = came[cur]
                out.append(cur)
            out.reverse()
            return out
        for nxt in world.neighbors(cur, tick):
            ng = cost[cur] + 1.0
            if ng < cost.get(nxt, float("inf")):
                cost[nxt] = ng
                came[nxt] = cur
                counter += 1
                heapq.heappush(open_heap, (ng + manhattan(nxt, goal), counter, nxt))
    return None
