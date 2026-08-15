"""Space-time reservation table — the heart of collision avoidance.

Model
-----
Time is discrete (ticks) and space is a 4-connected grid. A robot's plan is a
sequence of cells, one per tick, starting at its current position. Before a
plan is committed, every cell it occupies is reserved in *space-time*:

* **Vertex reservation** ``(x, y, t)`` — "robot R occupies cell (x, y) at
  tick t". Two robots can therefore never be scheduled into the same cell at
  the same tick.
* **Edge reservation** ``(u, v, t)`` — "robot R traverses u -> v arriving at
  tick t". Before committing, we check the *reverse* edge ``(v, u, t)``. This
  is what blocks head-on swaps, which vertex reservations alone permit: two
  robots exchanging cells never share a cell at any tick, yet they would pass
  through each other.

What this guarantees
--------------------
Any set of plans that were all committed through :meth:`ReservationTable.commit_path`
is pairwise conflict-free (no shared cell at a shared tick, no swap) for every
tick covered by the reservations. That is a property of the data structure, not
of testing.

What it does *not* guarantee
----------------------------
It does not guarantee that a valid plan exists for every robot, nor that the
system is deadlock-free. Robots that fail to plan hold position, and the engine
applies an independent execution guard (see ``engine.py``) so the *executed*
state transition is collision-free even if a planner ever misbehaves.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Cell = Tuple[int, int]
VertexKey = Tuple[int, int, int]  # x, y, t
EdgeKey = Tuple[int, int, int, int, int]  # x1, y1, x2, y2, t


class ReservationTable:
    """Sparse space-time occupancy map keyed by absolute tick."""

    __slots__ = ("_vertex", "_edge", "_by_agent", "_now")

    def __init__(self) -> None:
        self._vertex: Dict[VertexKey, int] = {}
        self._edge: Dict[EdgeKey, int] = {}
        self._by_agent: Dict[int, List[object]] = {}
        self._now: int = 0

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    def vertex_owner(self, cell: Cell, t: int) -> Optional[int]:
        return self._vertex.get((cell[0], cell[1], t))

    def is_vertex_free(self, cell: Cell, t: int, agent: int) -> bool:
        owner = self._vertex.get((cell[0], cell[1], t))
        return owner is None or owner == agent

    def is_edge_free(self, frm: Cell, to: Cell, t: int, agent: int) -> bool:
        """True if traversing ``frm -> to`` arriving at tick ``t`` is legal.

        Blocks the head-on swap: someone else traversing ``to -> frm`` at the
        same tick.
        """
        if frm == to:
            return True
        owner = self._edge.get((to[0], to[1], frm[0], frm[1], t))
        return owner is None or owner == agent

    def is_move_free(self, frm: Cell, to: Cell, t: int, agent: int) -> bool:
        """Combined vertex+edge check for arriving at ``to`` at tick ``t``."""
        return self.is_vertex_free(to, t, agent) and self.is_edge_free(frm, to, t, agent)

    # ------------------------------------------------------------------
    # mutation
    # ------------------------------------------------------------------
    def can_commit(self, agent: int, path: Sequence[Cell], t0: int) -> bool:
        """Dry-run a commit; used by tests and by defensive engine checks."""
        prev: Optional[Cell] = None
        for i, cell in enumerate(path):
            t = t0 + i
            if not self.is_vertex_free(cell, t, agent):
                return False
            if prev is not None and not self.is_edge_free(prev, cell, t, agent):
                return False
            prev = cell
        return True

    def commit_path(self, agent: int, path: Sequence[Cell], t0: int) -> None:
        """Reserve every space-time cell of ``path`` for ``agent``.

        Raises if any part of the path is already taken — committing must never
        silently overwrite another agent's reservation, otherwise the
        collision-freedom property of the table would be void.
        """
        if not path:
            return
        if not self.can_commit(agent, path, t0):
            raise ValueError(
                "refusing to commit conflicting path for agent %s at t0=%s" % (agent, t0)
            )
        keys: List[object] = self._by_agent.setdefault(agent, [])
        prev: Optional[Cell] = None
        for i, cell in enumerate(path):
            t = t0 + i
            vkey: VertexKey = (cell[0], cell[1], t)
            self._vertex[vkey] = agent
            keys.append(vkey)
            if prev is not None and prev != cell:
                ekey: EdgeKey = (prev[0], prev[1], cell[0], cell[1], t)
                self._edge[ekey] = agent
                keys.append(ekey)
            prev = cell

    def release_agent(self, agent: int) -> None:
        """Drop every reservation held by ``agent`` (called before replanning)."""
        keys = self._by_agent.pop(agent, None)
        if not keys:
            return
        for key in keys:
            if len(key) == 3:  # type: ignore[arg-type]
                if self._vertex.get(key) == agent:  # type: ignore[arg-type]
                    del self._vertex[key]  # type: ignore[arg-type]
            else:
                if self._edge.get(key) == agent:  # type: ignore[arg-type]
                    del self._edge[key]  # type: ignore[arg-type]

    def advance_to(self, now: int) -> None:
        """Expire reservations strictly in the past. Keeps the table bounded."""
        if now <= self._now:
            self._now = now
            return
        self._now = now
        stale_v = [k for k in self._vertex if k[2] < now]
        for k in stale_v:
            del self._vertex[k]
        stale_e = [k for k in self._edge if k[4] < now]
        for k in stale_e:
            del self._edge[k]
        for agent, keys in list(self._by_agent.items()):
            kept = [k for k in keys if (k[2] if len(k) == 3 else k[4]) >= now]  # type: ignore[index]
            if kept:
                self._by_agent[agent] = kept
            else:
                del self._by_agent[agent]

    def clear(self) -> None:
        self._vertex.clear()
        self._edge.clear()
        self._by_agent.clear()

    # ------------------------------------------------------------------
    # introspection (tests, metrics)
    # ------------------------------------------------------------------
    def agents(self) -> Iterable[int]:
        return self._by_agent.keys()

    def occupancy_at(self, t: int) -> Dict[Cell, int]:
        return {(k[0], k[1]): v for k, v in self._vertex.items() if k[2] == t}

    def __len__(self) -> int:
        return len(self._vertex)

    def stats(self) -> Dict[str, int]:
        return {
            "vertex_reservations": len(self._vertex),
            "edge_reservations": len(self._edge),
            "agents": len(self._by_agent),
        }
