# UR5e Data Pipeline Final Delivery Package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Create a self-contained Chinese-language delivery directory containing the current `data_collection_pkg` and `data_collection_rviz_panel` ROS 2 packages plus environment, interface, release, experiment, and operation documentation.

**Architecture:** Preserve the existing package boundaries and copy the current source tree into `ur5e_date_pipeline/`. The Python package remains responsible for capture, synchronization, cleaning, LeRobot export, replay, and the HTTP dashboard. The C++ package remains responsible for the Qt/RViz operator console and delegates capture/control lifecycle to the dashboard and external mode/control services. Build artifacts and workspace-local logs are excluded.

**Tech Stack:** ROS 2 Humble, Python 3, `ament_python`, C++17, Qt5 Widgets/Network, RViz2, Flask, NumPy, optional LeRobot 0.4.4, pytest, colcon.

## Global Constraints

- Use the exact requested delivery directory name `ur5e_date_pipeline`.
- Keep the original source directories and unrelated workspace changes untouched.
- Documentation in the delivery directory must be Chinese, while preserving literal ROS/package/API names and shell commands.
- Do not include `build/`, `install/`, `log/`, `.pytest_cache/`, editor state, or generated archives inside either package copy.
- Document external dependencies without copying or modifying `ur5e_mode_manager`, `ur5e_http_api`, robot drivers, camera drivers, or gripper drivers.
- Verify the copied directory itself with package builds, focused tests, and a whitespace check.

### Task 1: Create the delivery source tree

**Files:**
- Create: `ur5e_date_pipeline/data_collection_pkg/`
- Create: `ur5e_date_pipeline/data_collection_rviz_panel/`

- [ ] Copy only source, launch, tests, package manifests, setup/build files, and package-owned docs.
- [ ] Exclude workspace-generated build/install/log/cache artifacts.
- [ ] Confirm the copy includes the current uncommitted implementation and contract tests.

### Task 2: Add Chinese delivery documentation

**Files:**
- Create: `ur5e_date_pipeline/README.md`
- Create: `ur5e_date_pipeline/docs/ENVIRONMENT.md`
- Create: `ur5e_date_pipeline/docs/INTERFACES.md`
- Create: `ur5e_date_pipeline/docs/CHANGELOG.md`
- Create: `ur5e_date_pipeline/docs/EXPERIMENTS.md`
- Create: `ur5e_date_pipeline/docs/OPERATION_GUIDE.md`

- [ ] Document installation, ROS setup, Python/LeRobot dependencies, and build commands.
- [ ] Document node/launch entry points, topics, parameters, HTTP endpoints, dataset layout, and ownership boundaries.
- [ ] Summarize the recent capture clock, 15 Hz, split tolerances, gripper topic, UI lifecycle, export progress, and process cleanup changes.
- [ ] Record verified tests and real-robot observations separately from outstanding hardware acceptance checks.
- [ ] Provide startup preparation, normal startup, every visible button, every main panel/tab, capture, cleaning, export, replay, and shutdown procedures.

### Task 3: Verify the delivery tree

- [ ] Build both packages from `ur5e_date_pipeline` in an isolated temporary ROS workspace.
- [ ] Run Python data-pipeline tests and the Qt contract test from the copied sources.
- [ ] Run `git diff --check` and scan documentation links/commands for obvious path errors.

