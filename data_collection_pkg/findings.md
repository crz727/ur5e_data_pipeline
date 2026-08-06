# Findings

## ACT Teleop Demonstration Data

- Current RTDE teleop bridge actions are end-effector servoL commands:
  `[x, y, z, rx, ry, rz, gripper]`.
- ACT training target is planned as joint-space commands:
  `[q1, q2, q3, q4, q5, q6, gripper]`.
- Therefore RTDE end-effector commands should not be the primary training labels
  for ACT. They remain useful as debug metadata.
- The preferred first implementation is fixed-rate hardware-state sampling:
  `observation_t = qpos_t + gripper_t + images_t`, `action_t = qpos_{t+1} + gripper_{t+1}`.
- This avoids IK ambiguity and keeps teleoperation control independent from data
  labeling, but requires episode start/stop discipline and later filtering of
  long static intervals.

## Current Boundary

- Directory classification remains schema-based: `trainable`, `macro`, `debug`.
- Source must be metadata, not a directory classifier.
- `data_collection_pkg` must not call HTTP, access hardware, or control the robot.

## Current Implementation

- `TeleopJsonlRecorder` currently hardcodes `source=teleop`, `runtime_mode=teleop`, and `teleop_servo_l_pose`.
- HTTP API action recording was previously bridged to `/pika/teleop/servo_l_command`; this must move to `/ur5e/control/action_event` to avoid source pollution.
- `auto_grasp` still exists in the control layer as a HTTP API macro flow, so it should remain as `macro/auto_grasp`.
- Custom action topics require two separate changes: the message adapter must preserve the actual action topic, and the collector engine must trigger on the configured action topic.
- HTTP API `/api/control/qpos` and `/api/control/action` can be recorded as `qpos_gripper`.
- HTTP API `ee_pose` should not be forced into `qpos_gripper`; it needs a separate schema decision or should remain command audit only.
- Updated boundary: `trainable` now contains only teleop and policy data.
- HTTP API actions should use `http_api_action` under `debug/http_api/action`, with the original command schema stored inside the action payload.
- `delta_ee_pose` belongs under HTTP API debug data, not policy trainable data.
- HTTP API debug collection should run separate collectors per schema/topic because one collector writes to one schema directory.
- HTTP action audit uses `/ur5e/control/action_event`; HTTP delta ee pose uses `/ur5e/control/delta_ee_pose_event`; auto grasp uses `/auto_grasp/event`.
- To avoid touching the real-robot-tested control node, HTTP API data events are now produced by an independent proxy bridge instead of `ros_controller.py`.
- Data pipeline had a PIKA topic-name dependency on `/pika/gripper/state`; this is now parameterized as `gripper_state_topic`.
