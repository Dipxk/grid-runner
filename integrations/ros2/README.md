# Optional ROS 2 adapter

Grid Runner remains **framework-independent**. This directory documents how the
simulator could bridge to ROS 2 without requiring ROS at runtime.

## Topic mapping

| Grid Runner | ROS 2 concept |
|-------------|---------------|
| `snapshot.robots[]` | `/grid_runner/fleet_state` |
| `snapshot.events[]` | `/grid_runner/events` |
| per-robot payload | `/grid_runner/robot/{id}/state` |

## Commands

Dispatcher actions (jam, order, fault inject) map to services/actions on the
bridge node — not inside the core engine.

## Status

Adapter interfaces only. Install ROS 2 locally to implement a minimal bridge;
the main application does not depend on `rclpy`.
