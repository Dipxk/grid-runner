"""Experiment store tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.experiments import JsonExperimentStore, NullExperimentStore, build_run_record


def test_json_experiment_store_persists_run(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    store = JsonExperimentStore(path)
    run_id = store.save_run(
        build_run_record(
            scenario="planner_comparison",
            planner="whca",
            fleet_size=16,
            seed=17,
            tasks_completed=42,
            collisions=0,
        )
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["run_id"] == run_id
    assert data[0]["collisions"] == 0


def test_null_experiment_store_discards(tmp_path: Path) -> None:
    store = NullExperimentStore()
    assert store.save_run({"run_id": "x"}) == "x"
