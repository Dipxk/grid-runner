from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import SimConfig  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402


@pytest.fixture
def small_config() -> SimConfig:
    """A compact warehouse that still has shelves, aisles and stations."""
    return SimConfig(
        width=20,
        height=14,
        shelf_block_w=3,
        shelf_block_h=2,
        margin=1,
        fleet_size=6,
        horizon=8,
        initial_tasks=4,
        task_spawn_rate=0.4,
        seed=11,
    )


@pytest.fixture
def engine(small_config: SimConfig) -> SimulationEngine:
    return SimulationEngine(small_config)
