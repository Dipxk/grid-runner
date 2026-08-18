"""Central simulation configuration.

Every tunable lives here so the benchmark script, the tests and the live server
all exercise exactly the same code paths with different numbers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

LOG = logging.getLogger("robofleet")


def env_get(suffix: str, default: Optional[str] = None) -> Optional[str]:
    """Read ``ROBOFLEET_<SUFFIX>``, with a one-release ``GRIDRUNNER_`` fallback."""
    value = os.environ.get("ROBOFLEET_" + suffix)
    if value is not None:
        return value
    return os.environ.get("GRIDRUNNER_" + suffix, default)


@dataclass(frozen=True)
class SimConfig:
    """Immutable configuration for one simulation run."""

    # --- world -------------------------------------------------------------
    width: int = 44
    height: int = 26
    shelf_block_w: int = 4
    shelf_block_h: int = 2
    aisle_every_x: int = 2
    aisle_every_y: int = 2
    margin: int = 2

    # --- fleet -------------------------------------------------------------
    fleet_size: int = 18

    # --- planner -----------------------------------------------------------
    #: Rolling planning window (ticks). Reservations only ever cover
    #: [now, now + horizon]; robots replan as the window slides. This is the
    #: classic windowed-hierarchical-cooperative-A* (WHCA*) tradeoff: a larger
    #: window means better cooperation but more search per replan.
    horizon: int = 10
    #: Hard cap on A* expansions per replan, so one pathological robot cannot
    #: blow the tick budget for the whole fleet.
    max_expansions: int = 6000
    #: ``whca`` = space-time reservations (default). ``baseline`` = independent
    #: spatial A* with execution-guard-only conflict resolution (for benchmarks).
    planner_mode: str = "whca"
    #: Waiting is slightly more expensive than moving so robots prefer to keep
    #: flowing rather than idle in an aisle (reduces gridlock).
    wait_cost: float = 1.05

    # --- tasks -------------------------------------------------------------
    #: Expected new tasks per tick. ``None`` means "scale demand with the
    #: fleet" (see ``tasks_per_robot_per_tick``) so that growing the fleet
    #: actually puts more robots to work instead of parking them; set an
    #: explicit float to pin demand (benchmarks and tests do this).
    task_spawn_rate: Optional[float] = None
    #: Demand per robot per tick when ``task_spawn_rate`` is auto. Tuned just
    #: below measured per-robot throughput so the queue stays shallow but the
    #: floor never goes idle.
    tasks_per_robot_per_tick: float = 0.024
    initial_tasks: int = 12
    max_pending_tasks: int = 400
    max_assignments_per_tick: int = 8
    #: How much an aging task is boosted when competing for a robot.
    task_age_weight: float = 0.35
    #: Extra cost, in cells of detour, charged per robot already inbound to a
    #: dropoff station. Keeps loaded robots from funnelling into one bay.
    station_queue_penalty: float = 4.0

    # --- deadlock recovery ---------------------------------------------------
    #: Ticks a robot may stand still with no legal plan before it is allowed to
    #: step aside into any reachable neighbour to break a traffic knot.
    escape_after_stuck_ticks: int = 6

    # --- events ------------------------------------------------------------
    #: ~15 s at the default 6 Hz tick rate: long enough to watch the fleet
    #: re-plan around a blockage and queue up, short enough that the floor
    #: recovers on its own during a demo.
    jam_duration_ticks: int = 90

    # --- timing ------------------------------------------------------------
    ticks_per_second: float = 6.0
    #: Simulated seconds represented by one tick. Throughput metrics are
    #: reported in simulated time so they are independent of playback speed.
    seconds_per_tick: float = 1.0

    # --- misc --------------------------------------------------------------
    seed: int = 7
    metrics_window: int = 240  # rolling window (ticks) for throughput/latency

    def replace(self, **kwargs: Any) -> "SimConfig":
        data = asdict(self)
        data.update(kwargs)
        return SimConfig(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_CONFIG = SimConfig()


def config_from_env(base: Optional[SimConfig] = None) -> SimConfig:
    """Build a config, overriding any field from ``ROBOFLEET_<FIELD>`` env vars.

    Example: ``ROBOFLEET_FLEET_SIZE=32 ROBOFLEET_TICKS_PER_SECOND=10``.
    Unknown or unparsable values are ignored with a warning rather than
    crashing a container on a typo. ``GRIDRUNNER_*`` is still accepted so
    existing Render/Fly env vars keep working.
    """
    config = base or SimConfig()
    overrides: Dict[str, Any] = {}
    for field_name, current in asdict(config).items():
        raw = env_get(field_name.upper())
        if raw is None:
            continue
        caster = float if current is None else type(current)
        try:
            overrides[field_name] = caster(raw)
        except (TypeError, ValueError):
            LOG.warning(
                "ignoring invalid override %s=%r", field_name, raw
            )
    return config.replace(**overrides) if overrides else config

#: Speed presets exposed by the UI. Values are ticks-per-second; the client is
#: told the resulting tick interval so animation interpolation stays in sync.
SPEED_PRESETS: Dict[str, float] = {
    "0.5x": 3.0,
    "1x": 6.0,
    "2x": 12.0,
    "4x": 20.0,
}
