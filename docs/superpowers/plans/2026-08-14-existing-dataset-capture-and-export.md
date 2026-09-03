# Existing Dataset Capture And Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume original dataset capture safely and export any selected cleaned dataset as ACT or VLA.

**Architecture:** CaptureManager owns validation and active-target state for a selected original qpos dataset; the dashboard exposes it as an explicit API. The Qt panel uses that state to update the Capture controls and adds a standalone directory/profile export entry point that delegates to the existing LeRobot export workflow.

**Tech Stack:** Python 3, Flask dashboard, Qt Widgets/C++17, pytest, ROS 2 colcon.

## Global Constraints

- Resume accepts only `original/<teleop|http|act|vla>/qpos_gripper` with episode metadata.
- Resume must append with a next episode index and must reject runtime-mode mismatches.
- New Task clears the selected existing dataset.
- Standalone conversion accepts only `cleaned/<mode>/qpos_gripper`; it never cleans automatically.
- Reuse the existing ACT/VLA export API, output collision checks, VLA preflight, and activity indicator.

### Task 1: CaptureManager selected-dataset contract

**Files:**
- Modify: `data_collection_pkg/test/test_capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`

- [ ] Write tests for selecting a valid existing original dataset, preserving its next episode index, rejecting a mode mismatch, and clearing selection with `new_task`.
- [ ] Run the focused tests and observe failure because no selection API exists.
- [ ] Add `select_existing_dataset(payload)` plus status fields for the selected dataset, derived mode, task, and annotation metadata.
- [ ] Require selected-mode equality in `start`; retain the existing writer append behavior.
- [ ] Run the focused tests green.

### Task 2: Dashboard transport

**Files:**
- Modify: `data_collection_pkg/test/test_data_collection_web_dashboard.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py`

- [ ] Add a failing route test for `POST /api/capture/select-existing-dataset`.
- [ ] Add the route and retain existing 200/409 response conventions.
- [ ] Run the focused dashboard test green.

### Task 3: Qt continuation and standalone conversion

**Files:**
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`

- [ ] Add failing source-contract assertions for `Continue Dataset...`, `Convert LeRobot...`, the selected-dataset API, cleaned-directory selection, and profile choice.
- [ ] Add the two buttons and asynchronous directory dialogs.
- [ ] Apply selected capture status to mode/task/language UI and disable a mode mismatch while resuming.
- [ ] Reuse `request_lerobot_export` after ACT/VLA selection; reject structurally invalid directories before export.
- [ ] Run the panel contract test green and build `data_collection_rviz_panel`.

### Task 4: Verification

**Files:**
- Modify: `data_collection_rviz_panel/docs/REAL_ROBOT_TEST_GUIDE.md`

- [ ] Document continuation and standalone export workflows, including required original/cleaned directory forms and re-cleaning after append.
- [ ] Run the full data collection pytest suite, Qt panel pytest suite, Qt build, and `git diff --check`.
