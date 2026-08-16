"""Integration tests for the HTTP + WebSocket surface."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import SimConfig
from app.server import create_app


def make_client() -> TestClient:
    config = SimConfig(width=20, height=14, margin=1, fleet_size=6, ticks_per_second=20.0)
    return TestClient(create_app(config))


def test_health_and_state_endpoints():
    with make_client() as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["fleet"] == 6

        state = client.get("/api/state").json()
        assert state["world"]["width"] == 20
        assert state["snapshot"]["type"] == "tick"
        assert state["tickIntervalMs"] > 0


def test_websocket_sends_init_then_streams_ticks():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            assert init["type"] == "init"
            assert init["world"]["cells"]
            assert init["snapshot"]["robots"]
            assert init["tickIntervalMs"] > 0

            ticks = []
            for _ in range(3):
                msg = ws.receive_json()
                if msg["type"] == "tick":
                    ticks.append(msg)
            assert ticks, "no tick frames received"
            assert ticks[-1]["tick"] >= ticks[0]["tick"]
            assert ticks[-1]["metrics"]["collisions"] == 0


def test_websocket_commands_are_acknowledged():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # init

            ws.send_text(json.dumps({"action": "pause"}))
            ack = _next_ack(ws)
            assert ack["ok"] and ack["running"] is False

            ws.send_text(json.dumps({"action": "burst", "count": 5}))
            assert _next_ack(ws)["ok"]

            ws.send_text(json.dumps({"action": "speed", "value": 12}))
            ack = _next_ack(ws)
            assert ack["ticksPerSecond"] == 12

            ws.send_text(json.dumps({"action": "fleet", "value": 9}))
            assert _next_ack(ws)["fleetSize"] == 9

            ws.send_text(json.dumps({"action": "jam", "x": 5, "y": 5}))
            assert _next_ack(ws)["ok"]

            ws.send_text(json.dumps({"action": "resume"}))
            assert _next_ack(ws)["running"] is True


def test_step_command_advances_exactly_one_tick_while_paused():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            ws.send_text(json.dumps({"action": "pause"}))
            _next_ack(ws)

            runner = client.app.state.runner
            before = runner.engine.tick
            ws.send_text(json.dumps({"action": "step"}))
            _next_ack(ws)
            assert runner.engine.tick == before + 1
            assert init["type"] == "init"


def test_jam_ack_reports_added_cleared_and_refused_cells():
    """The UI shows toasts straight off this ack, so it must tell the truth."""
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            ws.send_text(json.dumps({"action": "pause"}))
            _next_ack(ws)

            world = client.app.state.runner.engine.world
            aisle = next(
                cell
                for cell in world.passable_cells()
                if world.cell_type(cell) not in ("dropoff", "charger")
            )
            dropoff = client.app.state.runner.engine.world.dropoffs[0]

            ws.send_text(json.dumps({"action": "jam", "x": aisle[0], "y": aisle[1]}))
            ack = _next_ack(ws)
            assert ack["jam"] == {"ok": True, "action": "added", "cell": list(aisle)}

            ws.send_text(json.dumps({"action": "jam", "x": aisle[0], "y": aisle[1]}))
            assert _next_ack(ws)["jam"]["action"] == "cleared"

            ws.send_text(json.dumps({"action": "jam", "x": dropoff[0], "y": dropoff[1]}))
            refused = _next_ack(ws)["jam"]
            assert refused["ok"] is False and refused["cell"] == list(dropoff)
            assert init["type"] == "init"


def test_rush_and_scenario_commands_are_acknowledged():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            pickup = client.app.state.runner.engine.world.pickups[0]
            ws.send_text(json.dumps({"action": "rush", "x": pickup[0], "y": pickup[1]}))
            ack = _next_ack(ws)
            assert ack["rush"]["ok"] is True
            assert ack["rush"]["cell"] == list(pickup)

            ws.send_text(json.dumps({"action": "scenario", "name": "black_friday"}))
            sc = _next_ack(ws)
            assert sc["scenario"]["id"] == "black_friday"
            assert sc["world"]["width"] >= 1
            assert sc["fleetSize"] == 32


def test_order_and_demand_commands_are_acknowledged():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            engine = client.app.state.runner.engine
            pickup = engine.world.pickups[0]
            dropoff = engine.world.dropoffs[0]
            ws.send_text(
                json.dumps(
                    {
                        "action": "order",
                        "x": pickup[0],
                        "y": pickup[1],
                        "dropX": dropoff[0],
                        "dropY": dropoff[1],
                    }
                )
            )
            ack = _next_ack(ws)
            assert ack["order"]["ok"] is True
            assert ack["order"]["pickup"] == list(pickup)
            assert ack["order"]["dropoff"] == list(dropoff)

            ws.send_text(json.dumps({"action": "demand", "manual": True}))
            demand = _next_ack(ws)
            assert demand["demand"]["manual"] is True
            assert demand["manualDemand"] is True


def test_unknown_command_is_rejected_cleanly():
    with make_client() as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_text(json.dumps({"action": "self-destruct"}))
            ack = _next_ack(ws)
            assert ack["ok"] is False


def _next_ack(ws, limit: int = 40):
    """Skip over tick frames until the command acknowledgement arrives."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == "ack":
            return msg
    raise AssertionError("no ack received")
