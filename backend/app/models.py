"""Domain models: robots and tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Cell = Tuple[int, int]


class RobotStatus:
    """Robot lifecycle states. These map 1:1 onto the UI legend colours."""

    IDLE = "idle"
    TO_PICKUP = "to_pickup"
    CARRYING = "carrying"
    REROUTING = "rerouting"

    ALL = (IDLE, TO_PICKUP, CARRYING, REROUTING)


class TaskState:
    PENDING = "pending"
    ASSIGNED = "assigned"
    CARRIED = "carried"
    DONE = "done"
    #: Robot failed while carrying — inventory stays with the disabled robot.
    RECOVERY_REQUIRED = "recovery_required"


@dataclass
class Task:
    id: int
    pickup: Cell
    dropoff: Cell
    created_tick: int
    state: str = TaskState.PENDING
    assigned_to: Optional[int] = None
    assigned_tick: Optional[int] = None
    picked_tick: Optional[int] = None
    done_tick: Optional[int] = None
    #: Dispatcher rush order — jumps the allocation queue.
    rush: bool = False

    @property
    def wait_ticks(self) -> Optional[int]:
        if self.assigned_tick is None:
            return None
        return self.assigned_tick - self.created_tick

    def cycle_ticks(self) -> Optional[int]:
        if self.done_tick is None:
            return None
        return self.done_tick - self.created_tick

    def to_payload(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "pickup": list(self.pickup),
            "dropoff": list(self.dropoff),
            "state": self.state,
            "createdTick": self.created_tick,
            "assignedTo": self.assigned_to,
            "rush": self.rush,
        }


@dataclass
class Robot:
    id: int
    pos: Cell
    home: Cell
    status: str = RobotStatus.IDLE
    task: Optional[Task] = None
    #: Queue of tasks handed to this robot beyond the active one.
    queue: List[Task] = field(default_factory=list)
    #: Planned cells for ticks [t0, t0+horizon]; ``plan[0]`` is the current cell.
    plan: List[Cell] = field(default_factory=list)
    plan_t0: int = 0
    #: Set when the last replan could not reach the goal within the window.
    plan_partial: bool = False
    #: Diagnostics surfaced in the UI detail panel.
    replans: int = 0
    reroutes: int = 0
    blocked_ticks: int = 0
    #: Consecutive ticks spent standing still; resets the moment the robot moves.
    #: Drives the deadlock-escape behaviour, unlike the lifetime blocked count.
    stuck_ticks: int = 0
    distance_travelled: int = 0
    tasks_completed: int = 0
    #: Ticks remaining of the "rerouting" visual state after a forced replan.
    reroute_flash: int = 0
    facing: str = "east"
    #: False when fault-injected offline — no allocation or movement.
    operational: bool = True

    # ------------------------------------------------------------------
    @property
    def goal(self) -> Optional[Cell]:
        if self.task is None:
            return self.home
        if self.task.state == TaskState.CARRIED:
            return self.task.dropoff
        return self.task.pickup

    def next_cell(self) -> Optional[Cell]:
        if len(self.plan) >= 2:
            return self.plan[1]
        return None

    def remaining_path(self) -> List[Cell]:
        return list(self.plan[1:]) if len(self.plan) > 1 else []

    def advance_plan(self) -> None:
        if self.plan:
            self.plan = self.plan[1:]
            self.plan_t0 += 1

    def invalidate_plan(self) -> None:
        self.plan = []
        self.plan_partial = False

    def set_facing(self, frm: Cell, to: Cell) -> None:
        dx, dy = to[0] - frm[0], to[1] - frm[1]
        if dx > 0:
            self.facing = "east"
        elif dx < 0:
            self.facing = "west"
        elif dy > 0:
            self.facing = "south"
        elif dy < 0:
            self.facing = "north"

    def to_payload(self, include_path: bool = True) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "id": self.id,
            "x": self.pos[0],
            "y": self.pos[1],
            "status": self.status,
            "facing": self.facing,
            "taskId": self.task.id if self.task else None,
            "queued": len(self.queue),
            "completed": self.tasks_completed,
        }
        if include_path:
            payload["path"] = [[c[0], c[1]] for c in self.remaining_path()]
            goal = self.goal
            payload["goal"] = list(goal) if goal else None
        if self.task is not None:
            payload["task"] = {
                "id": self.task.id,
                "state": self.task.state,
                "pickup": list(self.task.pickup),
                "dropoff": list(self.task.dropoff),
                "rush": self.task.rush,
                "ageTicks": None,
            }
        payload["queue"] = [t.id for t in self.queue]
        payload["stats"] = {
            "replans": self.replans,
            "reroutes": self.reroutes,
            "blockedTicks": self.blocked_ticks,
            "distance": self.distance_travelled,
        }
        return payload
