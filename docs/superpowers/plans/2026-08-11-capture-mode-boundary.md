# Capture Mode Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `teleop`, `http`, `act`, and `vla` as capture-only profiles, omit empty annotation launch arguments, and preserve Mode Manager ownership of robot control.

**Architecture:** Keep the existing `runtime_mode` API and metadata field as the capture-profile identifier so existing JSONL, cleaning, replay, and export paths remain compatible. Tighten only the capture allowlist and UI option lists; the hardware qpos launch remains the sole process started by `CaptureManager`. Annotation arguments are appended conditionally after `parse_capture_task_annotation` returns normalized values.

**Tech Stack:** Python 3, pytest, ROS 2 launch files, Qt/C++ RViz panel, embedded Web dashboard HTML.

## Global Constraints

- Capture profiles are storage/metadata classifications, not robot control modes.
- `CaptureManager` starts/stops only `data_collection_hardware_qpos.launch.py`.
- Fixed-rate qpos/gripper collection remains 15 Hz with camera/state synchronization tolerance `0.07 s`.
- New capture requests accept exactly `teleop`, `http`, `act`, and `vla`; historical `policy` directories remain readable.
- VLA language validation remains an export-preflight concern, not a collector-start requirement.
- Do not modify external untracked ROS packages or Mode Manager control transitions.

### Task 1: CaptureManager contract and regression tests

**Files:**
- Modify: `data_collection_pkg/test/test_capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`

**Interfaces:**
- `ALLOWED_RUNTIME_MODES` becomes `("teleop", "http", "act", "vla")`.
- `CaptureManager._command(...)` continues returning a `list[str]`, with optional annotation arguments omitted when their values are empty.

- [ ] **Step 1: Write failing tests**

Add tests that start `CaptureManager` with no annotation and assert none of
`task_id:=`, `language_instruction_en:=`, or `language_instruction_zh:=` is in
the command; start each of `act` and `vla` and assert the dataset path uses the
selected profile; and assert `runtime_mode=policy` is rejected while the
collector command still contains no controller command.

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
cd /home/crz/src/data_collection_pkg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest -q test/test_capture_manager.py
```

Expected: the new profile and empty-argument assertions fail against the
current allowlist/command builder.

- [ ] **Step 3: Implement the minimal manager change**

Change the allowlist and build the base command without annotation arguments.
For each annotation key, append `f"{name}:={value}"` only when
`str(annotation.get(name, "")).strip()` is non-empty. Leave controller and
collector process behavior unchanged.

- [ ] **Step 4: Run focused tests to verify green**

Run the same pytest command and require all capture-manager tests to pass.

- [ ] **Step 5: Commit the isolated Python behavior**

```bash
git add data_collection_pkg/data_collection_pkg/visualization/capture_manager.py data_collection_pkg/test/test_capture_manager.py
git commit -m "fix: classify act and vla captures without empty launch args"
```

### Task 2: Qt and Web capture selectors

**Files:**
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py`
- Modify: `data_collection_rviz_panel/test` or the existing selector contract test file, if present
- Modify: `data_collection_pkg/test/test_data_collection_web_dashboard.py` when selector HTML is asserted there

**Interfaces:**
- Qt `capture_mode_` and Web `#captureMode` expose the same four values in the same order.
- Start requests continue sending `{runtime_mode, task, task_id, language_instruction_en, language_instruction_zh}` from Qt and `{runtime_mode, task}` from the dashboard.

- [ ] **Step 1: Write failing selector-contract tests**

Add source-contract assertions that the Qt source contains
`teleop`, `http`, `act`, and `vla` and no capture selector `policy` item; add a
Web dashboard HTML assertion for the same option set.

- [ ] **Step 2: Run selector tests to verify failure**

Run:

```bash
cd /home/crz/src/data_collection_pkg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest -q test/test_data_collection_web_dashboard.py
```

Expected: the new option assertions fail because both selectors still list
`policy`.

- [ ] **Step 3: Update both option lists**

Replace only the capture selector values with `teleop`, `http`, `act`, and
`vla`; do not add control-mode requests or policy startup callbacks.

- [ ] **Step 4: Run selector tests and compile/build checks**

Run the focused dashboard tests, then build the Qt panel in Task 4.

- [ ] **Step 5: Commit the UI/profile selection change**

```bash
git add data_collection_rviz_panel/src/main_window.cpp data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py data_collection_pkg/test/test_data_collection_web_dashboard.py
git commit -m "feat: expose act and vla capture profiles"
```

### Task 3: Documentation and compatibility assertions

**Files:**
- Modify: `data_collection_pkg/README.md`
- Modify: `docs/PROJECT_HANDOFF.md`
- Modify: focused data-collection contract tests under `data_collection_pkg/test`

**Interfaces:**
- Documentation names `runtime_mode` as a capture profile and lists the four new values.
- Historical `policy` path examples remain documented only where they describe existing fixtures or compatibility.

- [ ] **Step 1: Add failing documentation/contract assertions**

Add or update tests that assert qpos paths for `act` and `vla` resolve to
`original/act/qpos_gripper` and `original/vla/qpos_gripper`, while an existing
`policy` path can still be passed to replay/export helpers.

- [ ] **Step 2: Run the focused schema/replay tests**

Run:

```bash
cd /home/crz/src/data_collection_pkg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest -q test/test_data_collection_schemas.py test/test_data_collection_replay_simulator.py
```

- [ ] **Step 3: Update README and handoff text**

Document the four capture profiles, the fixed-rate shared collector, the
Mode Manager boundary, and the empty-annotation launch rule. Do not alter
historical fixture paths.

- [ ] **Step 4: Run documentation-adjacent tests**

Re-run the schema/replay tests and verify `git diff --check`.

- [ ] **Step 5: Commit documentation and compatibility tests**

```bash
git add data_collection_pkg/README.md docs/PROJECT_HANDOFF.md data_collection_pkg/test
git commit -m "docs: clarify capture profile and control mode boundaries"
```

### Task 4: Full verification and package builds

**Files:**
- No new production files; inspect all changed files and preserve unrelated dirty worktree entries.

- [ ] **Step 1: Run the complete data-pipeline and panel tests**

```bash
cd /home/crz/src/data_collection_pkg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test ../data_collection_rviz_panel/test
```

- [ ] **Step 2: Build owned packages**

```bash
cd /home/crz/src
source /opt/ros/humble/setup.bash
colcon build --packages-select data_collection_pkg data_collection_rviz_panel
```

- [ ] **Step 3: Inspect the final diff and status**

Run `git diff --check`, `git diff --stat`, and `git status --short`; verify no
external untracked ROS package is staged and no Mode Manager control code was
changed.
