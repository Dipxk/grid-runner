"""Optional experiment run storage for benchmarks and scenarios."""

from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gridrunner.experiments")


class ExperimentStore(ABC):
    @abstractmethod
    def save_run(self, record: Dict[str, Any]) -> str:
        ...


class JsonExperimentStore(ExperimentStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def save_run(self, record: Dict[str, Any]) -> str:
        run_id = record.get("run_id") or str(uuid.uuid4())
        record = {**record, "run_id": run_id}
        data: List[Dict[str, Any]] = json.loads(self.path.read_text(encoding="utf-8"))
        data.append(record)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return run_id


class DynamoDbExperimentStore(ExperimentStore):
    """Persist run summaries to DynamoDB when boto3 and credentials are available."""

    def __init__(
        self,
        table_name: str,
        *,
        region: Optional[str] = None,
    ) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 required for DynamoDbExperimentStore") from exc
        self.table_name = table_name
        self._dynamodb = boto3.resource("dynamodb", region_name=region or os.environ.get("AWS_REGION"))
        self._table = self._dynamodb.Table(table_name)

    def save_run(self, record: Dict[str, Any]) -> str:
        run_id = record.get("run_id") or str(uuid.uuid4())
        item = {**record, "run_id": run_id}
        item["timestamp"] = item.get("timestamp") or datetime.now(timezone.utc).isoformat()
        # DynamoDB requires string/number types; coerce floats.
        for key, value in list(item.items()):
            if isinstance(value, float):
                item[key] = round(value, 4)
        self._table.put_item(Item=item)
        return run_id


class NullExperimentStore(ExperimentStore):
    def save_run(self, record: Dict[str, Any]) -> str:
        return record.get("run_id") or "discarded"


def experiment_store_from_env() -> ExperimentStore:
    table = os.environ.get("GRIDRUNNER_DYNAMODB_TABLE")
    if table:
        try:
            return DynamoDbExperimentStore(table)
        except Exception as exc:
            logger.warning("DynamoDB store unavailable (%s); falling back to JSON", exc)
    default = Path(__file__).resolve().parents[2] / "benchmarks" / "experiments.json"
    if os.environ.get("GRIDRUNNER_EXPERIMENT_STORE", "json").lower() in ("null", "off"):
        return NullExperimentStore()
    return JsonExperimentStore(default)


def build_run_record(
    *,
    scenario: str,
    planner: str,
    fleet_size: int,
    seed: int,
    git_commit: Optional[str] = None,
    **metrics: Any,
) -> Dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit or os.environ.get("GITHUB_SHA", "local"),
        "seed": seed,
        "scenario": scenario,
        "planner": planner,
        "fleet_size": fleet_size,
        **metrics,
    }
