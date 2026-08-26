# data_collection_pkg

Standalone ROS2 data-pipeline package for UR5e teleoperation datasets.

This export is designed to be copied directly into another ROS2 workspace and
reused without the original `ur5e_http_api` control/API package. It contains:

- Fixed-rate hardware-state collection node.
- Dataset classification and JSONL episode writer.
- Offline quality gates for `basic`, `trainable`, and `replay` profiles.
- Optional official LeRobotDataset conversion and LeRobot/Rerun visualization.
- Realtime topology and data-flow monitor.
- Flask Dashboard API backend for the Qt/RViz panel, plus an optional
  compatibility browser page.
- Simulation-safe replay publisher plus URSim/RViz adapter.
- Data-pipeline unit tests and manual real-robot validation docs.

## Directory Layout

```text
data_collection_pkg/
  data_collection_pkg/      Python source
  launch/                   monitor and replay launch files
  docs/                     package boundary and validation guides
  test/                     data-pipeline tests
  package.xml               ROS2 package manifest
  setup.py                  ament_python entry points
  requirements.txt          offline Python runtime dependencies
  requirements-lerobot.txt  optional LeRobot dependency
  requirements-dev.txt      test dependency helper
```

## Install In A ROS2 Workspace

```bash
mkdir -p ~/ur5e_ws/src
cp -r "D:/data_pipline_Integration testing" ~/ur5e_ws/src/data_collection_pkg
cd ~/ur5e_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select data_collection_pkg
source install/setup.bash
```

Quick sanity check:

```bash
ros2 run data_collection_pkg data_collection list-schemas
ros2 pkg executables data_collection_pkg
```

## Read-Only Hardware Interface Check

Before enabling HTTP API or teleoperation control, verify the hardware data
interfaces only:

```bash
ros2 run data_collection_pkg hardware_interface_check --ros-args \
  -p timeout_s:=3.0 \
  -p gripper_state_topic:=/binary_gripper_state \
  -p gripper_state_msg_type:=std_msgs.msg:Int8 \
  -p require_cameras:=false
```

For Robotiq drivers that publish a custom message, pass the actual type, for
example:

```bash
ros2 run data_collection_pkg hardware_interface_check --ros-args \
  -p gripper_state_topic:=/robotiq/input \
  -p gripper_state_msg_type:=robotiq_2f_msgs/msg/Robotiq2FGripperRobotInput
```

This tool subscribes and prints a JSON report. It does not publish robot
commands, call HTTP API endpoints, start teleoperation, or write dataset frames.

## Main Commands

List schemas:

```bash
ros2 run data_collection_pkg data_collection list-schemas
```

Start legacy action-triggered teleop recording:

```bash
ros2 run data_collection_pkg data_collection_collector_node --ros-args \
  -p root:=/tmp/ur5e_datasets \
  -p task:=teleop_pick
```

The command above and `data_collection_teleop_ur_ros2.launch.py` are retained
as compatibility paths for action-triggered teleop datasets. They are not the
default path for new ACT/VLA demonstrations.

Start `teleop_ur_ros2` recording from the independent teleop data bridge:

```bash
ros2 launch data_collection_pkg data_collection_teleop_ur_ros2.launch.py \
  root:=/tmp/ur5e_datasets \
  task:=teleop_ur_ros2 \
  gripper_state_topic:=/gripper/state
```

Start original hardware qpos recording. This is the recommended fixed-rate
path for teleop, HTTP, ACT, and VLA capture profiles:

```bash
ros2 launch data_collection_pkg data_collection_hardware_qpos.launch.py \
  root:=/tmp/ur5e_datasets \
  task:=teleop_pick_place_demo \
  dataset_stage:=original \
  runtime_mode:=teleop \
  sample_rate_hz:=15.0
```

Use `runtime_mode:=teleop`, `runtime_mode:=http`, `runtime_mode:=act`, or
`runtime_mode:=vla` to classify captures. These values are capture profiles,
not robot control modes: every profile writes fixed-rate frames to
`original/<runtime_mode>/qpos_gripper`, and control ownership remains with the
independent Mode Manager. Each frame uses the current hardware observation as
`observation` and the next sampled joint/gripper state as `action`, so the
action space matches ACT-style `[q1, q2, q3, q4, q5, q6, gripper]` policies.
Bridge or HTTP action events are not required for this path. Existing
`original/policy/qpos_gripper` datasets remain readable for historical replay
and export, but new capture requests should use `act` or `vla`.

The hardware qpos launch defaults to `/binary_gripper_state`
(`std_msgs.msg:Int8`) and stores its `0/1` value as the seventh state/action
dimension. Override both `gripper_state_topic` and `gripper_state_msg_type`
together when using another hardware interface. The Qt/RViz model display may
continue to use `/robotiq_2f_gripper/joint_states` (`JointState`); that topic
is a separate visualization input and is not the fixed-rate collector default.

