# Seek Redraw and Bottom Operation Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve telemetry curves after seek and reserve the lower-right UI for operation controls.

**Architecture:** TelemetryChart receives dashboard telemetry history and replaces its timestamped samples on seek jumps. MainWindow separates charts from operations, creates a lower horizontal splitter for diagnostic tabs and an operation scroll area, and uses a custom capture-outcome dialog.

**Tech Stack:** C++17, Qt5 Widgets/QPainter, ROS 2 Humble, ament_cmake pytest contract tests.

## Global Constraints

- Change only `data_collection_rviz_panel`.
- Preserve safe replay-only model publication and existing Capture/Replay APIs.
- The capture dialog order is Success, Failure, Cancel from left to right.
- Run pytest with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest`.

---

### Task 1: Specify seek redraw and layout contracts

**Files:**
- Modify: `test/test_panel_contract.py`

**Interfaces:**
- Produces: source-level regressions for `replace_history`, bottom splitter,
  operation scroll, and fixed dialog order.

- [ ] **Step 1: Write failing assertions**

```python
assert "replace_history" in main_window
assert "bottom_splitter" in main_window
assert "operation_scroll" in main_window
assert "dialog_buttons->addWidget(success)" in main_window
assert "dialog_buttons->addWidget(failure)" in main_window
assert "dialog_buttons->addWidget(cancel)" in main_window
```

- [ ] **Step 2: Run test and observe failure**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: FAIL because seeking clears charts and the current layout/dialog use
the old widgets.

### Task 2: Preserve curves on replay seek

**Files:**
- Modify: `src/main_window.cpp:109-390, 1389-1440`

**Interfaces:**
- Produces: `TelemetryChart::replace_history(const QJsonArray &, const QString &)`.

- [ ] **Step 1: Implement history replacement**

```cpp
void replace_history(const QJsonArray & history, const QString & field);
```

Extract timestamp/value samples for one telemetry field, sort by timestamp,
retain at most 300 samples, and clear hover selection.

- [ ] **Step 2: Use history on seek jump**

```cpp
qpos_chart_->replace_history(history, QStringLiteral("qpos"));
```

Use the telemetry history for qpos/qvel/effort rather than clearing the
charts. Continue to update the selected replay pose and camera state.

- [ ] **Step 3: Run panel contract**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q test/test_panel_contract.py`

Expected: PASS.

### Task 3: Move controls to lower-right and fix dialog order

**Files:**
- Modify: `src/main_window.cpp:530-795, 953-992`

**Interfaces:**
- Produces: `bottom_splitter` with diagnostic tabs on the left and
  `operation_scroll` on the right; custom ordered outcome dialog.

- [ ] **Step 1: Separate telemetry from operation controls**

```cpp
auto * bottom_splitter = new QSplitter(Qt::Horizontal, workspace);
auto * operation_scroll = new QScrollArea(bottom_splitter);
```

Keep qpos/qvel/effort in the upper right. Move Mode, Capture, and Replay
groups into `operation_scroll` in the lower right. Put the existing JSON
tabs into the lower-left splitter pane.

- [ ] **Step 2: Implement deterministic result dialog**

```cpp
auto * dialog_buttons = new QHBoxLayout;
dialog_buttons->addWidget(success);
dialog_buttons->addWidget(failure);
dialog_buttons->addWidget(cancel);
```

Use QDialog with custom buttons, connect each to accept/reject, and map the
clicked action to success/failure/unreviewed annotation behavior.

- [ ] **Step 3: Build and test**

Run: `cd /home/crz/src && colcon build --packages-select data_collection_rviz_panel --symlink-install && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q data_collection_rviz_panel/test/test_panel_contract.py`

Expected: build succeeds and contract test passes.
