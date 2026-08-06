# Data Pipeline Integration Plan

## Goal

Align the data pipeline with the current boundary: control packages control; `data_collection_pkg` observes, records, validates, classifies, and replays ROS2 data streams.

## Phase 1 - Source-Aware Recording

Status: complete

- Move HTTP API action recording away from teleop topics.
- Add collector parameters for `source`, `dataset_schema`, and `action_topic`.
- Preserve existing teleop defaults.
- Verify metadata records `source`, `runtime_mode`, `action_schema`, and `converted_from`.

## Phase 2 - Three Input Sources

Status: in_progress

- Teleop records from `/pika/teleop/servo_l_command`.
- HTTP API records from `/ur5e/control/action_event`.
- Policy records from `/model/action`.
- `trainable` stores only teleop and policy data.
- HTTP API action events are stored under `debug/http_api/action`.
- HTTP API delta end-effector actions are stored under `debug/http_api/delta_ee_pose`.
- HTTP API events are emitted by an independent proxy bridge, not by the control node.
- Gripper state topic is configurable so Robotiq can replace the default PIKA topic.

## Phase 3 - Macro Events

Status: pending

- Keep `macro/auto_grasp`.
- Record auto grasp as macro event data, not as a fourth independent control source.

## Phase 4 - Integration Validation

Status: in_progress

- Run local unit tests.
- Run ROS2 topic smoke tests in workspace.
- Validate URSim/RViz replay.
- Run low-speed real robot recording only after simulation checks pass.

## Phase 5 - ACT-Style Teleop Demonstration Capture

Status: in_progress

- Keep RTDE/ROS2 teleoperation control packages responsible only for robot control.
- Add fixed-rate data collection that records hardware observations directly.
- Generate training `action` from the next sampled joint/gripper state so the
  dataset uses `qpos_gripper` rather than end-effector teleop commands.
- Preserve raw `/teleop/command` payloads as metadata for debugging when available.
- Provide a dedicated launch file for `trainable/policy/qpos_gripper` teleop demos.
