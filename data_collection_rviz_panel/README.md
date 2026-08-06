# UR5e Data Collection RViz Panel

Native C++ Qt/RViz2 front-end for the existing `data_collection_pkg` and
`ur5e_mode_manager` ROS nodes. It subscribes directly to live ROS topics and
uses the Python dashboard only as the Capture/Replay HTTP backend.

## Build

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select data_collection_rviz_panel
```

## Run

For the complete console, start the dashboard backend, a read-only replay
`robot_state_publisher`, and this panel together:

```bash
ros2 launch data_collection_rviz_panel data_collection_rviz_panel.launch.py
```

The launch file does not start a hardware driver or a mode manager. Start the
real UR5e driver and `ur5e_mode_manager` separately when those are required.
The replay publisher only consumes `/data_collection/replay/joint_states` and
publishes TF under the `replay/` prefix, so it cannot send motion commands to
the real controller.

To run only the panel against an already-running backend:

```bash
ros2 run data_collection_rviz_panel data_collection_rviz_panel
```

The panel uses `/robot_description`, `/tf`, `/tf_static`, `/joint_states`,
the two compressed camera topics, and `/control_mode/*`. It never publishes
robot motion commands. Replay uses `/replay/robot_description`, the `replay/`
TF prefix, and the panel's safe `/data_collection/replay/joint_states` stream.
