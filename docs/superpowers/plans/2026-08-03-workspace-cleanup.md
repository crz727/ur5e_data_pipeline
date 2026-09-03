# Workspace Cleanup And Data Package Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the ROS 2 workspace to source and required assets, remove the RealSense hardware driver, preserve the D435i Gazebo model, and make `data_collection_pkg` a standard two-level ROS package.

**Architecture:** Keep all control, teleoperation, gripper, robot-description, Gazebo, demo, and data-pipeline packages. Move only the D435i model files needed by `my_description` into that package, then remove the RealSense ROS driver tree. Flatten `data_collection_pkg` so its ROS package root is one directory and its Python module is the only child package directory.

**Tech Stack:** ROS 2 Humble, `colcon`, `ament_cmake`, `ament_python`, Python 3, xacro, Gazebo, rsync.

## Global Constraints

- Keep UR5e control, Pika teleoperation, Robotiq gripper, Gazebo simulation, robot description, HTTP API, mode manager, demo nodes, and data collection.
- Remove only the RealSense hardware driver source and generated build artifacts.
- Preserve D435i simulation links and Gazebo camera topics.
- Keep the data package name, entry points, launch files, schemas, topics, and Python imports unchanged.
- Do not delete the local `data_collection_pkg.rar` archive.

---

### Task 1: Remove Generated Workspace Artifacts

**Files:**
- Delete generated directories: `build/`, `install/`, `log/`, `.pytest_cache/`, and `__pycache__/` wherever present under the workspace.
- Delete generated editor databases: `.vscode/browse.vc.db` and `ur_min_demo/.vscode/browse.vc.db`.

**Interfaces:**
- Consumes: Existing workspace source tree.
- Produces: Source-only directories without Python or ROS build outputs.

- [ ] **Step 1: Resolve deletion targets**

Run:

```bash
find /home/crz/src -type d \( -name build -o -name install -o -name log -o -name .pytest_cache -o -name __pycache__ \) -print
find /home/crz/src -type f -name browse.vc.db -print
```

Expected: only generated directories and editor databases are listed; source directories are not targets.

- [ ] **Step 2: Delete only the resolved generated targets**

Run the deletion against the explicit paths returned by Step 1. Do not delete `/home/crz/src/data_collection_pkg.rar`.

- [ ] **Step 3: Verify the cleanup**

Run:

```bash
find /home/crz/src -type d \( -name build -o -name install -o -name log -o -name .pytest_cache -o -name __pycache__ \) -print
find /home/crz/src -type f -name browse.vc.db -print
test -f /home/crz/src/data_collection_pkg.rar
```

Expected: the first two commands produce no output and the archive test exits successfully.

### Task 2: Vendor the Minimal D435i Simulation Description

**Files:**
- Create: `my_description/urdf/_d435.urdf.xacro`
- Create: `my_description/urdf/_d435i.urdf.xacro`
- Create: `my_description/urdf/_d435i_imu_modules.urdf.xacro`
- Create: `my_description/urdf/_materials.urdf.xacro`
- Create: `my_description/urdf/_usb_plug.urdf.xacro`
- Create: `my_description/meshes/d435.dae`
- Create: `my_description/meshes/plug.stl`
- Create: `my_description/meshes/plug_collision.stl`
- Modify: `my_description/urdf/my_robot.urdf.xacro`
- Modify: `my_description/package.xml`

**Interfaces:**
- Consumes: The D435i model subset from `realsense2_description`.
- Produces: A self-contained `my_description` package that expands both `sensor_d435i` instances without a RealSense ROS package.

- [ ] **Step 1: Copy only the model subset and preserve license headers**

Copy the five xacro files and three mesh files listed above from `realsense2_description` into the matching `my_description` subdirectories. Keep the RealSense license headers in copied xacro files.

- [ ] **Step 2: Rewrite model package references**

Replace every `$(find realsense2_description)` include in the copied xacro files with `$(find my_description)`. Replace every `package://realsense2_description/meshes/` URI with `package://my_description/meshes/`.

- [ ] **Step 3: Remove the external description dependency**

Remove `<depend>realsense2_description</depend>` from `my_description/package.xml`. Keep the existing `ur_description`, `robotiq_description`, Gazebo, xacro, and robot-state-publisher dependencies.

- [ ] **Step 4: Point the robot xacro at the vendored model**

Change the D435i include in `my_description/urdf/my_robot.urdf.xacro` from:

```xml
<xacro:include filename="$(find realsense2_description)/urdf/_d435i.urdf.xacro"/>
```

to:

```xml
<xacro:include filename="$(find my_description)/urdf/_d435i.urdf.xacro"/>
```

- [ ] **Step 5: Remove the RealSense driver tree**

Delete `/home/crz/src/realsense-ros-ros2-development` after the copied assets and references are verified.

