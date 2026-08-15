"""Rolling metrics.

Throughput is reported in *simulated* time (``seconds_per_tick``) so the number
does not change when the operator speeds up or slows down playback. Compute
time is reported in real milliseconds, because that is the number that decides
how large a fleet we can actually run.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional


class MetricsTracker:
    def __init__(self, window: int, seconds_per_tick: float) -> None:
        self.window = window
        self.seconds_per_tick = seconds_per_tick
        self.completions: Deque[int] = deque()          # ticks at which tasks finished
        self.cycle_times: Deque[int] = deque(maxlen=window)
        self.tick_ms: Deque[float] = deque(maxlen=window)
        self.throughput_history: Deque[float] = deque(maxlen=120)
        self.total_completed = 0
        self.total_ticks = 0
        self.collisions = 0
        self.guard_interventions = 0
        self.replans = 0
        self.failed_plans = 0
        self.expansions = 0

    # ------------------------------------------------------------------
    def record_completion(self, tick: int, cycle_ticks: Optional[int]) -> None:
        self.completions.append(tick)
        self.total_completed += 1
        if cycle_ticks is not None:
            self.cycle_times.append(cycle_ticks)

    def record_tick(self, tick: int, compute_ms: float) -> None:
        self.total_ticks += 1
        self.tick_ms.append(compute_ms)
        cutoff = tick - self.window
        while self.completions and self.completions[0] < cutoff:
            self.completions.popleft()
        self.throughput_history.append(self.tasks_per_hour(tick))

    # ------------------------------------------------------------------
    def tasks_per_hour(self, tick: int) -> float:
        """Completions over the rolling window, extrapolated to one sim hour."""
        if tick <= 0:
            return 0.0
        span_ticks = min(tick, self.window)
        if span_ticks <= 0:
            return 0.0
        span_seconds = span_ticks * self.seconds_per_tick
        if span_seconds <= 0:
            return 0.0
        return len(self.completions) * 3600.0 / span_seconds

    def avg_cycle_ticks(self) -> float:
        if not self.cycle_times:
            return 0.0
        return sum(self.cycle_times) / len(self.cycle_times)

    def avg_tick_ms(self) -> float:
        if not self.tick_ms:
            return 0.0
        return sum(self.tick_ms) / len(self.tick_ms)

    def p95_tick_ms(self) -> float:
        if not self.tick_ms:
            return 0.0
        ordered: List[float] = sorted(self.tick_ms)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    def max_tick_ms(self) -> float:
        return max(self.tick_ms) if self.tick_ms else 0.0

    # ------------------------------------------------------------------
    def snapshot(self, tick: int, active_robots: int, fleet: int, pending: int) -> Dict[str, Any]:
        return {
            "tick": tick,
            "tasksPerHour": round(self.tasks_per_hour(tick), 1),
            "tasksCompleted": self.total_completed,
            "avgTaskSeconds": round(self.avg_cycle_ticks() * self.seconds_per_tick, 1),
            "activeRobots": active_robots,
            "fleetSize": fleet,
            "pendingTasks": pending,
            "tickComputeMs": round(self.avg_tick_ms(), 2),
            "tickComputeP95Ms": round(self.p95_tick_ms(), 2),
            "collisions": self.collisions,
            "guardInterventions": self.guard_interventions,
            "replans": self.replans,
            "failedPlans": self.failed_plans,
            "utilization": round(active_robots / fleet, 3) if fleet else 0.0,
            "throughputHistory": [round(v, 1) for v in self.throughput_history],
        }
