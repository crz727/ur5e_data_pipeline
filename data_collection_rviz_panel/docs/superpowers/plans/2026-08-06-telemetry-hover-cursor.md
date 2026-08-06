# Telemetry Hover Cursor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add relative-time axes and a hover cursor that reports all joint values in each telemetry chart.

**Architecture:** Keep `TelemetryChart` as a custom Qt widget. Store timestamped samples, map mouse x-coordinates to the nearest sample, and render the cursor, axis labels, and value overlay in `paintEvent`. MainWindow passes ROS/replay timestamps and clears charts at replay boundaries.

**Tech Stack:** C++17, Qt5 Widgets/QPainter, ROS 2 Humble, ament_cmake pytest contract tests.

## Global Constraints

- Change only `data_collection_rviz_panel`.
- Preserve existing live telemetry, replay, RViz, camera, and control behavior.
- Use relative episode time for replay and nearest-recorded-sample values.
- Run pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

---

### Task 1: Specify the telemetry cursor contract

**Files:**
- Modify: `test/test_panel_contract.py`

**Interfaces:**
- Consumes: `TelemetryChart::append(double timestamp, const std::vector<double> & values)`
- Produces: a source-level regression contract for timeline, pointer events, and replay clearing.

- [x] **Step 1: Write the failing test**

```python
assert `void append(double timestamp, const std::vector<double> & values)` in main_window
assert `void mouseMoveEvent(QMouseEvent * event) override` in main_window
assert `void leaveEvent(QEvent *) override` in main_window
assert `painter.drawText(axis_rect, Qt::AlignCenter, QStringLiteral("time (s)"))` in main_window
assert `qpos_chart_->clear()` in main_window
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: FAIL because timestamped append and hover cursor hooks do not exist.

- [x] **Step 3: Implement the feature in Task 2**

- [x] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: PASS.

### Task 2: Render timestamped hover inspection

**Files:**
- Modify: `src/main_window.cpp:107-218`

**Interfaces:**
- Consumes: timestamped telemetry samples and mouse coordinates.
- Produces: `TelemetryChart::append(double, const std::vector<double> &)`, `TelemetryChart::clear()`, time-axis and cursor/overlay rendering.

- [x] **Step 1: Implement stored timestamped samples**

```cpp
struct Sample {
  double timestamp;
  QVector<double> values;
};
void append(double timestamp, const std::vector<double> & values);
void clear();
```

- [x] **Step 2: Implement pointer selection**

```cpp
void mouseMoveEvent(QMouseEvent * event) override;
void leaveEvent(QEvent *) override;
int nearest_sample_index(double timestamp) const;
```

Map the pointer x-position to the plot's first/last retained timestamp,
clamp it to the plot, and retain the closest sample index.

- [x] **Step 3: Render the time axis, cursor, and value overlay**

```cpp
painter.drawLine(cursor_x, plot.top(), cursor_x, plot.bottom());
painter.drawText(axis_rect, Qt::AlignCenter, QStringLiteral("time (s)"));
```

Draw elapsed seconds relative to the first retained sample. Include curve
names, units, and values in the overlay using each legend color.

- [x] **Step 4: Run the contract test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: PASS.

### Task 3: Supply timestamps and reset replay charts

**Files:**
- Modify: `src/main_window.cpp:543-557, 1012-1034`

**Interfaces:**
- Consumes: ROS JointState header timestamps and dashboard replay timestamps.
- Produces: synchronized timestamped telemetry input and clean episode boundaries.

- [x] **Step 1: Pass live ROS timestamps**

```cpp
const double timestamp = static_cast<double>(message->header.stamp.sec) +
  static_cast<double>(message->header.stamp.nanosec) * 1e-9;
qpos_chart_->append(timestamp, position);
```

Fallback to the node clock when the ROS header stamp is zero.

- [x] **Step 2: Reset and append replay samples**

```cpp
qpos_chart_->clear();
qvel_chart_->clear();
effort_chart_->clear();
qpos_chart_->append(timestamp, qpos);
```

Perform the reset when replay begins or its episode index changes.

- [x] **Step 3: Build and test**

Run: `cd /home/crz/src && colcon build --packages-select data_collection_rviz_panel --symlink-install && colcon test --packages-select data_collection_rviz_panel && colcon test-result --verbose`

Expected: build succeeds and the package has no failed tests.
