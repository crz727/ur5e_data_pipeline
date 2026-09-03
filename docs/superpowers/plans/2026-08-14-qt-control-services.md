# Qt Control Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Qt panel safely start and stop only its owned HTTP API and Mode Manager processes.

**Architecture:** Add a Qt-local control-services state machine that starts two detached `QProcess` commands, records their PIDs, and polls the existing HTTP API plus ROS mode status. It starts HTTP API before Mode Manager and requires a confirmed IDLE/no-owner result before stopping owned services.

**Tech Stack:** Qt Widgets and Network, Qt `QProcess`, C++17, ROS 2 rclcpp, pytest source-contract tests, colcon.

## Global Constraints

- Manage only `ur5e_http_api run_api` and `ur5e_mode_manager mode_manager` created by this Qt instance.
- Never launch, stop, or signal the UR driver, controller manager, cameras, gripper, dashboard backend, or policy processes.
- Do not stop externally managed API or Mode Manager processes.
- Stop requires observed `state=IDLE` and `owner=none`; a timeout leaves processes running.
- Closing the Qt window must not stop control services.

### Task 1: Contract coverage for the control-services lifecycle

**Files:**
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- Consumes: Qt panel source and header files.
- Produces: source-contract assertions for `start_control_services`, `stop_control_services`, ownership fields, and idle confirmation.

- [x] **Step 1: Write failing lifecycle assertions**

Add a test that requires `QProcess` ownership fields, a single stateful
`control_services_button_`, a `Start control services` label, a `Stop control
services` label, HTTP health polling before manager launch, an idle request
before stop, and no UR-driver launch command in `main_window.cpp`.

- [x] **Step 2: Run the focused test and confirm failure**

```bash
cd /home/crz/src
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q data_collection_rviz_panel/test/test_panel_contract.py
```

Expected: FAIL because the lifecycle interface does not exist.

- [x] **Step 3: Keep the test focused on observable contracts**

Do not assert private layout positions, exact timeout literals, or unrelated
Capture/Replay source text. The test must only constrain the required
ownership and transition behavior.

### Task 2: Implement the Qt-local lifecycle state machine

**Files:**
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`

**Interfaces:**
- Consumes: `MainWindow::request_mode`, `/control_mode/status`, and existing `QNetworkAccessManager`.
- Produces: `start_control_services()`, `stop_control_services()`, and
  `update_control_services_button()` methods plus owned API/manager
  `QProcess` fields.

- [x] **Step 1: Add owned process and lifecycle state fields**

Declare API and Mode Manager PIDs created by `QProcess::startDetached`, a lifecycle enum
covering stopped, starting API, starting manager, running, and stopping, a
single timer, and a button/status label. Store an explicit `services_owned_`
flag; do not infer ownership from ROS topic existence.

- [x] **Step 2: Add the Mode Manager UI controls**

Create one button in the existing Mode Manager group. It displays `Start
control services` while stopped and `Stop control services` while running;
disable it during a transition. Add a concise status label for health-check,
external-management, and timeout errors.

- [x] **Step 3: Implement ordered start**

On start, refuse if mode status or API health shows external management.
Otherwise start `ros2 run ur5e_http_api run_api` using the inherited Qt/ROS
environment. Poll `GET http://127.0.0.1:5000/api/health`; only after success
start `ros2 run ur5e_mode_manager mode_manager`. Mark the stack running only
after valid `/control_mode/status` arrives. If either process exits or the
deadline expires, terminate only the processes started by this attempt.

- [x] **Step 4: Implement ordered stop**

On stop, publish `idle` through `request_mode`. Require a later status message
with `state == IDLE` and `owner == none`. Then terminate the owned manager,
wait for it to exit, and terminate the owned API. If status does not arrive
before the deadline, leave both processes running and show a timeout status.

- [x] **Step 5: Preserve external and window behavior**

When API or manager are detected but no owned process exists, show
`Externally managed; stop unavailable` and leave the button non-destructive.
Do not add process cleanup to the Qt window destructor or close event.

### Task 3: Verify and document real-robot operation

**Files:**
- Modify: `data_collection_rviz_panel/docs/REAL_ROBOT_TEST_GUIDE.md`
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- Consumes: control-services lifecycle methods from Task 2.
- Produces: operator steps for Qt-owned and externally managed services.

- [x] **Step 1: Extend the source-contract test for final behavior**

Require `QProcess`, the owned-only stop guard, `request_mode("idle")`, and
the `IDLE`/`none` status predicate. Assert no strings that launch UR driver,
camera, gripper, ros2_control, or policy executables appear in the new
lifecycle command definitions.

- [x] **Step 2: Run focused tests**

```bash
cd /home/crz/src
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q data_collection_rviz_panel/test/test_panel_contract.py
```

Expected: PASS.

- [x] **Step 3: Build the Qt package**

```bash
cd /home/crz
source /opt/ros/humble/setup.bash
source /home/crz/src/install/setup.bash
colcon build --base-paths /home/crz/src --packages-select data_collection_rviz_panel
```

Expected: `data_collection_rviz_panel` builds successfully.

- [x] **Step 4: Add the operator runbook**

Document that the button manages only API and Mode Manager, requires a
healthy API before the manager starts, returns to IDLE before stop, does not
stop externally started services, and supports the `AUTO -> IDLE -> TELEOP`
HIL handoff after status confirmation.

- [x] **Step 5: Final checks**

Run `git diff --check` and inspect `git status --short`. Do not stage or
modify unrelated dirty files.
