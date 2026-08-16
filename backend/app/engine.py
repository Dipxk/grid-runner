"""Simulation engine: one deterministic tick at a time.

Tick pipeline
-------------
1. **Expire** finished jams, slide the reservation window to ``now``.
2. **Spawn** new tasks (Poisson-ish arrival driven by ``task_spawn_rate``).
3. **Allocate** pending tasks to idle robots.
4. **Plan** — every robot whose reserved runway is short, invalid or aimed at a
   stale goal replans a conflict-free window through the reservation table.
5. **Execute** — apply one step of each plan through the *execution guard*.
6. **Verify** — assert no two robots share a cell and no pair swapped.
7. **Resolve** task state machine + metrics.

Two independent layers of safety
--------------------------------
* The **reservation table** makes committed *plans* pairwise conflict-free by
  construction (see ``reservation.py``).
* The **execution guard** re-validates the *actual* move set each tick against
  live robot positions. It exists because a plan can go stale between ticks
  (a robot may fail to plan and hold position without reservations). The guard
  is what makes "zero collisions" a property of the executed state, not just of
  the planner.

The verifier in step 6 counts violations; it stays at zero in every test and
benchmark run, and the count is surfaced live in the UI.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .allocator import GreedyAllocator, apply_assignment
from .config import SimConfig
from .metrics import MetricsTracker
from .models import Robot, RobotStatus, Task, TaskState
from .pathfinding import plan_path
from .reservation import ReservationTable
from .world import CHARGER, DROPOFF, FLOOR, PICKUP, World, manhattan

Cell = Tuple[int, int]

STATUS_RANK = {
    RobotStatus.CARRYING: 0,
    RobotStatus.REROUTING: 1,
    RobotStatus.TO_PICKUP: 2,
    RobotStatus.IDLE: 3,
}

#: How long a robot keeps the "rerouting" colour after a forced replan. Long
#: enough (~2.3 s at 6 Hz) that a viewer actually sees the fleet react to a jam.
REROUTE_FLASH_TICKS = 14

BLACK_FRIDAY = {
    "id": "black_friday",
    "title": "Black Friday",
    "blurb": "Peak hour. The main aisle is blocked. Keep the docks moving.",
    "fleet": 32,
    "duration": 180,
    "target": 100,
    "seed": 42,
    "initial_tasks": 36,
}


def _scenario_grade(delivered: int, target: int, collisions: int) -> str:
    if collisions:
        return "F"
    ratio = delivered / max(1, target)
    if ratio >= 1.2:
        return "S"
    if ratio >= 1.0:
        return "A"
    if ratio >= 0.7:
        return "B"
    if ratio >= 0.4:
        return "C"
    return "D"


class SimulationEngine:
    """Headless, deterministic warehouse simulation."""

    def __init__(self, config: Optional[SimConfig] = None) -> None:
        self.config = config or SimConfig()
        self.rng = random.Random(self.config.seed)
        self.world = World(self.config)
        self.table = ReservationTable()
        self.allocator = GreedyAllocator(self.config)
        self.metrics = MetricsTracker(
            window=self.config.metrics_window,
            seconds_per_tick=self.config.seconds_per_tick,
        )
        self.tick: int = 0
        self.robots: List[Robot] = []
        self.tasks: Dict[int, Task] = {}
        self.pending: List[Task] = []
        self._next_task_id = 1
        self.events: List[Dict[str, Any]] = []
        self.scenario: Optional[Dict[str, Any]] = None
        #: When True, ambient random demand is off — only dispatcher-placed orders.
        self.manual_demand: bool = False
        self._parking: List[Cell] = self._parking_spots()
        self._spawn_fleet(self.config.fleet_size)
        for _ in range(self.config.initial_tasks):
            self._spawn_task()

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _parking_spots(self) -> List[Cell]:
        """Idle bays around the whole floor perimeter, so aisles stay clear.

        The ring (north wall, south wall, both side lanes) is walked in order
        rather than row by row: robots then park spread around the building
        instead of queueing shoulder-to-shoulder along a single row, which is
        both more realistic and far better looking at large fleet sizes.
        """
        w, h = self.world.width, self.world.height
        candidates: List[Cell] = []
        north = [max(0, self.config.margin - 1), 0]
        south = [h - 1, h - self.config.margin]

        for y in dict.fromkeys(north):                 # top rows, left to right
            candidates.extend((x, y) for x in range(w))
        for x in (w - 1, 0):                           # right lane, top to bottom
            candidates.extend((x, y) for y in range(h))
        for y in dict.fromkeys(south):                 # bottom rows
            candidates.extend((x, y) for x in reversed(range(w)))

        seen = set()
        spots: List[Cell] = []
        for cell in list(self.world.chargers) + candidates:
            if cell in seen or not self.world.in_bounds(cell):
                continue
            if self.world.cell_type(cell) not in (FLOOR, CHARGER):
                continue
            seen.add(cell)
            spots.append(cell)

        if not spots:
            spots = sorted(self.world.passable_cells())
        return spots

    def _spawn_fleet(self, size: int) -> None:
        spots = self._parking
        used = {r.pos for r in self.robots}
        next_id = max([r.id for r in self.robots], default=-1) + 1
        stride = max(1, len(spots) // max(1, size))
        i = 0
        while len(self.robots) < size and i < len(spots) * 2:
            cell = spots[(i * stride) % len(spots)]
            i += 1
            if cell in used or not self.world.is_static_passable(cell):
                continue
            used.add(cell)
            self.robots.append(Robot(id=next_id, pos=cell, home=cell))
            next_id += 1
        # Fall back to any free floor cell if the perimeter ran out.
        if len(self.robots) < size:
            for cell in sorted(self.world.passable_cells()):
                if len(self.robots) >= size:
                    break
                if cell in used or self.world.cell_type(cell) == DROPOFF:
                    continue
                used.add(cell)
                self.robots.append(Robot(id=next_id, pos=cell, home=cell))
                next_id += 1

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def _spawn_task(
        self,
        pickup: Optional[Cell] = None,
        dropoff: Optional[Cell] = None,
        rush: bool = False,
    ) -> Optional[Task]:
        if len(self.pending) >= self.config.max_pending_tasks:
            return None
        pickup = pickup if pickup is not None else self.rng.choice(self.world.pickups)
        dropoff = dropoff if dropoff is not None else self.rng.choice(self.world.dropoffs)
        created = self.tick - 90 if rush else self.tick
        task = Task(
            id=self._next_task_id,
            pickup=pickup,
            dropoff=dropoff,
            created_tick=created,
            rush=rush,
        )
        self._next_task_id += 1
        self.tasks[task.id] = task
        self.pending.append(task)
        return task

    def add_task_burst(self, count: int) -> int:
        created = 0
        for _ in range(max(0, min(count, 200))):
            if self._spawn_task() is not None:
                created += 1
        if created:
            self.events.append({"type": "burst", "count": created, "tick": self.tick})
        return created

    def _resolve_cell(self, cell: Cell, kind: int) -> Optional[Cell]:
        if self.world.cell_type(cell) == kind:
            return cell
        x, y = cell
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if self.world.in_bounds(n) and self.world.cell_type(n) == kind:
                return n
        return None

    def add_rush_order(self, cell: Cell) -> Dict[str, Any]:
        """Dispatcher: spawn a high-priority pick at this face."""
        pickup = self._resolve_cell(cell, PICKUP)
        if pickup is None:
            return {"ok": False, "reason": "click a pick face"}
        task = self._spawn_task(pickup=pickup, rush=True)
        if task is None:
            return {"ok": False, "reason": "queue is full"}
        if self.scenario and self.scenario.get("active"):
            self.scenario["rushOrders"] = int(self.scenario.get("rushOrders", 0)) + 1
        self.events.append(
            {
                "type": "rush",
                "task": task.id,
                "cell": list(pickup),
                "tick": self.tick,
            }
        )
        return {"ok": True, "action": "added", "task": task.id, "cell": list(pickup)}

    def place_order(self, pickup_cell: Cell, dropoff_cell: Cell) -> Dict[str, Any]:
        """Dispatcher: authored pick → dock, jumps the allocation queue."""
        pickup = self._resolve_cell(pickup_cell, PICKUP)
        if pickup is None:
            return {"ok": False, "reason": "click a pick slot"}
        dropoff = self._resolve_cell(dropoff_cell, DROPOFF)
        if dropoff is None:
            return {"ok": False, "reason": "click a dock door"}
        task = self._spawn_task(pickup=pickup, dropoff=dropoff, rush=True)
        if task is None:
            return {"ok": False, "reason": "queue is full"}
        if self.scenario and self.scenario.get("active"):
            self.scenario["rushOrders"] = int(self.scenario.get("rushOrders", 0)) + 1
        self.events.append(
            {
                "type": "order",
                "task": task.id,
                "pickup": list(pickup),
                "dropoff": list(dropoff),
                "tick": self.tick,
            }
        )
        return {
            "ok": True,
            "action": "added",
            "task": task.id,
            "pickup": list(pickup),
            "dropoff": list(dropoff),
        }

    def set_manual_demand(self, manual: bool) -> Dict[str, Any]:
        """Pause or resume ambient random orders. Assigned work keeps rolling."""
        self.manual_demand = bool(manual)
        dropped = 0
        if self.manual_demand:
            kept: List[Task] = []
            for task in self.pending:
                if task.rush:
                    kept.append(task)
                else:
                    dropped += 1
            self.pending = kept
        self.events.append(
            {
                "type": "demand",
                "manual": self.manual_demand,
                "dropped": dropped,
                "tick": self.tick,
            }
        )
        return {"ok": True, "manual": self.manual_demand, "dropped": dropped}

    def effective_spawn_rate(self) -> float:
        """Tasks per tick: explicit if configured, otherwise scaled to fleet.

        Scaling matters for the demo: with fixed demand, dragging the fleet
        slider up just parks idle robots along the perimeter, which looks
        broken. Scaling keeps the floor busy so a larger fleet reads as more
        throughput rather than more clutter.
        """
        if self.config.task_spawn_rate is not None:
            return self.config.task_spawn_rate
        return self.config.tasks_per_robot_per_tick * len(self.robots)

    def _spawn_tasks_for_tick(self) -> None:
        # Throttle demand once the backlog is deep. Ambient demand is tuned to
        # saturate the fleet; without a ceiling a small surplus compounds into a
        # queue that only inflates avg-task-time (mostly wait, not driving).
        # Bursts still bypass this: an operator-triggered spike should be felt.
        if self.manual_demand:
            return
        if len(self.pending) >= max(4, len(self.robots) // 4):
            return
        rate = self.effective_spawn_rate()
        whole = int(rate)
        for _ in range(whole):
            self._spawn_task()
        if self.rng.random() < (rate - whole):
            self._spawn_task()

    # ------------------------------------------------------------------
    # events / commands
    # ------------------------------------------------------------------
    def toggle_jam(self, cell: Cell, duration: Optional[int] = None) -> Dict[str, Any]:
        """Add a jam, or clear it if the cell is already jammed."""
        if self.world.is_jammed(cell, self.tick):
            self.world.clear_jam(cell)
            self.events.append({"type": "jam_cleared", "cell": list(cell), "tick": self.tick})
            self._invalidate_plans_touching(cell)
            return {"ok": True, "action": "cleared"}
        jam = self.world.add_jam(cell, self.tick, duration)
        if jam is None:
            return {"ok": False, "reason": "cell cannot be jammed"}
        if self.scenario and self.scenario.get("active"):
            self.scenario["jamsPlaced"] = int(self.scenario.get("jamsPlaced", 0)) + 1
        self.events.append(
            {
                "type": "jam_added",
                "cell": list(cell),
                "tick": self.tick,
                "expires": jam.expires_tick,
            }
        )
        self._invalidate_plans_touching(cell)
        return {"ok": True, "action": "added"}

    def _invalidate_plans_touching(self, cell: Cell) -> None:
        """Force a reroute for every robot whose reserved window uses ``cell``."""
        for robot in self.robots:
            if cell in robot.plan:
                self.table.release_agent(robot.id)
                robot.invalidate_plan()
                robot.reroutes += 1
                robot.reroute_flash = REROUTE_FLASH_TICKS
                self.events.append(
                    {"type": "reroute", "robot": robot.id, "tick": self.tick}
                )

    def set_fleet_size(self, size: int) -> int:
        size = max(1, min(size, 120))
        if size > len(self.robots):
            self._spawn_fleet(size)
        elif size < len(self.robots):
            for robot in self.robots[size:]:
                self.table.release_agent(robot.id)
                if robot.task is not None:
                    self._release_task(robot.task)
                for queued in robot.queue:
                    self._release_task(queued)
            self.robots = self.robots[:size]
        self.config = self.config.replace(fleet_size=len(self.robots))
        return len(self.robots)

    def _release_task(self, task: Task) -> None:
        if task.state in (TaskState.ASSIGNED, TaskState.CARRIED):
            task.state = TaskState.PENDING
            task.assigned_to = None
            task.assigned_tick = None
            if task not in self.pending:
                self.pending.append(task)

    # ------------------------------------------------------------------
    # scenario
    # ------------------------------------------------------------------
    def begin_black_friday(self) -> Dict[str, Any]:
        """Seed the named dispatcher scenario: blocked aisle, peak demand."""
        spec = BLACK_FRIDAY
        self._seed_incident_jams(spec["duration"] + 20)
        self.add_task_burst(18)
        self.scenario = {
            "id": spec["id"],
            "title": spec["title"],
            "blurb": spec["blurb"],
            "startTick": self.tick,
            "duration": spec["duration"],
            "target": spec["target"],
            "startCompleted": self.metrics.total_completed,
            "delivered": 0,
            "jamsPlaced": 0,
            "rushOrders": 0,
            "active": True,
            "grade": None,
            "score": 0,
            "remaining": spec["duration"],
        }
        self.events.append({"type": "scenario_start", "id": spec["id"], "tick": self.tick})
        return self.scenario_payload()

    def _seed_incident_jams(self, duration: int) -> None:
        """Block a stretch of a busy east-west aisle so the fleet has to reroute."""
        h, w = self.world.height, self.world.width
        y = max(self.config.margin + 1, min(h - 4, h // 2 + 1))
        jammed = 0
        for x in range(w // 4, (3 * w) // 4):
            cell = (x, y)
            if self.world.cell_type(cell) != FLOOR:
                continue
            if self.world.add_jam(cell, self.tick, duration) is None:
                continue
            self._invalidate_plans_touching(cell)
            jammed += 1
            if jammed >= 7:
                break
        if jammed:
            self.events.append(
                {"type": "jam_added", "cell": [w // 2, y], "tick": self.tick, "expires": self.tick + duration}
            )

    def _tick_scenario(self) -> None:
        sc = self.scenario
        if not sc or not sc.get("active"):
            return
        delivered = self.metrics.total_completed - int(sc["startCompleted"])
        elapsed = self.tick - int(sc["startTick"])
        sc["delivered"] = delivered
        sc["remaining"] = max(0, int(sc["duration"]) - elapsed)
        sc["score"] = delivered * 12 + int(sc.get("rushOrders", 0)) * 8
        if elapsed >= int(sc["duration"]):
            sc["active"] = False
            sc["grade"] = _scenario_grade(delivered, int(sc["target"]), self.metrics.collisions)
            self.events.append(
                {
                    "type": "scenario_over",
                    "id": sc["id"],
                    "grade": sc["grade"],
                    "score": sc["score"],
                    "delivered": delivered,
                    "tick": self.tick,
                }
            )

    def scenario_payload(self) -> Optional[Dict[str, Any]]:
        if not self.scenario:
            return None
        return dict(self.scenario)

    # ------------------------------------------------------------------
    # main tick
    # ------------------------------------------------------------------
    def step(self) -> Dict[str, Any]:
        started = time.perf_counter()
        now = self.tick

        for cell in self.world.expire_jams(now):
            self.events.append({"type": "jam_expired", "cell": list(cell), "tick": now})
            self._invalidate_plans_touching(cell)
        self.table.advance_to(now)

        self._spawn_tasks_for_tick()
        self._allocate(now)
        self._plan_phase(now)
        moved = self._execute_phase(now)
        collisions = self._verify(moved)
        self.tick = now + 1
        self._resolve_tasks(self.tick)
        self._decay_flags()

        compute_ms = (time.perf_counter() - started) * 1000.0
        self.metrics.collisions += collisions
        self.metrics.record_tick(self.tick, compute_ms)
        self._tick_scenario()
        return self.snapshot()

    # ------------------------------------------------------------------
    def _allocate(self, now: int) -> None:
        assignments = self.allocator.allocate(self.robots, self.pending, now)
        for robot, task in assignments:
            apply_assignment(robot, task, now)
            self.table.release_agent(robot.id)
            if task in self.pending:
                self.pending.remove(task)
            self.events.append(
                {"type": "assigned", "robot": robot.id, "task": task.id, "tick": now}
            )

    # ------------------------------------------------------------------
    def _priority_order(self) -> List[Robot]:
        """Carrying robots first, then long-blocked robots, then everyone else.

        Deterministic ordering keeps runs reproducible; boosting robots that
        have been blocked is a cheap and effective anti-livelock measure.
        """
        return sorted(
            self.robots,
            key=lambda r: (STATUS_RANK.get(r.status, 9), -r.blocked_ticks, r.id),
        )

    def _plan_needs_refresh(self, robot: Robot, now: int) -> bool:
        if not robot.plan or robot.plan_t0 != now or robot.plan[0] != robot.pos:
            return True
        goal = robot.goal
        if goal is not None and robot.plan[-1] != goal and robot.plan_partial:
            # Partial plans are refreshed once their runway is half consumed so
            # the robot keeps making progress toward a goal outside the window.
            return len(robot.plan) - 1 <= self.config.horizon // 2
        if len(robot.plan) - 1 <= max(1, self.config.horizon // 3):
            return True
        for i, cell in enumerate(robot.plan):
            if self.world.is_jammed(cell, now + i):
                return True
        return False

    def _rebalance_dropoffs(self) -> None:
        """Spread loaded robots across dropoff stations.

        Every task is born with a fixed dropoff. At high fleet density that
        turns a popular station into a funnel: dozens of carrying robots aim at
        one cell, the ones that cannot reserve it stall on the approach, and the
        stalled bodies block the robots that could have delivered — a queue that
        never drains. Re-picking the station each tick by *travel distance plus
        inbound traffic* keeps all four bays busy and the aisles moving.
        """
        stations = self.world.dropoffs
        if len(stations) < 2:
            return
        inbound: Dict[Cell, int] = {cell: 0 for cell in stations}
        carrying: List[Robot] = []
        for robot in self.robots:
            task = robot.task
            if task is None or task.state != TaskState.CARRIED:
                continue
            carrying.append(robot)
            if task.dropoff in inbound:
                inbound[task.dropoff] += 1

        penalty = self.config.station_queue_penalty
        for robot in carrying:
            task = robot.task
            current = task.dropoff
            # Committed robots keep their bay: swapping on the doorstep looks
            # like indecision and wastes the approach they already paid for.
            if manhattan(robot.pos, current) <= 2:
                continue
            cost_now = manhattan(robot.pos, current) + penalty * (inbound[current] - 1)
            best, best_cost = current, cost_now
            for cell in stations:
                if cell == current:
                    continue
                cost = manhattan(robot.pos, cell) + penalty * inbound[cell]
                if cost < best_cost:
                    best, best_cost = cell, cost
            # Hysteresis: only switch for a clear win, never for a tie.
            if best is not current and best_cost + 2 <= cost_now:
                inbound[current] -= 1
                inbound[best] += 1
                task.dropoff = best
                self.table.release_agent(robot.id)
                robot.invalidate_plan()
                robot.reroute_flash = max(robot.reroute_flash, REROUTE_FLASH_TICKS // 2)

    def _plan_escape(self, robot: Robot, now: int) -> Optional[List[Cell]]:
        """Plan a short move to any reachable neighbour to break a standoff.

        A robot whose goal is unreachable holds position, and a wall of holding
        robots is exactly what keeps the goal unreachable. Stepping aside is the
        cheapest way to unwind the knot: it costs one detour and gives the
        robots behind it a lane.
        """
        options = [c for c in self.world.neighbors(robot.pos, now + 1)]
        self.rng.shuffle(options)
        for cell in options:
            result = plan_path(
                world=self.world,
                table=self.table,
                agent=robot.id,
                start=robot.pos,
                goal=cell,
                t0=now,
                horizon=min(self.config.horizon, 6),
                max_expansions=self.config.max_expansions // 4,
                wait_cost=self.config.wait_cost,
            )
            if result is not None and len(result.path) > 1:
                return list(result.path)
        return None

    def _plan_phase(self, now: int) -> None:
        self._rebalance_dropoffs()
        for robot in self._priority_order():
            if not self._plan_needs_refresh(robot, now):
                continue
            goal = robot.goal or robot.pos
            self.table.release_agent(robot.id)
            result = plan_path(
                world=self.world,
                table=self.table,
                agent=robot.id,
                start=robot.pos,
                goal=goal,
                t0=now,
                horizon=self.config.horizon,
                max_expansions=self.config.max_expansions,
                wait_cost=self.config.wait_cost,
            )
            robot.replans += 1
            self.metrics.replans += 1
            if result is None or len(result.path) < 1:
                self.metrics.failed_plans += 1
                escape = (
                    self._plan_escape(robot, now)
                    if robot.stuck_ticks >= self.config.escape_after_stuck_ticks
                    else None
                )
                if escape is not None:
                    self.table.commit_path(robot.id, escape, now)
                    robot.plan = escape
                    robot.plan_t0 = now
                    robot.plan_partial = True
                    robot.reroutes += 1
                    robot.reroute_flash = max(robot.reroute_flash, REROUTE_FLASH_TICKS)
                    continue
                # Nothing legal — hold position with no reservation. The guard
                # keeps this safe; the robot retries next tick.
                robot.plan = [robot.pos]
                robot.plan_t0 = now
                robot.plan_partial = True
                continue
            self.metrics.expansions += result.expansions
            self.table.commit_path(robot.id, result.path, now)
            robot.plan = list(result.path)
            robot.plan_t0 = now
            robot.plan_partial = not result.complete

    # ------------------------------------------------------------------
    def _execute_phase(self, now: int) -> Dict[int, Tuple[Cell, Cell]]:
        """Apply one step of every plan, filtered by the execution guard."""
        robots = self._priority_order()
        pos_now: Dict[int, Cell] = {r.id: r.pos for r in robots}
        occupant: Dict[Cell, int] = {r.pos: r.id for r in robots}
        target: Dict[int, Cell] = {}
        moving: Dict[int, bool] = {}

        # --- desired moves -------------------------------------------------
        for robot in robots:
            nxt = robot.next_cell()
            if nxt is None or nxt == robot.pos:
                target[robot.id] = robot.pos
                moving[robot.id] = False
                continue
            if not self.world.is_passable(nxt, now + 1) or manhattan(robot.pos, nxt) != 1:
                target[robot.id] = robot.pos
                moving[robot.id] = False
                self._reject(robot, "illegal step")
                continue
            target[robot.id] = nxt
            moving[robot.id] = True

        # --- guard rule 1: two robots may not claim the same cell -----------
        claims: Dict[Cell, List[int]] = {}
        for robot in robots:
            if moving[robot.id]:
                claims.setdefault(target[robot.id], []).append(robot.id)
        for cell, ids in claims.items():
            if len(ids) > 1:
                winner = ids[0]  # robots iterate in priority order
                for rid in ids[1:]:
                    moving[rid] = False
                    target[rid] = pos_now[rid]
                    self._reject(self._robot(rid), "cell contention")
                del winner

        # --- guard rule 2: no head-on swaps ---------------------------------
        for robot in robots:
            if not moving[robot.id]:
                continue
            other_id = occupant.get(target[robot.id])
            if other_id is None or other_id == robot.id:
                continue
            if moving.get(other_id) and target[other_id] == robot.pos:
                # Lower-priority robot yields.
                loser = other_id if STATUS_RANK.get(
                    self._robot(other_id).status, 9
                ) >= STATUS_RANK.get(robot.status, 9) else robot.id
                moving[loser] = False
                target[loser] = pos_now[loser]
                self._reject(self._robot(loser), "swap conflict")

        # --- guard rule 3: cannot enter a cell whose occupant stays ---------
        # Iterated to a fixpoint so that rejecting one move cascades correctly.
        # Cyclic rotations (A->B->C->A) survive, which keeps traffic flowing.
        changed = True
        while changed:
            changed = False
            for robot in robots:
                if not moving[robot.id]:
                    continue
                occ = occupant.get(target[robot.id])
                if occ is not None and occ != robot.id and not moving.get(occ, False):
                    moving[robot.id] = False
                    target[robot.id] = pos_now[robot.id]
                    self._reject(robot, "blocked by stationary robot")
                    changed = True

        # --- apply -----------------------------------------------------------
        moved: Dict[int, Tuple[Cell, Cell]] = {}
        for robot in robots:
            dest = target[robot.id]
            if moving[robot.id] and dest != robot.pos:
                robot.set_facing(robot.pos, dest)
                moved[robot.id] = (robot.pos, dest)
                robot.pos = dest
                robot.distance_travelled += 1
                robot.stuck_ticks = 0
                robot.advance_plan()
            else:
                moved[robot.id] = (robot.pos, robot.pos)
                # Only robots that *want* to be somewhere else are "stuck";
                # a parked robot standing on its spot is simply parked.
                goal = robot.goal
                robot.stuck_ticks = robot.stuck_ticks + 1 if goal is not None and goal != robot.pos else 0
                if robot.plan and robot.plan[0] == robot.pos and len(robot.plan) > 1 and robot.plan[1] == robot.pos:
                    robot.advance_plan()  # planned wait: consume it
                elif robot.plan:
                    # Plan diverged from reality — drop it and replan next tick.
                    self.table.release_agent(robot.id)
                    robot.invalidate_plan()
        return moved

    def _reject(self, robot: Optional[Robot], reason: str) -> None:
        if robot is None:
            return
        robot.blocked_ticks += 1
        self.metrics.guard_interventions += 1
        if robot.status in (RobotStatus.TO_PICKUP, RobotStatus.CARRYING):
            robot.reroute_flash = max(robot.reroute_flash, 3)

    def _robot(self, rid: int) -> Optional[Robot]:
        for r in self.robots:
            if r.id == rid:
                return r
        return None

    # ------------------------------------------------------------------
    def _verify(self, moved: Dict[int, Tuple[Cell, Cell]]) -> int:
        """Runtime invariant check: no shared cells, no swaps. Always 0."""
        violations = 0
        seen: Dict[Cell, int] = {}
        for robot in self.robots:
            other = seen.get(robot.pos)
            if other is not None:
                violations += 1
            else:
                seen[robot.pos] = robot.id
        transitions = {rid: fr_to for rid, fr_to in moved.items()}
        for rid, (frm, to) in transitions.items():
            for oid, (ofrm, oto) in transitions.items():
                if oid <= rid:
                    continue
                if frm == oto and to == ofrm and frm != to:
                    violations += 1
        return violations

    # ------------------------------------------------------------------
    def _resolve_tasks(self, now: int) -> None:
        for robot in self.robots:
            task = robot.task
            if task is None:
                if robot.status != RobotStatus.IDLE:
                    robot.status = RobotStatus.IDLE
                if robot.queue:
                    nxt = robot.queue.pop(0)
                    apply_assignment(robot, nxt, now)
                    self.table.release_agent(robot.id)
                continue
            if task.state == TaskState.ASSIGNED and robot.pos == task.pickup:
                task.state = TaskState.CARRIED
                task.picked_tick = now
                robot.status = RobotStatus.CARRYING
                self.table.release_agent(robot.id)
                robot.invalidate_plan()
                self.events.append(
                    {
                        "type": "picked",
                        "robot": robot.id,
                        "task": task.id,
                        "cell": list(robot.pos),
                        "tick": now,
                    }
                )
            elif task.state == TaskState.CARRIED and robot.pos == task.dropoff:
                task.state = TaskState.DONE
                task.done_tick = now
                robot.tasks_completed += 1
                robot.task = None
                robot.status = RobotStatus.IDLE
                self.table.release_agent(robot.id)
                robot.invalidate_plan()
                self.metrics.record_completion(now, task.cycle_ticks())
                self.events.append(
                    {
                        "type": "delivered",
                        "robot": robot.id,
                        "task": task.id,
                        "cell": list(robot.pos),
                        "tick": now,
                    }
                )

    def _decay_flags(self) -> None:
        for robot in self.robots:
            if robot.reroute_flash > 0:
                robot.reroute_flash -= 1
            if robot.blocked_ticks > 0 and robot.status == RobotStatus.IDLE:
                robot.blocked_ticks = max(0, robot.blocked_ticks - 1)

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------
    def display_status(self, robot: Robot) -> str:
        if robot.reroute_flash > 0 and robot.status != RobotStatus.IDLE:
            return RobotStatus.REROUTING
        return robot.status

    def snapshot(self) -> Dict[str, Any]:
        active = sum(1 for r in self.robots if r.status != RobotStatus.IDLE)
        robots_payload: List[Dict[str, Any]] = []
        for robot in self.robots:
            payload = robot.to_payload()
            payload["status"] = self.display_status(robot)
            if robot.task is not None:
                payload["task"] = {
                    "id": robot.task.id,
                    "state": robot.task.state,
                    "pickup": list(robot.task.pickup),
                    "dropoff": list(robot.task.dropoff),
                    "rush": robot.task.rush,
                    "ageTicks": self.tick - robot.task.created_tick,
                }
            robots_payload.append(payload)

        jams = [
            {
                "x": j.cell[0],
                "y": j.cell[1],
                "created": j.created_tick,
                "expires": j.expires_tick,
                "ttl": max(0, j.expires_tick - self.tick),
            }
            for j in self.world.active_jams(self.tick)
        ]
        events = self.events
        self.events = []
        return {
            "type": "tick",
            "tick": self.tick,
            "robots": robots_payload,
            "jams": jams,
            "events": events,
            "tasks": {
                "pending": len(self.pending),
                "active": sum(
                    1 for t in self.tasks.values()
                    if t.state in (TaskState.ASSIGNED, TaskState.CARRIED)
                ),
                "completed": self.metrics.total_completed,
            },
            "metrics": self.metrics.snapshot(
                tick=self.tick,
                active_robots=active,
                fleet=len(self.robots),
                pending=len(self.pending),
            ),
            "scenario": self.scenario_payload(),
            "manualDemand": self.manual_demand,
            "dispatch": [
                {
                    "id": t.id,
                    "pickup": list(t.pickup),
                    "dropoff": list(t.dropoff),
                }
                for t in self.pending
                if t.rush
            ],
        }

    def world_payload(self) -> Dict[str, Any]:
        return self.world.to_payload()

    # ------------------------------------------------------------------
    def run(self, ticks: int) -> None:
        """Advance ``ticks`` steps (used by tests and the benchmark)."""
        for _ in range(ticks):
            self.step()

    def positions(self) -> List[Cell]:
        return [r.pos for r in self.robots]
