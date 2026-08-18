#!/usr/bin/env python3
"""Bridge Grid Runner WebSocket snapshots to ROS 2 topics.

Dependency direction:
    ROS 2 bridge  →  Grid Runner HTTP/WebSocket API
NOT:
    Grid Runner core  →  ROS required

Run (requires ROS 2 + rclpy + websockets installed):
    ros2 run grid_runner_bridge bridge_node --ros-args -p grid_runner_url:=ws://127.0.0.1:8000/ws
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, Optional

try:
    import rclpy
    from geometry_msgs.msg import Pose2D
    from rclpy.node import Node
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    ROS_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without ROS
    ROS_AVAILABLE = False
    Node = object  # type: ignore


class GridRunnerBridge(Node):
    """Subscribe to Grid Runner ticks and republish as ROS 2 messages."""

    def __init__(self) -> None:
        super().__init__("grid_runner_bridge")
        self.url = self.declare_parameter("grid_runner_url", "ws://127.0.0.1:8000/ws").value
        self.fleet_pub = self.create_publisher(String, "/grid_runner/fleet_state", 10)
        self.events_pub = self.create_publisher(String, "/grid_runner/events", 10)
        self.robot_pubs: Dict[int, Any] = {}
        self.pose_pubs: Dict[int, Any] = {}
        self.command_sub = self.create_subscription(
            String,
            "/grid_runner/command",
            self._on_command,
            10,
        )
        self.ping_srv = self.create_service(Trigger, "/grid_runner/ping", self._on_ping)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._ws_loop(), self._loop)
        self.get_logger().info("Grid Runner bridge listening on %s" % self.url)

    def _run_async_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _ws_loop(self) -> None:
        import websockets

        while rclpy.ok():
            try:
                async with websockets.connect(self.url) as ws:
                    init = json.loads(await ws.recv())
                    self.get_logger().info(
                        "connected tick=%s fleet=%s"
                        % (
                            init.get("snapshot", {}).get("tick", 0),
                            init.get("fleetSize", "?"),
                        )
                    )
                    while rclpy.ok():
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") == "tick":
                            self._publish_snapshot(msg)
            except Exception as exc:
                self.get_logger().warning("websocket reconnect in 2s: %s" % exc)
                await asyncio.sleep(2.0)

    def _robot_pub(self, robot_id: int):
        if robot_id not in self.robot_pubs:
            topic = f"/grid_runner/robot/{robot_id}/state"
            self.robot_pubs[robot_id] = self.create_publisher(String, topic, 10)
            self.pose_pubs[robot_id] = self.create_publisher(
                Pose2D, f"/grid_runner/robot/{robot_id}/pose", 10
            )
        return self.robot_pubs[robot_id], self.pose_pubs[robot_id]

    def _publish_snapshot(self, snap: Dict[str, Any]) -> None:
        fleet_msg = String()
        fleet_msg.data = json.dumps(
            {
                "tick": snap.get("tick"),
                "metrics": snap.get("metrics"),
                "robots": len(snap.get("robots") or []),
            },
            separators=(",", ":"),
        )
        self.fleet_pub.publish(fleet_msg)

        for event in snap.get("events") or []:
            ev = String()
            ev.data = json.dumps(event, separators=(",", ":"))
            self.events_pub.publish(ev)

        for robot in snap.get("robots") or []:
            rid = int(robot["id"])
            state_pub, pose_pub = self._robot_pub(rid)
            body = String()
            body.data = json.dumps(robot, separators=(",", ":"))
            state_pub.publish(body)
            pose = Pose2D()
            pose.x = float(robot.get("x", 0))
            pose.y = float(robot.get("y", 0))
            pose_pub.publish(pose)

    def _on_command(self, msg: String) -> None:
        """JSON commands, e.g. {\"action\":\"fault\",\"robot\":3,\"type\":\"slow_robot\"}."""
        asyncio.run_coroutine_threadsafe(self._send_command(msg.data), self._loop)

    async def _send_command(self, payload: str) -> None:
        import websockets

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.get_logger().error("invalid JSON command")
            return
        try:
            async with websockets.connect(self.url) as ws:
                await ws.recv()  # init
                await ws.send(json.dumps(data))
                ack = json.loads(await ws.recv())
                self.get_logger().info("command ack: %s" % ack.get("ok"))
        except Exception as exc:
            self.get_logger().error("command failed: %s" % exc)

    def _on_ping(self, _request, response):
        response.success = True
        response.message = "grid_runner_bridge alive"
        return response


def main(args=None) -> None:
    if not ROS_AVAILABLE:
        raise SystemExit(
            "rclpy not installed — source ROS 2 and install dependencies before running the bridge."
        )
    rclpy.init(args=args)
    node = GridRunnerBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
