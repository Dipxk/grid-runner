"""Fault injection and autonomous recovery for the fleet simulator.

Faults are modelled at the simulation tick level so tests stay deterministic.
The manager owns per-robot fault records; the engine calls ``tick()`` once per
sim step and consults the manager before allocate / plan / execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import SimulationEngine
    from .models import Robot, Task


class FaultType(str, Enum):
    ROBOT_OFFLINE = "robot_offline"
    SLOW_ROBOT = "slow_robot"
    PLANNER_FAILURE = "planner_failure"
    COMMUNICATION_DELAY = "communication_delay"


class FaultState(str, Enum):
    NORMAL = "normal"
    FAULT_DETECTED = "fault_detected"
    SAFE_HOLD = "safe_hold"
    RECOVERY = "recovery"
    REPLANNING = "replanning"


class RobotHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass
class ActiveFault:
    fault_type: FaultType
    injected_tick: int
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RobotFaultRecord:
    active: Optional[ActiveFault] = None
    fault_state: FaultState = FaultState.NORMAL
    health: RobotHealth = RobotHealth.HEALTHY
    fault_count: int = 0
    recovery_count: int = 0
    last_fault_tick: Optional[int] = None
    recovery_started_tick: Optional[int] = None
    recovery_completed_tick: Optional[int] = None
    #: Planner failure backoff — robot holds until this tick.
    planner_hold_until: int = 0
    planner_failures: int = 0
    #: Slow robot executes a move only every ``slow_stride`` ticks.
    slow_stride: int = 1
    slow_tick_counter: int = 0
    #: Comm delay: queued destination applied after this many ticks.
    comm_delay_ticks: int = 0
    comm_pending_dest: Optional[tuple] = None
    comm_pending_at: Optional[int] = None

    def to_payload(self, tick: int, seconds_per_tick: float = 1.0) -> Dict[str, Any]:
        last_recovery_seconds: Optional[float] = None
        if self.recovery_started_tick is not None and self.recovery_completed_tick is not None:
            last_recovery_seconds = (
                self.recovery_completed_tick - self.recovery_started_tick
            ) * seconds_per_tick
        return {
            "health": self.health.value,
            "faultState": self.fault_state.value,
            "fault": self.active.fault_type.value if self.active else None,
            "faultCount": self.fault_count,
            "recoveryCount": self.recovery_count,
            "lastFaultTick": self.last_fault_tick,
            "recoveryStartedTick": self.recovery_started_tick,
            "recoveryCompletedTick": self.recovery_completed_tick,
            "lastRecoverySeconds": round(last_recovery_seconds, 2) if last_recovery_seconds is not None else None,
            "plannerFailures": self.planner_failures,
        }


class FaultManager:
    """Central fault registry and recovery orchestrator."""

    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.records: Dict[int, RobotFaultRecord] = {}
        self.faults_injected = 0
        self.successful_recoveries = 0
        self.task_reassignments = 0
        self.recovery_latencies: List[int] = []

    def _record(self, robot_id: int) -> RobotFaultRecord:
        if robot_id not in self.records:
            self.records[robot_id] = RobotFaultRecord()
        return self.records[robot_id]

    def active_faults(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for rid, rec in self.records.items():
            if rec.active is not None:
                out.append(
                    {
                        "robot": rid,
                        "type": rec.active.fault_type.value,
                        "tick": rec.active.injected_tick,
                        "params": dict(rec.active.params),
                    }
                )
        return out

    def inject_fault(
        self,
        robot_id: int,
        fault_type: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        robot = self.engine._robot(robot_id)
        if robot is None:
            return {"ok": False, "reason": "unknown robot"}
        try:
            ftype = FaultType(fault_type)
        except ValueError:
            return {"ok": False, "reason": f"unknown fault type: {fault_type}"}

        params = dict(params or {})
        rec = self._record(robot_id)
        if rec.active is not None and rec.active.fault_type == ftype:
            return {"ok": True, "action": "already_active", "robot": robot_id, "type": ftype.value}

        tick = self.engine.tick
        rec.active = ActiveFault(fault_type=ftype, injected_tick=tick, params=params)
        rec.fault_state = FaultState.FAULT_DETECTED
        rec.fault_count += 1
        rec.last_fault_tick = tick
        rec.recovery_started_tick = None
        rec.recovery_completed_tick = None
        self.faults_injected += 1

        if ftype == FaultType.ROBOT_OFFLINE:
            rec.health = RobotHealth.OFFLINE
            robot.operational = False
            self._handle_offline(robot, tick)
        elif ftype == FaultType.SLOW_ROBOT:
            rec.health = RobotHealth.DEGRADED
            rec.slow_stride = max(2, int(params.get("stride", 3)))
            rec.slow_tick_counter = 0
            rec.fault_state = FaultState.SAFE_HOLD
        elif ftype == FaultType.PLANNER_FAILURE:
            rec.health = RobotHealth.DEGRADED
            rec.planner_failures += 1
            self.engine.metrics.planner_failures += 1
            hold = int(params.get("hold_ticks", 8))
            rec.planner_hold_until = tick + hold
            self._safe_hold(robot, tick)
            rec.fault_state = FaultState.SAFE_HOLD
        elif ftype == FaultType.COMMUNICATION_DELAY:
            rec.health = RobotHealth.DEGRADED
            rec.comm_delay_ticks = max(1, int(params.get("delay_ticks", 4)))
            rec.fault_state = FaultState.SAFE_HOLD

        self.engine.events.append(
            {
                "type": "fault_detected",
                "robot": robot_id,
                "fault": ftype.value,
                "tick": tick,
            }
        )
        if ftype == FaultType.ROBOT_OFFLINE:
            self.engine.events.append(
                {"type": "robot_offline", "robot": robot_id, "tick": tick}
            )
        elif ftype == FaultType.PLANNER_FAILURE:
            self.engine.events.append(
                {"type": "planner_failure", "robot": robot_id, "tick": tick}
            )
        return {"ok": True, "action": "injected", "robot": robot_id, "type": ftype.value}

    def clear_fault(self, robot_id: int) -> Dict[str, Any]:
        robot = self.engine._robot(robot_id)
        if robot is None:
            return {"ok": False, "reason": "unknown robot"}
        rec = self._record(robot_id)
        if rec.active is None:
            if rec.fault_state in (FaultState.RECOVERY, FaultState.REPLANNING):
                return {"ok": True, "action": "recovering", "robot": robot_id}
            return {"ok": True, "action": "none", "robot": robot_id}

        tick = self.engine.tick
        rec.fault_state = FaultState.RECOVERY
        rec.recovery_started_tick = tick
        rec.active = None
        rec.health = RobotHealth.DEGRADED
        rec.planner_hold_until = 0
        rec.slow_stride = 1
        rec.slow_tick_counter = 0
        rec.comm_delay_ticks = 0
        rec.comm_pending_dest = None
        rec.comm_pending_at = None
        robot.operational = True
        self.engine.events.append(
            {"type": "recovery_started", "robot": robot_id, "tick": tick}
        )
        return {"ok": True, "action": "cleared", "robot": robot_id}

    def tick(self, now: int) -> None:
        """Advance recovery state machines and planner-failure backoff."""
        for robot in self.engine.robots:
            rec = self._record(robot.id)
            if rec.active is None and rec.fault_state == FaultState.RECOVERY:
                rec.fault_state = FaultState.REPLANNING
                self.engine.table.release_agent(robot.id)
                robot.invalidate_plan()
            elif rec.active is None and rec.fault_state == FaultState.REPLANNING:
                if robot.plan and len(robot.plan) > 1:
                    self._complete_recovery(robot, rec, now)
            elif rec.active and rec.active.fault_type == FaultType.PLANNER_FAILURE:
                if now >= rec.planner_hold_until:
                    rec.fault_state = FaultState.REPLANNING
                    self.engine.table.release_agent(robot.id)
                    robot.invalidate_plan()

    def _complete_recovery(self, robot: Robot, rec: RobotFaultRecord, now: int) -> None:
        if not robot.operational or not robot.plan or len(robot.plan) <= 1:
            return
        if rec.fault_state != FaultState.REPLANNING:
            return
        rec.fault_state = FaultState.NORMAL
        rec.health = RobotHealth.HEALTHY
        rec.recovery_count += 1
        rec.recovery_completed_tick = now
        self.successful_recoveries += 1
        if rec.recovery_started_tick is not None:
            latency = now - rec.recovery_started_tick
            self.recovery_latencies.append(latency)
        self.engine.events.append(
            {
                "type": "recovery_completed",
                "robot": robot.id,
                "tick": now,
                "latencyTicks": (
                    now - rec.recovery_started_tick if rec.recovery_started_tick else 0
                ),
            }
        )
        self.engine.events.append(
            {"type": "robot_recovered", "robot": robot.id, "tick": now}
        )

    def _safe_hold(self, robot: Robot, tick: int) -> None:
        self.engine.table.release_agent(robot.id)
        robot.invalidate_plan()
        robot.plan = [robot.pos]
        robot.plan_t0 = tick
        robot.plan_partial = True

    def _handle_offline(self, robot: Robot, tick: int) -> None:
        from .models import TaskState

        self._safe_hold(robot, tick)
        rec = self._record(robot.id)
        rec.fault_state = FaultState.SAFE_HOLD

        task = robot.task
        if task is not None and task.state == TaskState.ASSIGNED:
            self.engine._return_task_to_queue(task, robot, tick, reason="robot_offline")
        elif task is not None and task.state == TaskState.CARRIED:
            from .models import RobotStatus

            task.state = TaskState.RECOVERY_REQUIRED
            self.engine.events.append(
                {
                    "type": "recovery_required",
                    "robot": robot.id,
                    "task": task.id,
                    "tick": tick,
                }
            )
            robot.task = None
            robot.status = RobotStatus.IDLE

        for queued in list(robot.queue):
            self.engine._return_task_to_queue(queued, robot, tick, reason="robot_offline")
        robot.queue.clear()

    def is_offline(self, robot_id: int) -> bool:
        rec = self.records.get(robot_id)
        return rec is not None and rec.active is not None and rec.active.fault_type == FaultType.ROBOT_OFFLINE

    def is_planner_blocked(self, robot_id: int, tick: int) -> bool:
        rec = self.records.get(robot_id)
        if rec is None:
            return False
        if rec.active and rec.active.fault_type == FaultType.PLANNER_FAILURE:
            return tick < rec.planner_hold_until
        return False

    def is_slow(self, robot_id: int) -> bool:
        rec = self.records.get(robot_id)
        return (
            rec is not None
            and rec.active is not None
            and rec.active.fault_type == FaultType.SLOW_ROBOT
        )

    def slow_stride(self, robot_id: int) -> int:
        rec = self.records.get(robot_id)
        if rec and rec.active and rec.active.fault_type == FaultType.SLOW_ROBOT:
            return max(2, rec.slow_stride)
        return 1

    def should_execute_move(self, robot_id: int, tick: int) -> bool:
        if self.is_offline(robot_id):
            return False
        return True

    def apply_comm_delay(
        self, robot: Robot, intended_dest: tuple, tick: int
    ) -> tuple:
        """Hold commanded moves until the communication delay elapses."""
        rec = self._record(robot.id)
        if not rec.active or rec.active.fault_type != FaultType.COMMUNICATION_DELAY:
            return intended_dest
        if intended_dest == robot.pos:
            return intended_dest
        if rec.comm_pending_dest is None:
            rec.comm_pending_dest = intended_dest
            rec.comm_pending_at = tick + rec.comm_delay_ticks
            return robot.pos
        if rec.comm_pending_at is not None and tick >= rec.comm_pending_at:
            dest = rec.comm_pending_dest
            rec.comm_pending_dest = None
            rec.comm_pending_at = None
            return dest
        return robot.pos

    def comm_delay_ready(self, robot_id: int, tick: int) -> Optional[tuple]:
        return None

    def robots_offline_count(self) -> int:
        return sum(1 for rid, rec in self.records.items() if self.is_offline(rid))

    def mean_recovery_ticks(self) -> float:
        if not self.recovery_latencies:
            return 0.0
        return sum(self.recovery_latencies) / len(self.recovery_latencies)

    def recovery_success_rate(self) -> float:
        if self.faults_injected == 0:
            return 1.0
        return self.successful_recoveries / self.faults_injected

    def snapshot_metrics(self) -> Dict[str, Any]:
        return {
            "faultsInjected": self.faults_injected,
            "successfulRecoveries": self.successful_recoveries,
            "recoverySuccessRate": round(self.recovery_success_rate(), 3),
            "meanRecoveryTicks": round(self.mean_recovery_ticks(), 2),
            "meanRecoverySeconds": round(
                self.mean_recovery_ticks() * self.engine.config.seconds_per_tick, 2
            ),
            "taskReassignments": self.task_reassignments,
            "plannerFailures": self.engine.metrics.planner_failures,
            "robotsOffline": self.robots_offline_count(),
        }
