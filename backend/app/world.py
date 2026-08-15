"""Warehouse world: static floor plan plus dynamic jam zones.

The layout is generated procedurally but deterministically from the config so
that the visual result reads as a real warehouse (shelf blocks separated by
aisles, pick faces on the shelf ends, dropoff stations along the south wall)
rather than random noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .config import SimConfig

Cell = Tuple[int, int]

FLOOR = 0
SHELF = 1
PICKUP = 2
DROPOFF = 3
CHARGER = 4

CELL_NAMES = {
    FLOOR: "floor",
    SHELF: "shelf",
    PICKUP: "pickup",
    DROPOFF: "dropoff",
    CHARGER: "charger",
}


@dataclass
class Jam:
    """A temporary blockage injected by the operator (or by the demo script)."""

    cell: Cell
    created_tick: int
    expires_tick: int

    def active(self, tick: int) -> bool:
        return self.created_tick <= tick < self.expires_tick


class World:
    """Static warehouse geometry + the dynamic jam overlay.

    Coordinates are ``(x, y)`` with origin at the top-left of the grid.
    """

    def __init__(self, config: SimConfig) -> None:
        self.config = config
        self.width = config.width
        self.height = config.height
        self.grid: List[List[int]] = [
            [FLOOR for _ in range(self.width)] for _ in range(self.height)
        ]
        self.pickups: List[Cell] = []
        self.dropoffs: List[Cell] = []
        self.chargers: List[Cell] = []
        self.jams: Dict[Cell, Jam] = {}
        self._build_layout()
        self._passable_cache: Set[Cell] = {
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if self.grid[y][x] != SHELF
        }

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        cfg = self.config
        m = cfg.margin
        bw, bh = cfg.shelf_block_w, cfg.shelf_block_h
        ax, ay = cfg.aisle_every_x, cfg.aisle_every_y

        # Reserve the two southern rows for dropoff stations and a service lane.
        usable_bottom = self.height - m - 3
        last_shelf_row = m

        y = m
        while y + bh <= usable_bottom:
            x = m
            while x + bw <= self.width - m:
                for yy in range(y, y + bh):
                    for xx in range(x, x + bw):
                        self.grid[yy][xx] = SHELF
                # Pick faces: the aisle cells immediately left and right of the
                # block. These are where robots physically collect an item.
                left = (x - 1, y + bh // 2)
                right = (x + bw, y + bh // 2)
                for face in (left, right):
                    if self._in_bounds(face) and self.grid[face[1]][face[0]] == FLOOR:
                        self.grid[face[1]][face[0]] = PICKUP
                        self.pickups.append(face)
                x += bw + ax
            last_shelf_row = y + bh
            y += bh + ay

        # Trim trailing empty rows so the floor plan has no dead space: the
        # southern service lane is exactly one aisle deep, the dropoff row sits
        # below it, and one approach row closes the floor.
        desired_height = last_shelf_row + 3
        if m < last_shelf_row < self.height and desired_height < self.height:
            self.height = desired_height
            self.grid = self.grid[: self.height]

        # Dropoff stations: evenly spaced along the southern service lane.
        station_y = max(0, self.height - m)
        span = self.width - 2 * m
        count = max(3, span // 9)
        for i in range(count):
            sx = m + int((i + 0.5) * span / count)
            if self._in_bounds((sx, station_y)):
                self.grid[station_y][sx] = DROPOFF
                self.dropoffs.append((sx, station_y))

        # Charger bays along the northern wall, used as idle parking spots.
        for i in range(max(2, count - 1)):
            cx = m + int((i + 0.5) * span / max(2, count - 1))
            cy = m - 1 if m >= 1 else 0
            if self._in_bounds((cx, cy)) and self.grid[cy][cx] == FLOOR:
                self.grid[cy][cx] = CHARGER
                self.chargers.append((cx, cy))

        if not self.pickups:  # tiny grids used in tests
            self.pickups = [c for c in self._free_cells()][: max(1, self.width // 4)]
        if not self.dropoffs:
            self.dropoffs = [c for c in reversed(self._free_cells())][:1]
        if not self.chargers:
            self.chargers = list(self._free_cells())[:1]

    def _free_cells(self) -> List[Cell]:
        return [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if self.grid[y][x] == FLOOR
        ]

    def _in_bounds(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    def in_bounds(self, cell: Cell) -> bool:
        return self._in_bounds(cell)

    def cell_type(self, cell: Cell) -> int:
        x, y = cell
        return self.grid[y][x]

    def is_static_passable(self, cell: Cell) -> bool:
        """Passable ignoring jams (shelves are permanent obstacles)."""
        return self._in_bounds(cell) and self.grid[cell[1]][cell[0]] != SHELF

    def is_jammed(self, cell: Cell, tick: int) -> bool:
        jam = self.jams.get(cell)
        return jam is not None and jam.active(tick)

    def is_passable(self, cell: Cell, tick: int) -> bool:
        """Passable right now: not a shelf and not currently jammed."""
        return self.is_static_passable(cell) and not self.is_jammed(cell, tick)

    def neighbors(self, cell: Cell, tick: int) -> Iterable[Cell]:
        x, y = cell
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if self.is_passable((nx, ny), tick):
                yield (nx, ny)

    def passable_cells(self) -> Set[Cell]:
        return self._passable_cache

    # ------------------------------------------------------------------
    # jams
    # ------------------------------------------------------------------
    def add_jam(self, cell: Cell, tick: int, duration: Optional[int] = None) -> Optional[Jam]:
        """Inject a jam. Returns the jam, or ``None`` if the cell can't jam."""
        if not self.is_static_passable(cell):
            return None
        if self.cell_type(cell) in (DROPOFF, CHARGER):
            return None
        duration = duration if duration is not None else self.config.jam_duration_ticks
        jam = Jam(cell=cell, created_tick=tick, expires_tick=tick + duration)
        self.jams[cell] = jam
        return jam

    def clear_jam(self, cell: Cell) -> None:
        self.jams.pop(cell, None)

    def expire_jams(self, tick: int) -> List[Cell]:
        expired = [c for c, j in self.jams.items() if not j.active(tick)]
        for c in expired:
            del self.jams[c]
        return expired

    def active_jams(self, tick: int) -> List[Jam]:
        return [j for j in self.jams.values() if j.active(tick)]

    # ------------------------------------------------------------------
    # serialisation (sent once, on client connect)
    # ------------------------------------------------------------------
    def to_payload(self) -> Dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            # Row-major type codes; the client renders the static floor once to
            # an offscreen canvas from this array.
            "cells": ["".join(str(v) for v in row) for row in self.grid],
            "pickups": [list(c) for c in self.pickups],
            "dropoffs": [list(c) for c in self.dropoffs],
            "chargers": [list(c) for c in self.chargers],
            "legend": CELL_NAMES,
        }


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
