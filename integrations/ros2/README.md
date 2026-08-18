# Optional ROS 2 bridge

RoboFleet runs **without ROS**. This package bridges live simulation snapshots
to ROS 2 when you choose to run it.

```
ROS 2 bridge (rclpy)
        │
        ▼ WebSocket
RoboFleet FastAPI server
        │
        ▼
SimulationEngine (unchanged)
```

## Topics

| Topic | Type | Content |
| --- | --- | --- |
| `/grid_runner/fleet_state` | `std_msgs/String` | JSON tick + metrics summary |
| `/grid_runner/events` | `std_msgs/String` | JSON fault/delivery events |
| `/grid_runner/robot/{id}/state` | `std_msgs/String` | Full robot snapshot |
| `/grid_runner/robot/{id}/pose` | `geometry_msgs/Pose2D` | Robot grid position |

## Command interface

Publish JSON to `/grid_runner/command`:

```json
{"action":"fault","robot":7,"type":"robot_offline"}
{"action":"clear_fault","robot":7}
{"action":"pause"}
{"action":"resume"}
```

Service `/grid_runner/ping` (`std_srvs/Trigger`) returns bridge liveness.

## Build and run

**Not executed in CI** — requires a local ROS 2 install.

```bash
# Terminal 1 — RoboFleet
make run

# Terminal 2 — ROS 2 (after sourcing your distro)
cd integrations/ros2/grid_runner_bridge
pip install websockets
colcon build --packages-select grid_runner_bridge
source install/setup.bash
ros2 run grid_runner_bridge bridge_node --ros-args -p grid_runner_url:=ws://127.0.0.1:8000/ws
```

Verify:

```bash
ros2 topic echo /grid_runner/fleet_state
ros2 service call /grid_runner/ping std_srvs/srv/Trigger
ros2 topic pub --once /grid_runner/command std_msgs/msg/String \
  "{data: '{\"action\":\"fault\",\"robot\":0,\"type\":\"slow_robot\"}'}"
```

## Status

Bridge **source code is implemented** in this repository. Runtime verification
requires ROS 2 + `rclpy` on the host running the bridge node.
