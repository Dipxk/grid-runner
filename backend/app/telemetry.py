"""Optional telemetry sinks for fleet metrics and fault events.

Planning and collision avoidance stay local. Telemetry is observability only.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.config import env_get

logger = logging.getLogger("robofleet.telemetry")

TELEMETRY_EVENT_TYPES: Set[str] = {
    "fault_detected",
    "robot_offline",
    "robot_recovered",
    "task_reassigned",
    "planner_failure",
    "recovery_started",
    "recovery_completed",
    "recovery_required",
    "scenario_start",
    "scenario_over",
}


class TelemetrySink(ABC):
    @abstractmethod
    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def publish_event(self, event: Dict[str, Any]) -> None:
        ...

    def close(self) -> None:
        """Release external resources (MQTT connections, etc.)."""
        return None


class CompositeTelemetrySink(TelemetrySink):
    def __init__(self, sinks: List[TelemetrySink]) -> None:
        self.sinks = sinks

    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        for sink in self.sinks:
            _safe_call(sink.publish_metrics, payload)

    def publish_event(self, event: Dict[str, Any]) -> None:
        for sink in self.sinks:
            _safe_call(sink.publish_event, event)

    def close(self) -> None:
        for sink in self.sinks:
            _safe_call(sink.close)


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
        self._lock = threading.Lock()

    def _append(self, record: Dict[str, Any]) -> None:
        with self._lock:
            data: List[Dict[str, Any]] = json.loads(self.path.read_text(encoding="utf-8"))
            data.append(record)
            self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        self._append({"kind": "metrics", "ts": time.time(), **payload})

    def publish_event(self, event: Dict[str, Any]) -> None:
        self._append({"kind": "event", "ts": time.time(), **event})


class NullTelemetrySink(TelemetrySink):
    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        return None

    def publish_event(self, event: Dict[str, Any]) -> None:
        return None


class AwsIotTelemetrySink(TelemetrySink):
    """Publish to AWS IoT Core over MQTT (mtls). Requires ``awsiotsdk`` + certs."""

    def __init__(
        self,
        endpoint: str,
        cert_path: Path,
        key_path: Path,
        *,
        ca_path: Optional[Path] = None,
        client_id: str = "robofleet",
        topic_prefix: str = "robofleet",
    ) -> None:
        self.endpoint = endpoint
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path
        self.client_id = client_id
        self.topic_prefix = topic_prefix.rstrip("/")
        self._connection: Any = None
        self._lock = threading.Lock()
        self._connected = False
        self._last_error: Optional[str] = None

    @property
    def active(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _ensure_connection(self) -> bool:
        if self._connected and self._connection is not None:
            return True
        try:
            from awsiot import mqtt_connection_builder  # type: ignore
        except ImportError:
            self._last_error = "awsiotsdk not installed (pip install awsiotsdk)"
            logger.warning(self._last_error)
            return False

        try:
            kwargs: Dict[str, Any] = {
                "endpoint": self.endpoint,
                "cert_filepath": str(self.cert_path),
                "pri_key_filepath": str(self.key_path),
                "client_id": self.client_id,
                "clean_session": False,
                "keep_alive_secs": 30,
            }
            if self.ca_path is not None:
                kwargs["ca_filepath"] = str(self.ca_path)
            self._connection = mqtt_connection_builder.mtls_from_path(**kwargs)
            connect_future = self._connection.connect()
            connect_future.result(timeout=10)
            self._connected = True
            self._last_error = None
            logger.info("AWS IoT telemetry connected to %s", self.endpoint)
            return True
        except Exception as exc:
            self._connected = False
            self._connection = None
            self._last_error = str(exc)
            logger.warning("AWS IoT telemetry connect failed: %s", exc)
            return False

    def _publish(self, topic: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            if not self._ensure_connection():
                return
            try:
                from awscrt import mqtt as awscrt_mqtt  # type: ignore

                body = json.dumps(payload, separators=(",", ":"))
                publish_future, _packet_id = self._connection.publish(
                    topic=topic,
                    payload=body,
                    qos=awscrt_mqtt.QoS.AT_LEAST_ONCE,
                )
                publish_future.result(timeout=5)
            except Exception as exc:
                self._connected = False
                self._connection = None
                self._last_error = str(exc)
                logger.warning("AWS IoT publish failed on %s: %s", topic, exc)

    def publish_metrics(self, payload: Dict[str, Any]) -> None:
        self._publish(f"{self.topic_prefix}/fleet/metrics", payload)

    def publish_event(self, event: Dict[str, Any]) -> None:
        etype = str(event.get("type", "event"))
        if etype in ("recovery_completed", "robot_recovered", "recovery_started"):
            topic = f"{self.topic_prefix}/events/recovery"
        elif etype in (
            "fault_detected",
            "robot_offline",
            "planner_failure",
            "task_reassigned",
            "recovery_required",
        ):
            topic = f"{self.topic_prefix}/events/fault"
        else:
            topic = f"{self.topic_prefix}/events/{etype.replace('_', '-')}"
        self._publish(topic, event)

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            try:
                disconnect = self._connection.disconnect()
                disconnect.result(timeout=5)
            except Exception:
                pass
            self._connection = None
            self._connected = False


def _safe_call(fn: Any, payload: Dict[str, Any]) -> None:
    try:
        fn(payload)
    except Exception:
        logger.exception("telemetry sink failed")


def _aws_configured() -> bool:
    return bool(
        os.environ.get("AWS_IOT_ENDPOINT")
        and os.environ.get("AWS_IOT_CERT_PATH")
        and os.environ.get("AWS_IOT_KEY_PATH")
    )


def build_aws_sink() -> Optional[AwsIotTelemetrySink]:
    endpoint = os.environ.get("AWS_IOT_ENDPOINT")
    cert = os.environ.get("AWS_IOT_CERT_PATH")
    key = os.environ.get("AWS_IOT_KEY_PATH")
    if not endpoint or not cert or not key:
        return None
    ca = os.environ.get("AWS_IOT_CA_PATH")
    return AwsIotTelemetrySink(
        endpoint=endpoint,
        cert_path=Path(cert),
        key_path=Path(key),
        ca_path=Path(ca) if ca else None,
        client_id=os.environ.get("AWS_IOT_CLIENT_ID", "robofleet"),
        topic_prefix=os.environ.get("AWS_IOT_TOPIC_PREFIX", "robofleet"),
    )


def telemetry_from_env() -> TelemetrySink:
    """Select sink(s) from ``ROBOFLEET_TELEMETRY`` and AWS env vars."""
    mode = (env_get("TELEMETRY") or "").strip().lower()
    default_json = Path(__file__).resolve().parents[2] / "benchmarks" / "telemetry.jsonl"

    if not mode:
        if default_json.parent.exists():
            return JsonTelemetrySink(default_json)
        return NullTelemetrySink()

    if mode == "null" or mode == "off":
        return NullTelemetrySink()
    if mode == "console":
        return ConsoleTelemetrySink()
    if mode == "json":
        path = Path(env_get("TELEMETRY_PATH", str(default_json)) or default_json)
        return JsonTelemetrySink(path)
    if mode == "aws":
        aws = build_aws_sink()
        if aws is None:
            logger.warning("ROBOFLEET_TELEMETRY=aws but AWS IoT env vars missing; using null sink")
            return NullTelemetrySink()
        return aws

    sinks: List[TelemetrySink] = []
    if mode in ("all", "multi"):
        sinks.append(JsonTelemetrySink(default_json))
        aws = build_aws_sink()
        if aws is not None:
            sinks.append(aws)
        else:
            sinks.append(ConsoleTelemetrySink())
        return CompositeTelemetrySink(sinks) if sinks else NullTelemetrySink()

    logger.warning("unknown ROBOFLEET_TELEMETRY=%r; using null sink", mode)
    return NullTelemetrySink()


def telemetry_status(sink: TelemetrySink) -> Dict[str, Any]:
    """Summary for /api/health — never exposes secrets."""
    if isinstance(sink, CompositeTelemetrySink):
        kinds = []
        aws_active = False
        aws_error: Optional[str] = None
        for child in sink.sinks:
            if isinstance(child, JsonTelemetrySink):
                kinds.append("json")
            elif isinstance(child, ConsoleTelemetrySink):
                kinds.append("console")
            elif isinstance(child, AwsIotTelemetrySink):
                kinds.append("aws")
                aws_active = child.active
                aws_error = child.last_error
        return {"telemetry": kinds, "awsConnected": aws_active, "awsError": aws_error}
    if isinstance(sink, AwsIotTelemetrySink):
        return {
            "telemetry": ["aws"],
            "awsConnected": sink.active,
            "awsError": sink.last_error,
        }
    if isinstance(sink, JsonTelemetrySink):
        return {"telemetry": ["json"], "path": str(sink.path)}
    if isinstance(sink, ConsoleTelemetrySink):
        return {"telemetry": ["console"]}
    return {"telemetry": ["null"]}


class TelemetryBridge:
    """Fan-out metrics and significant events from tick snapshots."""

    METRICS_INTERVAL_TICKS = 30

    def __init__(self, sink: TelemetrySink) -> None:
        self.sink = sink

    def on_snapshot(self, snapshot: Dict[str, Any]) -> None:
        tick = int(snapshot.get("tick", 0))
        for event in snapshot.get("events") or []:
            if event.get("type") in TELEMETRY_EVENT_TYPES:
                self.sink.publish_event({**event, "tick": tick})

        if tick <= 1 or tick % self.METRICS_INTERVAL_TICKS == 0:
            metrics = dict(snapshot.get("metrics") or {})
            metrics["tick"] = tick
            metrics["scenario"] = (snapshot.get("scenario") or {}).get("id")
            self.sink.publish_metrics(metrics)

    def close(self) -> None:
        self.sink.close()
