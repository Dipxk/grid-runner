"""Task allocation.

Greedy nearest-idle matching with two corrections that matter in practice:

* **Age boost** — an old pending task lowers its effective distance, so tasks
  cannot starve while robots keep grabbing the convenient work nearby.
* **Congestion penalty** — candidate robots pay a small penalty proportional to
  how many other robots sit near the pickup, which spreads the fleet out
  instead of piling everyone into one aisle.

This is deliberately O(pending x idle) with small constants; the benchmark
shows allocation is a rounding error next to path planning. A Hungarian /
auction allocator is the natural next upgrade and is noted in the README.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .config import SimConfig
from .models import Robot, RobotStatus, Task, TaskState
from .world import manhattan

Cell = Tuple[int, int]


class GreedyAllocator:
    """Assigns pending tasks to idle robots, best pair first."""

    def __init__(self, config: SimConfig) -> None:
        self.config = config

    def allocate(
        self,
        robots: Sequence[Robot],
        pending: List[Task],
        tick: int,
    ) -> List[Tuple[Robot, Task]]:
        idle = [r for r in robots if r.task is None and not r.queue]
        if not idle or not pending:
            return []

        density = self._density(robots)
        assignments: List[Tuple[Robot, Task]] = []
        taken_robots: Dict[int, bool] = {}
        max_assign = min(self.config.max_assignments_per_tick, len(idle), len(pending))

        # Oldest tasks first; within a pass, each task grabs its cheapest robot.
        # Only the head of the backlog is considered: with a deep queue the
        # remaining tasks cannot win anyway (they are strictly younger), and
        # scanning all of them would make tick cost grow with backlog depth.
        candidate_count = max(self.config.max_assignments_per_tick * 4, len(idle) * 3, 24)
        ordered = sorted(pending, key=lambda t: (t.created_tick, t.id))[:candidate_count]
        for task in ordered:
            if len(assignments) >= max_assign:
                break
            best_robot = None
            best_score = float("inf")
            age = tick - task.created_tick
            for robot in idle:
                if taken_robots.get(robot.id):
                    continue
                dist = manhattan(robot.pos, task.pickup)
                penalty = density.get(task.pickup, 0) * 1.5
                score = dist + penalty - age * self.config.task_age_weight
                if score < best_score:
                    best_score = score
                    best_robot = robot
            if best_robot is None:
                break
            taken_robots[best_robot.id] = True
            assignments.append((best_robot, task))
        return assignments

    @staticmethod
    def _density(robots: Sequence[Robot]) -> Dict[Cell, int]:
        """Coarse 3x3 crowding map keyed by cell, used as a tie-breaker."""
        density: Dict[Cell, int] = {}
        for r in robots:
            x, y = r.pos
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    key = (x + dx, y + dy)
                    density[key] = density.get(key, 0) + 1
        return density


def apply_assignment(robot: Robot, task: Task, tick: int) -> None:
    """Bind a task to a robot and move both into the 'en route' state."""
    task.state = TaskState.ASSIGNED
    task.assigned_to = robot.id
    task.assigned_tick = tick
    robot.task = task
    robot.status = RobotStatus.TO_PICKUP
    robot.invalidate_plan()
