# Static Trimming and 15 Hz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect qpos demonstrations at 15 Hz and create cleaned datasets with only leading and trailing long-static frames removed.

**Architecture:** Original datasets remain immutable. The cleaner evaluates technical quality on the full source episode, then derives one contiguous retained frame range from actual joint and gripper state changes, writes that range and its referenced images to `cleaned`, and records the decision in the manifest and report. The Qt cleaning completion dialog stays open until the user explicitly closes it.

**Tech Stack:** Python 3.10, ROS 2 Humble, Flask, Qt5/C++, pytest, colcon.

## Global Constraints

- Fixed-rate qpos capture defaults to 15 Hz; LeRobot export defaults to 15 Hz.
- Original data is never changed by static trimming.
- Do not remove frames from the middle of an episode.
- Detect activity from actual qpos and gripper measurements over an eight-frame window.
- Retain eight frames of context on both sides of the active range.
- Mark an accepted human-success episode with no detected state motion as `needs_review:no_state_motion`.

---

### Task 1: Add Static Range Detection to the Cleaner

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/dataset/cleaner.py`
- Modify: `data_collection_pkg/test/test_data_collection_cleaner.py`

**Interfaces:**
- `CleaningConfig(target_fps=15.0, motion_window_frames=8, joint_motion_threshold_rad=0.01, gripper_motion_threshold=0.02, context_frames=8)`.
- `_retained_frame_range(frames, config) -> tuple[int, int] | None` returns a half-open contiguous range or `None`.

- [ ] Write tests for leading/trailing trimming, preserved middle dwell frames, and no-motion review status.
- [ ] Run the new tests and confirm they fail before the range detector exists.
- [ ] Implement the range detector and have accepted cleaned episodes write only the retained frame range with updated metadata and image references.
- [ ] Run `PYTHONPATH=. python3 -m pytest -q test/test_data_collection_cleaner.py`.

### Task 2: Apply the 15 Hz Contract

**Files:**
- Modify: `data_collection_pkg/launch/data_collection_hardware_qpos.launch.py`
- Modify: `data_collection_pkg/launch/data_collection_teleop_demo_qpos.launch.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/dataset/converter.py`
- Modify: `data_collection_pkg/data_collection_pkg/cli.py`
- Modify: `data_collection_pkg/test/test_capture_manager.py`

**Interfaces:**
- Hardware and demo qpos launch defaults use `sample_rate_hz=15.0`.
- Cleaner target FPS is 15.0; image/state synchronization tolerance is at most 0.07 s.
- UI and CLI LeRobot export uses FPS 15.0 unless explicitly overridden.

- [ ] Write tests asserting the default launch command and cleaner configuration use the 15 Hz contract.
- [ ] Run those tests and confirm they fail with the current 10 Hz defaults.
- [ ] Implement only the default-value changes and update user-facing validation guidance.
- [ ] Run focused capture, cleaner, CLI, and launch tests.

### Task 3: Make the Cleaning Result Dialog Persistent

**Files:**
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- A non-modal `QDialog` owns `Open Report`, `Export LeRobot`, and `Close` buttons.
- Only `Close` or the title-bar close control closes the dialog.

- [ ] Write the panel contract test for a non-modal dialog and explicit close action.
- [ ] Run the test and confirm it fails against `QMessageBox::exec()`.
- [ ] Implement the persistent dialog and keep export asynchronous.
- [ ] Build `data_collection_rviz_panel` and run its contract test.

### Task 4: Verify End-to-End Behavior

**Files:**
- Modify: `data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md`

- [ ] Document 15 Hz capture, static-trim report fields, and the fact that original data remains unchanged.
- [ ] Run `colcon build --packages-select data_collection_pkg data_collection_rviz_panel`.
- [ ] Run `colcon test --packages-select data_collection_pkg data_collection_rviz_panel` and inspect `colcon test-result --verbose`.
