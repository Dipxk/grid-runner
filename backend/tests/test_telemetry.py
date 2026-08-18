"""Tests for optional telemetry sinks."""

from __future__ import annotations

import json
from pathlib import Path

from app.telemetry import (
    JsonTelemetrySink,
    TelemetryBridge,
    NullTelemetrySink,
    telemetry_status,
)


def test_json_sink_records_metrics_and_events(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    sink = JsonTelemetrySink(path)
    bridge = TelemetryBridge(sink)

    bridge.on_snapshot(
        {
            "tick": 30,
            "metrics": {"tasksPerHour": 100.0, "collisions": 0},
            "events": [{"type": "fault_detected", "robot": 3, "fault": "robot_offline"}],
        }
    )

    records = json.loads(path.read_text(encoding="utf-8"))
    kinds = {r["kind"] for r in records}
    assert "metrics" in kinds
    assert "event" in kinds
    assert any(r.get("type") == "fault_detected" for r in records if r["kind"] == "event")


def test_bridge_skips_non_telemetry_events(tmp_path: Path) -> None:
    path = tmp_path / "telemetry.jsonl"
    bridge = TelemetryBridge(JsonTelemetrySink(path))
    bridge.on_snapshot(
        {
            "tick": 1,
            "metrics": {"tasksPerHour": 0},
            "events": [{"type": "picked", "robot": 1, "task": 5}],
        }
    )
    records = json.loads(path.read_text(encoding="utf-8"))
    assert all(r["kind"] == "metrics" for r in records)


def test_telemetry_status_null() -> None:
    assert telemetry_status(NullTelemetrySink())["telemetry"] == ["null"]
