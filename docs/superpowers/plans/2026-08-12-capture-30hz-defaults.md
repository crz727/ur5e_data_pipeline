# 30 Hz Capture Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hardware capture, cleaning, and LeRobot export consistently default to the 30 Hz scene-camera-clock data contract.

**Architecture:** The collector uses separate canonical camera, joint-state, and gripper tolerances. Hardware launch and CaptureManager default capture to 30 Hz and the scene-camera header clock. CaptureManager converts clean request fields into `CleaningConfig`, while Qt sends explicit 30 Hz defaults for capture, cleaning, and export.

**Tech Stack:** ROS 2 Humble, Python, pytest, C++17, Qt.

## Global Constraints

- Default capture: 30 Hz, `scene_camera_header`, camera/joint `0.02 s`, gripper `0.03 s`.
- `state_max_sync_delta_s` remains a legacy joint-state fallback only.
- Cleaning defaults to 30 Hz and image timestamp tolerance `0.02 s`.
- LeRobot export defaults to 30 FPS.
- Replay rate remains independent.

---

### Task 1: Separate Capture Tolerances And Defaults

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/ros_capture/collector_node.py`
- Modify: `data_collection_pkg/launch/data_collection_hardware_qpos.launch.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Test: `data_collection_pkg/test/test_data_collection_ros_nodes.py`
- Test: `data_collection_pkg/test/test_data_collection_launch_files.py`
- Test: `data_collection_pkg/test/test_capture_manager.py`

**Interfaces:**
- Produces `joint_state_sync_tolerance_s` as the canonical capture parameter.
- Retains `state_max_sync_delta_s` as a fallback when the canonical parameter is absent.

- [ ] Write failing tests that assert 30 Hz defaults, canonical joint-tolerance precedence, and legacy fallback behavior.
- [ ] Run the focused tests and confirm they fail under the existing 15 Hz/combined-state defaults.
- [ ] Add the canonical parameter and wire the 30 Hz defaults through hardware launch and CaptureManager.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Clean And Export Request Propagation

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/dataset/cleaner.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/dataset/converter.py`
- Modify: `data_collection_pkg/data_collection_pkg/dataset/lerobot_writer.py`
- Modify: `data_collection_pkg/data_collection_pkg/cli.py`
- Test: `data_collection_pkg/test/test_data_collection_cleaner.py`
- Test: `data_collection_pkg/test/test_capture_manager.py`
- Test: `data_collection_pkg/test/test_data_collection_converter.py`
- Test: `data_collection_pkg/test/test_data_collection_cli.py`

**Interfaces:**
- `CaptureManager.clean(payload)` accepts `target_fps`, `max_sync_delta_s`, and `fps_tolerance_ratio`.
- `CaptureManager.export_lerobot(payload)` defaults `fps` to `30.0`.

- [ ] Write failing tests for the 30 Hz defaults and clean/export override propagation.
- [ ] Run focused tests and confirm they fail.
- [ ] Construct `CleaningConfig` from supported request values and change conversion defaults to 30 FPS.
- [ ] Run focused tests and confirm they pass.

### Task 3: Qt Request Defaults

**Files:**
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Test: `data_collection_rviz_panel/test/test_main_window_contract.py`

**Interfaces:**
- Capture start JSON sends the 30 Hz capture contract.
- Clean JSON sends 30 Hz image-quality defaults.
- Export JSON sends `fps: 30.0`.

- [ ] Write failing source-contract tests for all three JSON request payloads.
- [ ] Run the focused test and confirm it fails.
- [ ] Add the explicit values to Qt request payloads.
- [ ] Run the focused test and confirm it passes.

### Task 4: Integrated Verification

**Files:**
- Modify: `docs/PROJECT_HANDOFF.md`

- [ ] Update the persisted baseline with the 30 Hz capture/clean/export defaults.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test ../data_collection_rviz_panel/test` from `data_collection_pkg`.
- [ ] Run `source /opt/ros/humble/setup.bash && colcon build --packages-select data_collection_pkg data_collection_rviz_panel` from the workspace root.
- [ ] Commit only files introduced or modified by this plan.
