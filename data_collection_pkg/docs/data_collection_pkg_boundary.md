# data_collection_pkg Boundary

## Current Implementation Shape

This export is a standalone ROS2 `ament_python` package named
`data_collection_pkg`. It can be copied into another ROS2 workspace as a sibling
package and built with `colcon`.

This gives the workspace one callable data pipeline module:

```text
data_collection_pkg
```

The original development repository kept this module inside a broader
`ur5e_http_api` package. This export has already performed that split so the
data layer can move without the HTTP/control API.

## Data Package Responsibility

`data_collection_pkg` owns:

```text
data collection
data classification
real-time quality checks
offline quality checks
topology graph generation
data-flow status summaries
JSONL debug writing
official LeRobotDataset writing
dry-run replay simulation
ROS2 node entry points for the data pipeline
publish-only teleop mirroring entry point
```

Real-time topology and flow visibility is provided by:

```text
data_collection_topology_monitor_node
data_collection_web_dashboard_node
```

It publishes:

```text
/data_collection/topology_graph
/data_collection/flow_status
```

`topology_graph` reports ROS2 graph relationships: topics, publishers,
subscribers, and publisher-to-subscriber edges. `flow_status` reports monitored
topic heartbeat status: seen, active/stale, latest timestamp, age, topic type,
publisher count, subscriber count, and endpoint names.

`data_collection_web_dashboard_node` subscribes only to data-collection status
topics and serves a read-only browser dashboard. It displays topology, flow,
quality, drop reason, and replay status. It must not publish control commands,
modify ROS2 topics, or make safety decisions.

The browser page is a compatibility client. The supported operator client is
the Qt/RViz panel, which uses the Dashboard HTTP API routes.

It does not read data from HTTP.

All reusable data-pipeline code is kept under `data_collection_pkg`:

```text
data_collection_pkg/
  dataset/
    schemas.py
    jsonl_writer.py
    lerobot_writer.py
    quality.py

  ros_capture/
    collector_node.py
    quality_monitor_node.py
    teleop_bridge_node.py       # reserved action-collection entry point

  action_replay/
    replay_simulator.py
    replay_simulator_node.py
    replay_topics.py
    rviz_markers.py
    ursim_rviz_adapter_node.py

  visualization/
    topology.py
    topology_monitor_node.py
    web_dashboard.py
    web_dashboard_node.py

  cli.py
```

The old `ur5e_lerobot_dataset` package is removed from the current boundary.
Useful dataset writing, LeRobot writing, and quality-checking behavior has been
merged into `data_collection_pkg.dataset`. HTTP clients and HTTP replay routing
are deleted because they are not portable across ROS2-only projects.

## Classification

Top-level categories:

```text
original
trainable
macro
debug
```

Original hardware-state qpos datasets:

```text
original/teleop/qpos_gripper
original/http/qpos_gripper
original/act/qpos_gripper
original/vla/qpos_gripper
```

`original/policy/qpos_gripper` remains readable for historical compatibility;
new capture requests use `act` or `vla` instead.

Cleaned trainable qpos datasets:

```text
trainable/policy/qpos_gripper
trainable/teleop/qpos_gripper
trainable/http/qpos_gripper
trainable/teleop/twist_gripper
```

Macro and debug schemas:

```text
macro/auto_grasp
debug/http_api/action
debug/http_api/delta_ee_pose
debug/replay
```

For qpos hardware demonstrations, `runtime_mode` is both metadata and the
second-level directory under `original` or `trainable`:

```json
{
  "source": "teleop",
  "runtime_mode": "teleop",
  "dataset_stage": "original",
  "action_schema": "qpos_gripper",
  "converted_from": "future_joint_state"
}
```

## Operation Layer Packaging

Operation-layer code can be grouped, but only as orchestration.

Recommended split:

```text
operation_orchestration_pkg or launch_system_pkg
```

This package may own:

```text
mode selection
launch composition
operator workflow
start/stop coordination
high-level state display
```

It should not absorb:

```text
real UR5e control implementation
camera driver implementation
calibration implementation
teleop control implementation
VLA inference implementation
TF broadcaster implementation
data collection implementation
```

The reason is simple: the operator can still call one workflow, while each
hardware or data subsystem keeps a clean responsibility boundary.

## Replay Boundary

Default replay is dry-run simulation:

```text
dataset -> data_collection_pkg.action_replay.replay_simulator -> /data_collection/replay/...
```

The boundary includes a URSim plus RViz visualization replay path:

```text
dataset
-> data_collection_pkg.action_replay.replay_simulator_node
-> /data_collection/replay/action
-> ursim_rviz_replay_adapter_node
-> ur_control_pkg simulation interface
-> URSim
-> RViz
```

This path is for action visualization and simulation validation. URSim owns the
robot simulation target. RViz owns visual inspection of joint motion, TF, end
effector path, and optional markers. `data_collection_pkg` owns only the replay
data stream, replay status, and adapter entry point boundary.

The adapter may publish or forward simulation-safe commands only to the
simulation interface exposed by `ur_control_pkg`. It must not publish to real
robot execution topics unless the user explicitly enables the separate real
execution path.

RViz visualization should show:

```text
joint state playback
tool/end-effector pose
planned or replayed path markers
frame index / timestamp status
drop or quality warning markers when available
```

Real robot replay remains out of the first implementation and must require an
explicit `execute_real:=true` path with safety state checks, speed limits, human
confirmation, and failure-stop behavior.

## Quality-Check Profiles

`data_collection_pkg.dataset.quality` now exposes three validation profiles:

```text
basic
trainable
replay
```

`basic` is the default and keeps compatibility with the first implementation.
It checks metadata, episode data files, finite and monotonic timestamps,
7-dimensional observation state, action schema dimensions, mapping actions for
macro/debug schemas, and inactive safety flags.

`trainable` extends `basic` for model training data. It can check required
cameras, camera/frame synchronization, encoded image decodability, declared
image size, qpos/qvel/effort/gripper ranges, action ranges, adjacent action
step limits, target frame rate, jitter tolerance, minimum frame count, minimum
duration, and safety field completeness.

`replay` extends validation for replay preparation. It checks that each frame
can construct a replay request for its schema before dry-run or URSim/RViz
playback. Simulation tracking error and real robot execution safety gates remain
integration-level checks outside offline JSONL validation.

## End-Effector Pose Recording

The teleop collector can record an optional end-effector pose stream from
`/tool0/pose` as `geometry_msgs/PoseStamped`. When synchronized with a teleop
frame, the pose is stored in two observation fields:

```text
ee_pose = [x, y, z, qx, qy, qz, qw]
tool_pose = {frame_id, child_frame_id, pose, timestamp}
```

The field is optional at collection time for backward compatibility. Dataset
release checks can require it with `quality-check --require-ee-pose`.

## LeRobot Dataset Visualization

`data_collection lerobot-viz` opens the official LeRobot/Rerun visualization for
either an existing LeRobotDataset or a project JSONL dataset converted on
demand. It does not publish ROS2 topics, touch URSim/RViz, or execute robot
commands. The command launches only the fixed `lerobot-dataset-viz` tool with
structured arguments.
