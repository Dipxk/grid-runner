"""FastAPI app: static frontend + a WebSocket that streams tick snapshots.

Design notes
------------
* **One authoritative simulation** runs in a single asyncio task. Clients are
  observers that share the same world, so two browser windows show identical
  state — that also makes the demo easy to show on a second screen.
* **Drift-corrected tick loop.** The loop targets an absolute schedule rather
  than ``sleep(interval)`` after work, so tick spacing stays even. Even spacing
  is what makes client-side interpolation look smooth: the client assumes the
  next snapshot lands exactly one interval later.
* **Snapshots, not deltas.** A tick payload for 20 robots is a few KB; deltas
  would buy little and cost a lot of complexity and bug surface.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import SPEED_PRESETS, SimConfig, config_from_env
from .engine import BLACK_FRIDAY, RESILIENCE_TEST, SimulationEngine
from .telemetry import TelemetryBridge, telemetry_from_env, telemetry_status

logger = logging.getLogger("robofleet")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class ClientChannel:
    """One connected browser, with a bounded outbound queue.

    Writing straight to ``ws.send_text`` from the tick loop is a trap: a
    single stalled client (a backgrounded tab, a paused debugger, a laptop
    that just slept) applies backpressure and freezes the *entire*
    simulation. Each client instead gets a depth-2 queue drained by its own
    task; when a client falls behind we drop the stale snapshot rather than
    the frame rate. Snapshots are self-contained, so a dropped one costs the
    client nothing but a slightly older view for one tick.
    """

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.dropped = 0
        self.task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._writer(), name="ws-writer")

    async def _writer(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                if message is None:
                    return
                await self.ws.send_text(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def offer(self, message: str) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.dropped += 1
            try:
                self.queue.get_nowait()          # discard the stale snapshot
                self.queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            self.task = None


class SimulationRunner:
    """Owns the engine, the tick clock and the set of connected clients."""

    def __init__(self, config: Optional[SimConfig] = None) -> None:
        self.config = config or config_from_env()
        self.engine = SimulationEngine(self.config)
        self.telemetry = TelemetryBridge(telemetry_from_env())
        self.clients: Dict[WebSocket, ClientChannel] = {}
        self.running = True
        self.ticks_per_second = self.config.ticks_per_second
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._resume = asyncio.Event()
        self._resume.set()

    # ------------------------------------------------------------------
    @property
    def tick_interval(self) -> float:
        return 1.0 / max(0.5, self.ticks_per_second)

    def state_header(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "ticksPerSecond": self.ticks_per_second,
            "tickIntervalMs": round(self.tick_interval * 1000, 2),
            "speedPresets": SPEED_PRESETS,
            "fleetSize": len(self.engine.robots),
            "secondsPerTick": self.config.seconds_per_tick,
            "manualDemand": self.engine.manual_demand,
        }

    def _launch_scenario(self, name: str) -> Dict[str, Any]:
        if name == BLACK_FRIDAY["id"]:
            spec = BLACK_FRIDAY
            self.config = SimConfig(
                fleet_size=spec["fleet"],
                seed=spec["seed"],
                initial_tasks=spec["initial_tasks"],
                jam_duration_ticks=spec["duration"] + 40,
            )
            self.engine = SimulationEngine(self.config)
            payload = self.engine.begin_black_friday()
        elif name == RESILIENCE_TEST["id"]:
            spec = RESILIENCE_TEST
            self.config = SimConfig(
                fleet_size=spec["fleet"],
                seed=spec["seed"],
                initial_tasks=spec["initial_tasks"],
                jam_duration_ticks=spec["duration"] + 40,
            )
            self.engine = SimulationEngine(self.config)
            payload = self.engine.begin_resilience_test()
        else:
            return {"scenario": {"ok": False, "reason": "unknown scenario"}}
        self.running = True
        self._resume.set()
        return {
            "scenario": payload,
            "world": self.engine.world_payload(),
            "snapshot": self.engine.snapshot(),
        }

    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="sim-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        next_at = time.perf_counter()
        while True:
            try:
                await self._resume.wait()
                now = time.perf_counter()
                if next_at < now - 1.0:  # recover from long pauses / speed changes
                    next_at = now
                delay = max(0.0, next_at - now)
                if delay:
                    await asyncio.sleep(delay)
                async with self._lock:
                    snapshot = self.engine.step()
                snapshot.update(self.state_header())
                self.telemetry.on_snapshot(snapshot)
                self.broadcast(snapshot)
                next_at += self.tick_interval
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one bad tick kill the simulation
                logger.exception("simulation tick failed; continuing")
                await asyncio.sleep(self.tick_interval)
                next_at = time.perf_counter()

    # ------------------------------------------------------------------
    def broadcast(self, payload: Dict[str, Any]) -> None:
        """Fan a snapshot out to every client without ever awaiting a socket."""
        if not self.clients:
            return
        message = json.dumps(payload, separators=(",", ":"))
        for channel in list(self.clients.values()):
            channel.offer(message)

    async def register(self, ws: WebSocket) -> None:
        channel = ClientChannel(ws)
        channel.start()
        self.clients[ws] = channel
        async with self._lock:
            init = {
                "type": "init",
                "world": self.engine.world_payload(),
                "config": self.config.to_dict(),
                "snapshot": self.engine.snapshot(),
            }
        init.update(self.state_header())
        await ws.send_text(json.dumps(init, separators=(",", ":")))

    async def unregister(self, ws: WebSocket) -> None:
        channel = self.clients.pop(ws, None)
        if channel is not None:
            await channel.close()

    # ------------------------------------------------------------------
    async def handle_command(self, message: Dict[str, Any]) -> Dict[str, Any]:
        action = message.get("action")
        extra: Dict[str, Any] = {}
        async with self._lock:
            if action == "pause":
                self.running = False
                self._resume.clear()
            elif action == "resume":
                self.running = True
                self._resume.set()
            elif action == "toggle":
                self.running = not self.running
                self._resume.set() if self.running else self._resume.clear()
            elif action == "speed":
                tps = float(message.get("value", self.config.ticks_per_second))
                self.ticks_per_second = max(0.5, min(tps, 30.0))
            elif action == "step":
                snapshot = self.engine.step()
                snapshot.update(self.state_header())
                self.telemetry.on_snapshot(snapshot)
                self.broadcast(snapshot)
            elif action == "jam":
                cell = (int(message.get("x", 0)), int(message.get("y", 0)))
                result = self.engine.toggle_jam(cell)
                extra = {"jam": {**result, "cell": list(cell)}}
            elif action == "burst":
                self.engine.add_task_burst(int(message.get("count", 10)))
            elif action == "rush":
                cell = (int(message.get("x", 0)), int(message.get("y", 0)))
                result = self.engine.add_rush_order(cell)
                extra = {"rush": result}
            elif action == "order":
                pickup = (int(message.get("x", 0)), int(message.get("y", 0)))
                dropoff = (int(message.get("dropX", 0)), int(message.get("dropY", 0)))
                result = self.engine.place_order(pickup, dropoff)
                extra = {"order": result}
            elif action == "demand":
                result = self.engine.set_manual_demand(bool(message.get("manual")))
                extra = {"demand": result}
            elif action == "scenario":
                extra = self._launch_scenario(str(message.get("name", "black_friday")))
            elif action == "fleet":
                self.engine.set_fleet_size(int(message.get("value", 12)))
            elif action == "fault":
                robot_id = int(message.get("robot", 0))
                fault_type = str(message.get("type", "robot_offline"))
                params = message.get("params") or {}
                result = self.engine.inject_fault(robot_id, fault_type, params)
                extra = {"fault": result}
            elif action == "clear_fault":
                robot_id = int(message.get("robot", 0))
                result = self.engine.clear_fault(robot_id)
                extra = {"fault": result}
            elif action == "reset":
                seed = int(message.get("seed", self.config.seed + 1))
                self.config = self.config.replace(
                    seed=seed, fleet_size=len(self.engine.robots)
                )
                self.engine = SimulationEngine(self.config)
            else:
                return {"type": "ack", "ok": False, "reason": "unknown action"}
        header = self.state_header()
        header.update({"type": "ack", "ok": True, "action": action, **extra})
        return header


def create_app(config: Optional[SimConfig] = None) -> FastAPI:
    runner = SimulationRunner(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await runner.start()
        try:
            yield
        finally:
            runner.telemetry.close()
            await runner.stop()

    app = FastAPI(title="RoboFleet", version="1.0.0", lifespan=lifespan)
    app.state.runner = runner

    @app.middleware("http")
    async def allow_embed(request, call_next):
        # Let the portfolio (and any other site) iframe the live demo.
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        return response

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "tick": runner.engine.tick,
                "fleet": len(runner.engine.robots),
                "clients": len(runner.clients),
                **telemetry_status(runner.telemetry.sink),
            }
        )

    @app.get("/api/state")
    async def state() -> JSONResponse:
        payload: Dict[str, Any] = {
            "world": runner.engine.world_payload(),
            "snapshot": runner.engine.snapshot(),
        }
        payload.update(runner.state_header())
        return JSONResponse(payload)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await runner.register(ws)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ack = await runner.handle_command(message)
                await ws.send_text(json.dumps(ack, separators=(",", ":")))
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("websocket error: %s", exc)
        finally:
            await runner.unregister(ws)

    if FRONTEND_DIR.exists():
        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html")

        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")

    return app


app = create_app()
