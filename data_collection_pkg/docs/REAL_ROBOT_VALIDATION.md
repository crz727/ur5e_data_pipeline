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

### Manual validation checklist

Run this checklist with one disposable real-robot capture and retain the
resulting paths and reports with the validation record:

1. Create Task `pick_place_batch_0807`.
2. Set task ID `pick-red-block-to-blue-tray` and enter both English and
   Chinese instructions (for example, “Pick the red block to the blue tray” /
   “把红色方块放到蓝色托盘”). Task is the dataset/task-root name; task ID is
   the stable per-instruction identifier and must not be substituted for the
   root folder.
3. Capture, stop, and inspect
   `original/teleop/qpos_gripper/meta/episodes.jsonl`. Each episode header must
   contain the frozen task ID and English/Chinese language snapshot; do not
   rely only on a mutable session file.
4. Mark success, run **Clean Data**, and inspect
   `cleaned/teleop/qpos_gripper/meta/episodes.jsonl`. Confirm accepted
   annotations are inherited, rejected episodes are absent, and files under
   `original/` are byte-for-byte unchanged. Keep the cleaning dialog open until
   **Close**; export is asynchronous and may be started after cleaning returns.
5. Export ACT from the cleaned directory and inspect the official LeRobot
   artifacts: `meta/episodes/*.parquet`, `meta/info.json`, `meta/stats.json`,
   `data/*.parquet`, `videos/observation.images.top/*.mp4`,
   `videos/observation.images.wrist/*.mp4`, and
   `meta/image_normalization.json`. Confirm 15 Hz, UR5e 7-D state/action,
   top→external and wrist→wrist camera mapping. Image preprocessing is
   `RGB / 255.0`, then ImageNet subtraction and division:
   `(rgb_float - [0.485, 0.456, 0.406]) /
   [0.229, 0.224, 0.225]`. The metadata documents this transform and must not
   overwrite observed LeRobot statistics.
6. Export VLA from the same cleaned directory and inspect the task mapping,
   `meta/episode_language_annotations.jsonl` (English task plus retained
   Chinese text), and `meta/vla_export_report.json`. Verify report eligible,
   skipped, and source→output mapping counts against the source episode
   headers. VLA task text is English; Chinese remains in the sidecar.
7. Remove English (`language_instruction_en`) from one fixture episode; ACT
   accepts the cleaned episode, while VLA skips it and records the episode index
   and reason in `vla_export_report.json`. VLA must never silently drop an
   episode.

For every run, attach the command output and the paths checked above to the
validation report. If no real robot is available, perform steps 3–7 against a
cleaned fixture dataset and label the run as fixture-only.

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

### Final review gates

- Task creates/selects task-root folders independently from task ID.
- Episode headers contain frozen language snapshots; cleaning preserves accepted
  annotations without mutating original data.
- ACT accepts unlabeled cleaned episodes. VLA exports only valid-English
  episodes and records every skipped episode.
- VLA task text is English, with Chinese retained in the sidecar.
- Both profiles retain 15 Hz, UR5e 7-D state/action, top/wrist MP4 mapping, and
  ImageNet metadata. ImageNet metadata does not replace measured LeRobot stats.
- Cleaning remains open until **Close**, and exports run asynchronously.
