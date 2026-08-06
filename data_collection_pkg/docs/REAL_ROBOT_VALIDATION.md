# UR5e Real Robot Validation

## Prerequisites

Build and source the workspace that contains `data_collection_pkg` and
`data_collection_rviz_panel`.

```bash
cd ~/ur5e_ws
colcon build --packages-select data_collection_pkg data_collection_rviz_panel
source install/setup.bash
```

Install the optional LeRobot export dependencies in the same Python
environment that launches the dashboard node:

```bash
cd ~/ur5e_ws/src/data_collection_pkg
python3 -m pip install --user --upgrade -r requirements-lerobot.txt
python3 - <<'PY'
import datasets
import pyarrow
import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
print("LeRobot export dependencies available")
PY
```

## Camera Contract

The capture pipeline and dashboard subscribe to compressed images:

```text
/camera2/scene_camera/color/image_raw/compressed
/camera1/wrist_camera/color/image_raw/compressed
```

Both topics must publish `sensor_msgs/msg/CompressedImage`. Confirm each
camera before capture:

```bash
ros2 topic echo /camera2/scene_camera/color/image_raw/compressed --once
ros2 topic echo /camera1/wrist_camera/color/image_raw/compressed --once
```

## Capture and Replay

1. Start the robot, camera drivers, and the normal real-robot bringup.
2. Launch the collection panel:

```bash
QT_QPA_PLATFORM=xcb ros2 launch data_collection_rviz_panel data_collection_rviz_panel.launch.py
```

3. In the panel, select `Teleop`, set the task name, then select `Start Capture`.
4. Wait for the capture status to leave warm-up. Capture runs at 15 Hz. Warm-up waits for synchronized
   UR5e joint state, gripper state, and both required cameras. It is not a
   recorded-data drop.
5. Select `Stop Capture`, then mark the completed episode as Success or Failure.
6. Use `Clean Data` only after capture has stopped. The original data remains
   untouched; accepted episodes are copied to the sibling `cleaned` directory.
7. Choose a cleaned `qpos_gripper` directory in Episode Replay, load the
   episode list, then replay at a safe rate. Replay drives only the dashboard
   visualization topics, never robot hardware.

## LeRobot Export

Only cleaned qpos/gripper data is accepted as export input. The panel starts
export as a background task, so the live camera, model, and replay controls
remain usable while it runs.

Command-line export is also available:

```bash
data_collection convert-jsonl-to-lerobot \
  ~/ur5e_ws/datasets/<task>/cleaned/teleop/qpos_gripper \
  --output-dir ~/ur5e_ws/datasets/<task>/lerobot_export \
  --repo-id local/ur5e_pick_place \
  --fps 15 \
  --camera pano=external \
  --camera wrist \
  --visual-storage video \
  --video-codec h264
```

The cleaner trims only long static leading and trailing ranges in cleaned output;
it leaves original data and any static interval between motion segments unchanged.
The exporter decodes compressed JPEG frames before encoding official LeRobot v3
H.264 MP4 camera streams under `videos/`. Parquet contains state, action, task,
and video time indices, not embedded image bytes. Video export requires an
integer FPS; the current real-robot pipeline uses `15`. A valid dataset reports
`480x640x3` for both current cameras.
