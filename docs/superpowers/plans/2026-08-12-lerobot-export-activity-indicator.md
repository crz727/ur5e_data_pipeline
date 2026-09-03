# LeRobot Export Activity Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an indeterminate Qt progress bar while a LeRobot export is queued or running.

**Architecture:** Reuse the existing asynchronous export endpoint and 500 ms status polling. A Qt-only helper owns the busy bar's range, visibility, and reset behavior; it is activated only after an export request is sent and reset on request failure, `done`, or `failed` status.

**Tech Stack:** Qt Widgets, C++17, pytest source-contract tests, ROS 2 colcon.

## Global Constraints

- Do not change `converter.py`, CaptureManager, dashboard API, LeRobot files, or video encoding.
- The indicator is indeterminate: active range is exactly `0, 0`; no percentage is displayed.
- Existing status text remains the user-visible state description.

### Task 1: Qt export activity indicator

**Files:**
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`

**Interfaces:**
- `MainWindow::set_lerobot_export_activity(bool active)` updates the Qt-only progress bar.
- `lerobot_export_progress_` is a `QProgressBar *` that is hidden and reset when inactive.

- [ ] **Step 1: Write failing source-contract assertions**

Assert that the panel declares a `QProgressBar`, creates it in the Capture
section, uses `setRange(0, 0)` while active, and calls the activity helper
from export start, request-start failure, `done`, and `failed` branches.

- [ ] **Step 2: Run panel contract test to verify failure**

```bash
cd /home/crz/src
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/home/crz/src python3 -m pytest -q data_collection_rviz_panel/test/test_panel_contract.py
```

Expected: FAIL because no `QProgressBar` or activity helper exists.

- [ ] **Step 3: Implement the minimal UI-only indicator**

Add the progress-bar forward declaration, field, include, Capture layout row,
and `set_lerobot_export_activity`. Call it with `true` at export request
submission and `false` for request failure, terminal `done`, and terminal
`failed` states. Keep status polling and state text unchanged.

- [ ] **Step 4: Run panel contract test to verify green**

Run the same focused pytest command and require all panel contract tests to
pass.

- [ ] **Step 5: Build and verify**

```bash
cd /home/crz
source /opt/ros/humble/setup.bash
source /home/crz/src/install/setup.bash
colcon build --base-paths /home/crz/src --packages-select data_collection_rviz_panel
```

Run `git diff --check`, inspect `git status --short`, and commit only the
three panel files and this plan document.
