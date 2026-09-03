# Workspace Cleanup And Data Package Layout

## Scope

Keep the UR5e control, Pika teleoperation, Robotiq gripper, Gazebo simulation,
robot description, HTTP API, mode manager, demo nodes, and data collection
package. Remove only the RealSense hardware driver source and generated build
artifacts.

## Cleanup

- Remove `realsense-ros-ros2-development/`, which contains the RealSense ROS
  hardware driver and its driver-specific messages.
- Preserve the D435i simulation links and Gazebo camera topics in
  `my_description` by vendoring only the D435i description xacro dependencies
  and required mesh files into `my_description`. No RealSense ROS package
  dependency remains.
- Remove generated `build/`, `install/`, `log/`, `.pytest_cache/`, and
  `__pycache__/` content.
- Remove large editor database files such as `.vscode/browse.vc.db`.
- Keep source files, tests, descriptions, and configuration files.

## Data Package Layout

Move the package root currently at
`data_collection_pkg/data_collection_pkg/` to `data_collection_pkg/` and move
the Python module currently at
`data_collection_pkg/data_collection_pkg/data_collection_pkg/` to
`data_collection_pkg/data_collection_pkg/`.

The resulting layout is:

```text
data_collection_pkg/
  package.xml
  setup.py
  launch/
  docs/
  test/
  data_collection_pkg/
    __init__.py
    cli.py
    dataset/
    ros_capture/
    action_replay/
    hardware_check/
    visualization/
```

The package name, entry points, launch files, schemas, topics, and Python
imports remain unchanged. Only filesystem nesting is changed.

## Compatibility Adjustment

Because the RealSense driver package is removed while the simulated D435i
model remains, `my_description` will own the small model subset it needs:
`_d435.urdf.xacro`, `_d435i.urdf.xacro`, `_d435i_imu_modules.urdf.xacro`,
`_materials.urdf.xacro`, `_usb_plug.urdf.xacro`, and the D435/plug meshes.
The xacro includes and mesh URIs will point at `my_description`, while Gazebo
camera plugins and topics remain unchanged.

## Verification

- `colcon list` must discover `data_collection_pkg` from its new root.
- No active package may reference `realsense2_camera` as a runtime driver.
- Python package files must compile.
- Data package CLI and focused unit tests must run from the new layout.
