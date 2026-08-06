# Compressed Camera Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dashboard and dataset collection consume ROS `CompressedImage` camera streams and preserve JPEG payloads without a second encoding pass.

**Architecture:** The collector defaults use the two real-camera `/image_raw/compressed` topics and `sensor_msgs.msg:CompressedImage`. `camera_sample` labels compressed payloads explicitly, and `JsonlDatasetWriter` writes JPEG payloads directly to the dataset image tree. The dashboard node subscribes to the same configurable compressed topics.

**Tech Stack:** ROS 2 `sensor_msgs/msg/CompressedImage`, Python standard library, Flask, existing JSONL writer, pytest.

## Global Constraints

- Modify only `/home/crz/src/data_collection_pkg`.
- Do not modify camera drivers or robot-control packages.
- Default camera topics are `/camera2/scene_camera/color/image_raw/compressed` and `/camera1/wrist_camera/color/image_raw/compressed`.
- Preserve parameter overrides for non-default deployments.
- Preserve the existing raw-image storage behavior for explicitly configured raw streams.
- Compressed JPEG bytes must be stored as `.jpg` with `codec: "jpeg"` without re-encoding.

---

### Task 1: Preserve compressed camera payload semantics

**Files:**
- Modify: `data_collection_pkg/ros_capture/message_adapters.py`
- Modify: `data_collection_pkg/dataset/jsonl_writer.py`
- Test: `test/test_data_collection_message_adapters.py`
- Test: `test/test_data_collection_writer.py`

- [ ] Write failing tests for `CompressedImage`-like messages producing `transport: "compressed"`, `codec: "jpeg"`, and JPEG bytes being stored unchanged in a `.jpg` dataset file.
- [ ] Run the two targeted tests and confirm they fail because compressed transport metadata and direct JPEG handling do not exist.
- [ ] Add a camera payload classifier for ROS `format` values such as `jpeg`, `jpg`, and `rgb8; jpeg compressed`.
- [ ] Update `JsonlDatasetWriter` to retain known compressed JPEG byte streams directly and preserve raw-image encoding behavior for all other payloads.
- [ ] Run targeted adapter/writer tests and the complete writer test module.

### Task 2: Make real-camera collection default to compressed topics

**Files:**
- Modify: `data_collection_pkg/ros_capture/teleop_recorder.py`
- Modify: `data_collection_pkg/ros_capture/collector_node.py`
- Modify: `launch/data_collection_hardware_qpos.launch.py`
- Modify: `launch/data_collection_teleop_demo_qpos.launch.py`
- Modify: `launch/data_collection_teleop_ur_ros2.launch.py`
- Modify: `data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/hardware_check/hardware_interface_check_node.py`
- Test: `test/test_data_collection_ros_nodes.py`
- Test: `test/test_data_collection_launch_files.py`

- [ ] Write failing assertions for compressed default topics and `sensor_msgs.msg:CompressedImage` subscription type names.
- [ ] Run the targeted tests and confirm the old raw defaults fail the new assertions.
- [ ] Change collection defaults and launch defaults to the real-camera compressed topic contract while leaving all topic parameters overrideable.
- [ ] Update dashboard-initiated collector command defaults to pass the compressed topics.
- [ ] Run targeted ROS-node and launch tests.

### Task 3: Make the dashboard consume the same compressed streams

**Files:**
- Modify: `data_collection_pkg/visualization/web_dashboard_node.py`
- Modify: `data_collection_pkg/visualization/topology_monitor_node.py`
- Modify: `data_collection_pkg/visualization/web_dashboard.py`
- Modify: `launch/data_collection_monitor.launch.py`
- Test: `test/test_data_collection_web_dashboard.py`
- Test: `test/test_data_collection_topology.py`

- [ ] Write failing tests covering compressed camera topic defaults in dashboard/topology configuration.
- [ ] Run the targeted tests and confirm the old raw paths fail.
- [ ] Add configurable dashboard camera topic/type parameters and subscribe with `CompressedImage`; keep the existing JSON status subscriptions intact.
- [ ] Update topology and browser key-topic defaults to the compressed paths.
- [ ] Run dashboard and topology tests.

### Task 4: Validate the package boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/ros2_manual_verification.md`
- Modify: `docs/REAL_ROBOT_VALIDATION.md`

- [ ] Update documented camera topic contracts to the compressed paths and `sensor_msgs/msg/CompressedImage`.
- [ ] Run `pytest test -q` and `python3 -m compileall -q data_collection_pkg`.
- [ ] Report any ROS-runtime verification that cannot run without a sourced ROS 2 workspace and live camera publishers.
