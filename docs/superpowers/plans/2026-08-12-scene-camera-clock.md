# Scene Camera Clock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in scene-camera-header sampling clock for qpos capture so observation synchronization is independent of camera transport latency.

**Architecture:** Retain the existing timer-driven fixed-rate collector as the default. In camera-clock mode, queue scene-camera header timestamps, wait a bounded settling interval for peer data to reach the synchronizer buffer, deterministically select timestamps at `sample_rate_hz`, and use the existing delayed observation/action pairing. Camera header-to-receipt delay is surfaced through quality status only and never causes a frame rejection.

**Tech Stack:** ROS 2 Humble, Python, pytest, existing JSONL capture pipeline.

## Global Constraints

- Preserve `sampling_clock:=timer` and the 15 Hz default.
- Scene camera, wrist camera, and joint state use header timestamps in camera-clock mode.
- Apply independent tolerances: wrist camera `0.02 s`, joint state `0.02 s`, gripper `0.03 s`.
- Do not change JSONL, cleaner, replay, or LeRobot output schemas.
- The `Int8` gripper remains receive-time stamped until an external stamped gripper topic exists.

---

### Task 1: Camera-anchor scheduling engine

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/ros_capture/qpos_demo_collector.py`
- Test: `data_collection_pkg/test/test_qpos_demo_collector.py`

**Interfaces:**
- Produces `FixedRateQposDemoEngine.capture_camera_anchor(timestamp, now)` and `flush_camera_anchors(now)`.
- Uses existing `capture_at(timestamp)` to preserve delayed next-state actions.

- [ ] Write failing tests for delayed anchor settlement, deterministic rate limiting, and camera-specific tolerances.
- [ ] Run the focused pytest selection and confirm each new assertion fails because the camera-clock API is absent.
- [ ] Add a bounded pending-anchor queue and process anchors only after `camera_settle_delay_s` has elapsed.
- [ ] Run the focused pytest selection and confirm it passes.

### Task 2: ROS adapter and health status

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/ros_capture/collector_node.py`
- Test: `data_collection_pkg/test/test_data_collection_ros_nodes.py`

**Interfaces:**
- Consumes parameters `sampling_clock`, `scene_camera_settle_delay_s`, `camera_sync_tolerance_s`, and `gripper_sync_tolerance_s`.
- Produces camera-clock invocation from scene camera callbacks and quality-status fields for latest camera receive delay and threshold breach.

- [ ] Write failing adapter/configuration tests for legacy timer compatibility and scene-camera routing.
- [ ] Run the focused pytest selection and confirm the new assertions fail.
- [ ] Wire configuration, scene callback anchor submission, timer-based pending-anchor flush, and non-rejecting health status.
- [ ] Run the focused pytest selection and confirm it passes.

### Task 3: Launch/UI propagation and regression coverage

**Files:**
- Modify: `data_collection_pkg/launch/data_collection_hardware_qpos.launch.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/test/test_capture_manager.py`
- Modify: `data_collection_pkg/test/test_data_collection_launch_files.py`

**Interfaces:**
- Hardware launch exposes the new parameters.
- CaptureManager forwards payload overrides while preserving timer defaults.

- [ ] Write failing launch and command-contract tests for the parameters and defaults.
- [ ] Run the focused pytest selection and confirm the tests fail.
- [ ] Add launch declarations/forwarding and command arguments.
- [ ] Run the complete Python suite and build `data_collection_pkg` and `data_collection_rviz_panel`.
