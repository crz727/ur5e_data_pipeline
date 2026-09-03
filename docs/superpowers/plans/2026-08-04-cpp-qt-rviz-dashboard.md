# C++ Qt/RViz Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Replace the browser UI with a single C++ Qt application that embeds RViz2, displays compressed cameras and telemetry, preserves data-pipeline controls, and integrates the UR5e mode manager.

**Architecture:** Add an independent `data_collection_rviz_panel` `ament_cmake` package. The Qt process owns the GUI and RViz render panel, subscribes directly to ROS topics for live state, and uses the existing Python dashboard HTTP endpoints for capture/replay commands so dataset logic remains in `data_collection_pkg`. Mode requests use the existing `/control_mode/*` topics.

**Tech Stack:** C++17, Qt Widgets, Qt Network, Qt Charts, ROS 2 `rclcpp`, `sensor_msgs`, `std_msgs`, `geometry_msgs`, `tf2_ros`, `rviz_common`, `rviz_rendering`, `rviz_default_plugins`.

## Global Constraints

- Keep changes scoped to `/home/crz/src/data_collection_rviz_panel` plus minimal documented adapters in `data_collection_pkg`.
- Do not publish real robot motion commands from the GUI or replay path.
- Keep compressed camera topics as the default: `/camera2/scene_camera/color/image_raw/compressed` and `/camera1/wrist_camera/color/image_raw/compressed`.
- Preserve Capture, Quality, Drop Reason, Replay, and mode-manager behavior.
- Treat RViz/Qt availability as a build prerequisite and report when it is unavailable.

### Task 1: C++ package and Qt/ROS shell

**Files:**
- Create: `data_collection_rviz_panel/package.xml`
- Create: `data_collection_rviz_panel/CMakeLists.txt`
- Create: `data_collection_rviz_panel/src/main.cpp`
- Create: `data_collection_rviz_panel/src/main_window.cpp`
- Create: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Test: `data_collection_rviz_panel/test/test_package_layout.py`

- [ ] Add the ament_cmake package, Qt target, ROS dependencies, and `data_collection_rviz_panel` executable.
- [ ] Create `MainWindow` with a Qt central widget, placeholder panels, and a ROS executor worker that marshals callbacks to the GUI thread.
- [ ] Add a package-layout test that verifies `package.xml`, `CMakeLists.txt`, and the executable source exist.
- [ ] Run the layout test and `cmake`/`colcon build` when the ROS/Qt toolchain is available.

### Task 2: RViz and live telemetry

**Files:**
- Modify: `main_window.hpp/.cpp`
- Create: `src/rviz_panel.cpp`
- Create: `src/camera_widget.cpp`
- Create: `src/telemetry_panel.cpp`
- Test: `test/test_topic_contract.py`

- [ ] Embed `rviz_common::RenderPanel`, configure RobotModel/TF/Grid, and expose `robot_description` and fixed-frame parameters.
- [ ] Subscribe to `/joint_states`, `/robotiq_2f_gripper/joint_states`, `/tcp_pose_broadcaster/pose`, and both compressed camera topics.
- [ ] Decode `CompressedImage.data` to `QImage` and render two camera widgets.
- [ ] Render qpos/qvel/effort histories using Qt Charts with bounded history.
- [ ] Test that the default topic contract matches the current data pipeline.

### Task 3: Capture, quality, replay, and mode control

**Files:**
- Create: `src/dashboard_client.cpp`
- Create: `src/mode_manager_client.cpp`
- Modify: `main_window.cpp`
- Test: `test/test_api_contract.py`

- [ ] Implement asynchronous HTTP calls to the existing capture/replay endpoints through `QNetworkAccessManager`.
- [ ] Add Capture mode/task controls and Dataset Path display without duplicating Python dataset logic.
- [ ] Add Quality, Drop Reason, Key Topics, Topology, and Replay Status views from `/api/state`.
- [ ] Publish mode requests and subscribe to `/control_mode` and `/control_mode/status`.
- [ ] Disable repeated mode requests while the backend reports `SWITCHING` and render fault text.
- [ ] Keep replay read-only; add a replay ROS joint-state adapter only if RViz must animate replayed episodes.

### Task 4: Build and deployment validation

**Files:**
- Modify: `data_collection_pkg/docs/ros2_manual_verification.md`
- Create: `data_collection_rviz_panel/README.md`

- [ ] Build the new package with the workspace's ROS distribution.
- [ ] Run unit/layout tests and Python regression tests.
- [ ] Validate live topics and `/robot_description` on the robot.
- [ ] Document launch order, Qt/RViz prerequisites, and the no-ROS disconnected state.

