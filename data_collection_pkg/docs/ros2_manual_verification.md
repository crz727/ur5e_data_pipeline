# ROS2 Manual Verification

Use this guide on the ROS2 machine. The local Windows test environment only
checks Python code and import boundaries; ROS2 behavior must be verified in a
ROS2 workspace with URSim/RViz available.

## Build

```bash
cd ~/ur5e_ws
colcon build --symlink-install --packages-select data_collection_pkg
source install/setup.bash
```

## Teleop Collection

Start the collector:

```bash
ros2 run data_collection_pkg data_collection_collector_node --ros-args \
  -p root:=/tmp/ur5e_datasets \
  -p task:=teleop_pick
```

In another terminal, confirm outputs:

```bash
ros2 topic echo /data_collection/quality_status
ros2 topic echo /data_collection/drop_reason
```

Required input topics:

```text
/joint_states
/teleop/command
/gripper/state
```

Optional but recommended:

```text
/camera2/scene_camera/color/image_raw/compressed
/camera1/wrist_camera/color/image_raw/compressed
/safety/state
/tool0/pose
```

`/tool0/pose` is a `geometry_msgs/PoseStamped` stream for the end-effector pose
in the base frame. When present, it is stored as `observation.ee_pose` and
`observation.tool_pose`.

After teleoperation, confirm data exists:

```bash
find /tmp/ur5e_datasets/trainable/teleop/twist_gripper -maxdepth 3 -type f
```

Run offline quality check:

```bash
ros2 run data_collection_pkg data_collection quality-check \
  /tmp/ur5e_datasets/trainable/teleop/twist_gripper
```

Run stricter trainable checks when recording data for training:

```bash
ros2 run data_collection_pkg data_collection quality-check \
  /tmp/ur5e_datasets/trainable/teleop/twist_gripper \
  --profile trainable \
  --required-camera external \
  --required-camera wrist \
  --max-sync-delta-s 0.07 \
  --target-fps 10.0 \
  --fps-tolerance-ratio 0.2 \
  --min-frame-count 20 \
  --min-duration-s 2.0 \
  --require-ee-pose
```

Run replay-readiness checks before URSim/RViz playback:

```bash
ros2 run data_collection_pkg data_collection quality-check \
  /tmp/ur5e_datasets/trainable/teleop/twist_gripper \
  --profile replay
```

## Topology And Flow Visualization

Start real-time topology and flow monitoring plus the read-only Web dashboard:

```bash
ros2 launch data_collection_pkg data_collection_monitor.launch.py \
  publish_rate_hz:=2.0 \
  active_age_s:=0.5 \
  dashboard_host:=0.0.0.0 \
  dashboard_port:=8765
```

Open the dashboard:

```text
http://<robot-host>:8765
```

Inspect which nodes publish/subscribe to each topic:

```bash
ros2 topic echo /data_collection/topology_graph
```

Inspect which monitored data streams are active or stale:

```bash
ros2 topic echo /data_collection/flow_status
```

Expected behavior:

```text
topology_graph publishes JSON with topics, publishers, subscribers, and edges
flow_status publishes JSON with seen, active, age_s, topic_type, publishers, and subscribers
active becomes false when a monitored topic has no message within active_age_s
the Web dashboard shows active/stale/unseen topics, graph edges, quality status, drop reason, and replay status
```

## Replay To URSim And RViz

Start URSim and RViz using the project control stack first. Then start replay:

```bash
ros2 launch data_collection_pkg data_collection_replay.launch.py \
  dataset_dir:=/tmp/ur5e_datasets/trainable/teleop/twist_gripper \
  episode_index:=0 \
  rate_hz:=10.0 \
  sim_command_topic:=/ur_control/sim/replay_command \
  frame_id:=base
```

Inspect replay topics:

```bash
ros2 topic echo /data_collection/replay/status
ros2 topic echo /data_collection/replay/action
ros2 topic echo /data_collection/replay/observation
ros2 topic echo /ur_control/sim/replay_command
```

In RViz, add a Marker display for:

```text
/data_collection/replay/marker
```

Expected behavior:

```text
replay/status publishes started, running, then done
replay/action publishes one JSON action per frame
sim_command_topic receives execute_real=false commands
RViz shows a line strip path for teleop_twist_gripper actions
```

If the URSim control package expects a different simulation command topic,
change `sim_command_topic` in the launch command. The data package must not
publish to real robot execution topics unless a separate real replay path is
explicitly enabled.