- [ ] **Step 6: Verify the simulation asset boundary**

Run:

```bash
rg -n 'realsense2_(camera|camera_msgs|description)|package://realsense2_description' /home/crz/src/my_description /home/crz/src/*/package.xml
find /home/crz/src/my_description/urdf -maxdepth 1 -type f -name '_d435*' -print
test -f /home/crz/src/my_description/meshes/d435.dae
```

Expected: no external RealSense package references remain, the five local xacro files exist, and the D435 mesh exists.

### Task 3: Flatten `data_collection_pkg` to Two Levels

**Files:**
- Move: `data_collection_pkg/data_collection_pkg/package.xml` to `data_collection_pkg/package.xml`
- Move: `data_collection_pkg/data_collection_pkg/setup.py` to `data_collection_pkg/setup.py`
- Move: `data_collection_pkg/data_collection_pkg/setup.cfg` to `data_collection_pkg/setup.cfg`
- Move: `data_collection_pkg/data_collection_pkg/README.md` to `data_collection_pkg/README.md`
- Move: `data_collection_pkg/data_collection_pkg/requirements*.txt` to `data_collection_pkg/`
- Move: `data_collection_pkg/data_collection_pkg/LICENSE`, `findings.md`, `progress.md`, and `task_plan.md` to `data_collection_pkg/`
- Move: `data_collection_pkg/data_collection_pkg/launch/`, `docs/`, `resource/`, and `test/` to `data_collection_pkg/`
- Move: `data_collection_pkg/data_collection_pkg/data_collection_pkg/` to `data_collection_pkg/data_collection_pkg/`
- Delete: the empty wrapper directory `data_collection_pkg/data_collection_pkg` after migration.

**Interfaces:**
- Consumes: Existing ROS package root and Python module.
- Produces: Standard ROS layout with `package.xml` and `setup.py` at the package root, and `data_collection_pkg/` as the Python module directory.

- [ ] **Step 1: Confirm source and target contents**

Run:

```bash
find /home/crz/src/data_collection_pkg/data_collection_pkg -maxdepth 2 -type f -print | sort
find /home/crz/src/data_collection_pkg/data_collection_pkg/data_collection_pkg -maxdepth 2 -type f -print | sort
```

Expected: package metadata and launch/test/docs directories are in the first path; Python implementation files are in the second path.

- [ ] **Step 2: Move package-root content up one directory**

Move all package-root files and directories listed above from the wrapper directory into `/home/crz/src/data_collection_pkg`, preserving relative paths.

- [ ] **Step 3: Move the Python module up one directory**

Move the inner Python module directory to `/home/crz/src/data_collection_pkg/data_collection_pkg` and remove only the now-empty wrapper directory.

- [ ] **Step 4: Verify package metadata and imports**

Run:

```bash
test -f /home/crz/src/data_collection_pkg/package.xml
test -f /home/crz/src/data_collection_pkg/setup.py
test -f /home/crz/src/data_collection_pkg/data_collection_pkg/cli.py
rg -n 'data_collection_pkg\.(cli|dataset|ros_capture|action_replay|hardware_check|visualization)' /home/crz/src/data_collection_pkg
```

Expected: metadata is at the root, `cli.py` is one level below it, and imports still use the unchanged package name.

### Task 4: Rebuild Discovery And Run Focused Checks

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: Cleaned workspace and flattened data package.
- Produces: Verified package discovery and import/test results.

- [ ] **Step 1: Check package discovery**

Run:

```bash
colcon list
```

Expected: `data_collection_pkg`, `my_description`, `ur5e_http_api`, `ur5e_mode_manager`, `pika_teleop`, `teleop_ur_ros2`, Robotiq packages, and `ur_min_demo` are discovered; RealSense driver packages are absent.

- [ ] **Step 2: Compile Python sources**

Run:

```bash
python3 -m compileall -q /home/crz/src/data_collection_pkg/data_collection_pkg /home/crz/src/ur5e_http_api/ur5e_http_api /home/crz/src/pika_teleop/pika_teleop /home/crz/src/teleop_ur_ros2/teleop_ur_ros2 /home/crz/src/ur5e_mode_manager/ur5e_mode_manager /home/crz/src/ur_min_demo/ur_min_demo
```

Expected: exit status 0.

- [ ] **Step 3: Run data package checks from the new root**

Run:

```bash
python3 -m data_collection_pkg.cli list-schemas
python3 -m pytest -q /home/crz/src/data_collection_pkg/test
```

Expected: schema names print and the data package tests pass or report only environment-specific ROS integration skips.

- [ ] **Step 4: Confirm no generated outputs are left**

Run:

```bash
find /home/crz/src -type d \( -name build -o -name install -o -name log -o -name .pytest_cache -o -name __pycache__ \) -print
find /home/crz/src -type f -name browse.vc.db -print
```

Expected: no output.
