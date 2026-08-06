# Telemetry Scale, Seek Timeline, and Health Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator comparable telemetry values, exact replay seek, and persistent health feedback.

**Architecture:** The Python dashboard replay controller owns frame selection and exposes a read-only seek endpoint. The Qt panel renders the shared-scale telemetry charts and derives its time slider and four health chips from the dashboard state. No component publishes robot commands.

**Tech Stack:** Python 3.10, Flask, C++17, Qt5 Widgets/QPainter, ROS 2 Humble, pytest, ament_cmake.

## Global Constraints

- Change only `data_collection_pkg` dashboard replay code and `data_collection_rviz_panel`.
- Do not change the collector, camera drivers, robot driver, or robot control topics.
- Seek operates solely on dashboard telemetry, image cache, and safe replay model state.
- Run pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest`.

---

### Task 1: Add safe replay seek to the dashboard controller

**Files:**
- Modify: `data_collection_pkg/visualization/replay_controller.py:24-157`
- Modify: `data_collection_pkg/visualization/web_dashboard.py:220-249`
- Modify: `test/test_dashboard_replay_controller.py`
- Modify: `test/test_data_collection_web_dashboard.py`

**Interfaces:**
- Produces: `DashboardReplayController.seek(frame_index: int) -> dict`.
- Produces: `POST /api/replay/seek` body `{"frame_index": int}`.
- Extends status with `frame_index` and `timestamp`.

- [x] **Step 1: Write failing seek tests**

```python
result = controller.seek(99)
assert result["ok"] is True
assert result["frame_index"] == 2
assert store.snapshot()["telemetry"]["latest"]["qpos"] == [0.2] * 6
```

Start a gated three-frame replay, pause it after frame zero, seek beyond the
last frame, and assert clamping plus immediate telemetry update. Add an API
test that `POST /api/replay/seek` exists and rejects an idle replay.

- [x] **Step 2: Run the new tests and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_dashboard_replay_controller.py test/test_data_collection_web_dashboard.py`

Expected: FAIL because `seek` and its endpoint do not exist.

- [x] **Step 3: Implement controller state and endpoint**

```python
def seek(self, frame_index: int) -> dict:
    # Require running or paused status, clamp index, apply selected observation
    # while holding the replay lock, then set the worker's next index.
```

Persist the loaded replay and dataset directory on `start`. The worker reads
its next index under the same lock. Update `frame_index`, `published_frames`
(one-based progress), and `timestamp` after every applied observation.
Return HTTP 409 for an invalid controller state and HTTP 400 for a noninteger
frame index.

- [x] **Step 4: Run controller and dashboard tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_dashboard_replay_controller.py test/test_data_collection_web_dashboard.py`

Expected: PASS.

### Task 2: Render numeric shared telemetry scales

**Files:**
- Modify: `src/main_window.cpp:109-390`
- Modify: `test/test_panel_contract.py`

**Interfaces:**
- Produces: a `TelemetryChart` shared range over all visible curves, numeric
  top/middle/bottom ticks, and chart unit labels.

- [x] **Step 1: Write a failing panel contract**

```python
assert "shared_value_range" in main_window
assert "painter.drawText(y_tick" in main_window
assert 'QStringLiteral("rad/s")' in main_window
```

- [x] **Step 2: Run the contract test and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: FAIL because the chart retains per-joint normalization without
numeric y-ticks.

- [x] **Step 3: Implement one range for all curves**

```cpp
QPair<double, double> shared_value_range(int joint_count) const;
double value_to_y(double value, double minimum, double maximum, const QRect & plot) const;
```

Use a 10% margin, retain the existing title-specific minimum span, and draw
top/middle/bottom tick values to the left of the plot. Reserve a left gutter
so labels do not overlap curves.

- [x] **Step 4: Run the panel contract**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: PASS.

### Task 3: Add seekable timeline and health chips to the Qt panel

**Files:**
- Modify: `include/data_collection_rviz_panel/main_window.hpp`
- Modify: `src/main_window.cpp:390-1260`
- Modify: `test/test_panel_contract.py`

**Interfaces:**
- Consumes: `replay_status.frame_index/frame_count/timestamp`,
  `flow_status.topics`, `cameras`, and `capture_status`.
- Produces: `request_replay_seek(int)`, a `QSlider` timeline, and four
  header health labels.

- [x] **Step 1: Write failing panel contract**

```python
assert "QSlider" in main_window
assert 'QStringLiteral("/api/replay/seek")' in main_window
assert "robot_health_value_" in main_window
assert "scene_camera_health_value_" in main_window
assert "wrist_camera_health_value_" in main_window
assert "writer_health_value_" in main_window
```

- [x] **Step 2: Run the contract test and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: FAIL because the panel has no seek/time status controls or health
labels.

- [x] **Step 3: Implement timeline and replay control state**

```cpp
void request_replay_seek(int frame_index);
QSlider * replay_timeline_{nullptr};
bool replay_timeline_dragging_{false};
```

Update the slider without signals on dashboard refresh. Enable it only while
replay is running or paused. On user release, post the selected frame index.
Show selected time and one-based `frame / total`, and enable Pause, Resume,
and Stop only in their valid replay states.

- [x] **Step 4: Implement health chips**

```cpp
void set_health_chip(QLabel * label, const QString & name, bool healthy,
                     bool stale, const QString & detail);
```

Build Robot/Scene/Wrist/Writer labels in the header. Read robot heartbeat from
`flow_status.topics["/joint_states"]`, camera validity/age from `cameras`,
and writer state from `capture_status`.

- [x] **Step 5: Run panel contract and build**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py && cd /home/crz/src && colcon build --packages-select data_collection_pkg data_collection_rviz_panel --symlink-install`

Expected: contract PASS and both packages compile.

### Task 4: Full verification

**Files:**
- Modify: `docs/REAL_ROBOT_TEST_GUIDE.md`

**Interfaces:**
- Consumes: the implemented replay timeline and header health behavior.
- Produces: real-robot verification steps for seek and health checks.

- [x] **Step 1: Add guide checks**

```text
Verify the four header chips before Capture.
Pause replay, drag the timeline, and confirm model/cameras/curves change to
the selected frame without any control-topic publication.
```

- [x] **Step 2: Run all relevant tests**

Run: `cd /home/crz/src && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q data_collection_pkg/test/test_dashboard_replay_controller.py data_collection_pkg/test/test_data_collection_web_dashboard.py data_collection_rviz_panel/test/test_panel_contract.py && colcon test --packages-select data_collection_pkg data_collection_rviz_panel && colcon test-result --verbose`

Expected: all selected pytest cases pass, both packages test successfully, and
the colcon result contains no failures.
