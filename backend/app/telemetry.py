"""Optional telemetry sinks for fleet metrics and fault events."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class TelemetrySink(ABC):
    @abstractmethod
    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def publish_event(self, event: Dict[str, Any]) -> None:
        ...


class ConsoleTelemetrySink(TelemetrySink):
    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        print("[metrics]", json.dumps(payload, separators=(",", ":")))

    def publish_event(self, event: Dict[str, Any]) -> None:
        print("[event]", json.dumps(event, separators=(",", ":")))


class JsonTelemetrySink(TelemetrySink):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def _append(self, record: Dict[str, Any]) -> None:
        data: List[Dict[str, Any]] = json.loads(self.path.read_text(encoding="utf-8"))
        data.append(record)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        self._append({"kind": "metrics", **payload})

    def publish_event(self, event: Dict[str, Any]) -> None:
        self._append({"kind": "event", **event})


class NullTelemetrySink(TelemetrySink):
    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        return None

    def publish_event(self, event: Dict[str, Any]) -> None:
        return None


def telemetry_from_env() -> TelemetrySink:
    path = Path(__file__).resolve().parents[2] / "benchmarks" / "telemetry.jsonl"
    if path.parent.exists():
        return JsonTelemetrySink(path)
    return NullTelemetrySink()