Task and language annotations are optional at collector startup. The dashboard
omits empty `task_id`, English, and Chinese launch arguments so a no-language
capture starts normally. VLA export preflight still requires a valid English
instruction for an episode to be included in a VLA dataset.

Run trainable dataset quality checks:

```bash
ros2 run data_collection_pkg data_collection quality-check \
  /tmp/ur5e_datasets/trainable/teleop/twist_gripper \
  --profile trainable \
  --required-camera external \
  --required-camera wrist \
  --max-sync-delta-s 0.07 \
  --target-fps 15.0 \
  --min-frame-count 20 \
  --min-duration-s 2.0 \
  --require-ee-pose
```

Create a high-quality sibling dataset from an annotated original qpos capture:

```bash
ros2 run data_collection_pkg data_collection clean-original \
  /tmp/ur5e_datasets/original/teleop/qpos_gripper
```

The command never edits `original`. It replaces the sibling output at
`cleaned/teleop/qpos_gripper` and writes an audit manifest, JSON summary, and
readable `meta/cleaning_report.html`. Only episodes explicitly annotated
`success` and passing the camera, timing, state/action, and safety gates are
copied. Failed annotations are rejected; unannotated episodes remain in the
report as `needs_review`.

Start realtime monitor and dashboard:

```bash
ros2 launch data_collection_pkg data_collection_monitor.launch.py \
  dashboard_host:=0.0.0.0 \
  dashboard_port:=8765 \
  capture_root:=/tmp/ur5e_datasets
```

Open:

```text
http://<robot-host>:8765
```

The dashboard is a data-collection workbench. It can start and stop only the
fixed-rate hardware qpos collector, writing to:

```text
original/teleop/qpos_gripper
original/http/qpos_gripper
original/act/qpos_gripper
original/vla/qpos_gripper
```

It does not start robot drivers, HTTP control, teleoperation, or policy
execution.

## Compatibility and Reserved Entrypoints

The following items are intentionally retained and marked rather than removed:

| Item | Status | Scope |
| --- | --- | --- |
| `web_dashboard.py` `/` page | Compatibility browser UI | Qt uses the `/api/...` routes; the browser page is optional. |
| `data_collection_http_api.launch.py` | Legacy HTTP event audit | Collects `http_api_action`, `delta_ee_pose`, and `auto_grasp` events; it is separate from the current `http` capture profile. |
| `data_collection_teleop_ur_ros2.launch.py` | Legacy action-triggered teleop | Keeps `teleop_twist_gripper` data compatibility. |
| `data_collection_teleop_demo_qpos.launch.py` | Older qpos launch | Retained for historical scripts; new captures use `data_collection_hardware_qpos.launch.py`. |
| `teleop_bridge_node` | Reserved action-collection entry point | Placeholder for a future action-triggered bridge; it does not replace the current fixed-rate collector. |

These entries remain packaged so historical datasets and deployment scripts do
not break. They should not be selected for the standard Qt capture workflow.

Start simulation-safe replay:

```bash
ros2 launch data_collection_pkg data_collection_replay.launch.py \
  dataset_dir:=/tmp/ur5e_datasets/trainable/teleop/twist_gripper \
  episode_index:=0 \
  rate_hz:=10.0
```

## Runtime Topic Contract

Required:

```text
/joint_states
/teleop/command
/gripper/state
```

For `teleop_ur_ros2`, the bridge publishes data events on:

```text
/teleop/command
```

Those frames are written to:

```text
trainable/teleop/twist_gripper
```

For ACT-style demonstration learning, prefer fixed-rate hardware qpos capture:

```text
original/teleop/qpos_gripper
original/http/qpos_gripper
original/act/qpos_gripper
original/vla/qpos_gripper
```

`original/policy/qpos_gripper` is a historical compatibility directory only.

This mode requires:

```text
/joint_states
/gripper/state
```

and samples at `sample_rate_hz`. Cleaned and filtered data should be exported
later under the matching `trainable/<runtime_mode>/qpos_gripper` directory.

Recommended:

```text
/camera2/scene_camera/color/image_raw/compressed
/camera1/wrist_camera/color/image_raw/compressed
/safety/state
/tool0/pose
```

The default camera transport is `sensor_msgs/msg/CompressedImage`. The
collector stores JPEG payloads directly under the episode image tree as `.jpg`
files. If a deployment publishes raw `sensor_msgs/msg/Image` instead, override
both camera topics and message types explicitly in the launch configuration.

If a real deployment uses different topic names or message types, remap topics
or pass collector parameters at runtime. Keep the package code unchanged unless
the canonical data schema itself changes.

## Validation

For full real-machine integration, follow:

```text
docs/REAL_ROBOT_VALIDATION.md
docs/ros2_manual_verification.md
```

For local Python checks without ROS2:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest test -q
python -m compileall -q data_collection_pkg
```

The ROS2 node tests keep ROS imports at node startup boundaries, so most core
logic remains reusable and testable on normal Python.
