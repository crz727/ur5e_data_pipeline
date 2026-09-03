# Project Handoff

Last updated: 2026-08-11

## Purpose

This document is the persistent starting point for a new conversation about
this workspace. Read it before changing the project. It records the current
data-pipeline scope, verified behavior, real-robot artifacts, known limits,
and outstanding decisions.

## Current Baseline

- Repository root: `/home/crz/src`
- Active branch: `master`
- Latest committed pipeline/UI fix: `ce8bce7 fix: make LeRobot exports retryable`
- The last feature merge is `e2fe44f vladataset`.
- The display redesign is `7240083 0807display`.
- The current worktree also contains untracked external ROS packages,
  `.vscode`, an unpublished weekly report, and earlier planning documents.
  Do not stage them as part of data-pipeline work without an explicit request.

## Ownership Boundary

The owner of this work is responsible for the data pipeline. Keep future edits
within these packages unless a change cannot be completed otherwise:

- `data_collection_pkg`: ROS capture, JSONL/image storage, cleaning, replay,
  LeRobot conversion, CLI, and dashboard HTTP backend.
- `data_collection_rviz_panel`: C++ Qt/RViz native desktop console.

The untracked hardware, teleoperation, description, and driver packages are
outside this ownership boundary. Preserve them and avoid unrelated refactors.

## Implemented System

### Capture

- The UR5e `qpos_gripper` pipeline writes fixed-rate data at 15 Hz.
- Capture profiles are `teleop`, `http`, `act`, and `vla`. They only classify
  the output directory and episode metadata; all four use the same collector,
  action semantics, and synchronization settings. The legacy `policy` path is
  retained for reading historical datasets, but is not a new capture option.
- Observation state and action are both seven values: six absolute joint
  positions followed by gripper state. The action is the next sampled absolute
  target, not a delta command.
- Required camera sources are `external` and `wrist`.
- Default real-robot camera topics are:
  - `/camera2/scene_camera/color/image_raw/compressed`
  - `/camera1/wrist_camera/color/image_raw/compressed`
- ROS `CompressedImage` values such as `rgb8; jpeg compressed bgr8` are stored
  as external JPEG files. The converter decodes them to RGB when creating the
  LeRobot dataset.
- Current capture defaults are 15 Hz, camera synchronization tolerance `0.07 s`,
  and robot-state synchronization tolerance `0.07 s`.

### Annotation And Cleaning

- The existing Task field is retained for capture batch/directory naming.
- The Qt panel has a separate Language Instruction editor with a reusable
  normalized `task_id`, English instruction, and Chinese instruction.
- At capture start, those values are frozen into each episode header in
  `meta/episodes.jsonl`; cleaning preserves them.
- Capture stop opens a human success/failure annotation dialog for the episode
  or episodes just recorded.
- Cleaning creates a sibling `cleaned/<mode>/qpos_gripper` dataset and leaves
  `original` intact.
- The cleaner checks required cameras, duration, frame count, synchronization,
  and static leading/trailing sections. The current defaults include 30 minimum
  frames, 2.0 minimum seconds, 8-frame motion windows, `0.01 rad` joint motion,
  and `0.02` gripper motion thresholds.
- Cleaning produces `meta/cleaning_report.html`,
  `meta/cleaning_summary.json`, and `meta/cleaning_manifest.jsonl`.

### Replay And Desktop UI

- The C++ Qt/RViz panel combines the robot model, live compressed camera
  previews, telemetry charts, capture controls, cleaning, replay controls, and
  Mode Manager status/control.
- Replay has episode selection, pause/resume/seek, a single timeline slider,
  replay robot model, and chart hover values.
- The panel uses the black/red/gold display theme introduced by `0807display`.
- CaptureManager starts only the fixed-rate collector. It does not start
  teleoperation, HTTP control, ACT/VLA policies, robot drivers, or the Mode
  Manager; control mode is switched independently through the Mode Manager.
- Mode Manager integration uses `/control_mode/request`, `/control_mode`, and
  `/control_mode/status`. The V2 manager sets HTTP ownership through
  `/api/system/mode`, matching the current HTTP API contract.
- Start the panel with the safe replay-state publisher setting:

```bash
cd /home/crz/src
source /opt/ros/humble/setup.bash
source install/setup.bash
QT_QPA_PLATFORM=xcb ros2 launch data_collection_rviz_panel \
  data_collection_rviz_panel.launch.py \
  start_replay_state_publisher:=false
```

This panel is a visual and data-control client. It does not start robot
drivers, teleoperation, HTTP control, or policy execution.

### LeRobot v3 Export

- Export always consumes `cleaned/<mode>/qpos_gripper`, never `original`.
- Both profiles use LeRobot v3 Parquet plus H.264 MP4 visual storage:
  - `ACT` uses the normalized `task_id` as the task value. Natural-language
    instructions are present in source metadata but not consumed by ACT.
  - `VLA` uses every episode's English instruction as its LeRobot task. Chinese
    instruction and `task_id` are retained in
    `meta/episode_language_annotations.jsonl`.
- Both profiles write `meta/image_normalization.json` with ImageNet RGB mean
  `[0.485, 0.456, 0.406]` and standard deviation `[0.229, 0.224, 0.225]`.
  This does not overwrite measured `meta/stats.json`.
- Camera mappings are `external -> observation.images.top` and
  `wrist -> observation.images.wrist`.
- VLA preflight skips episodes without a valid English instruction and records
  the decision in `meta/vla_export_report.json`.
- Output directories are immutable. The API and converter reject an existing
  output directory, while the Qt panel suggests an unused suffix such as
  `lerobot_act_v3_1`. This prevents partial output from being reused.
- While ACT or VLA export is active, a second export click reports that an
  export is already running instead of silently doing nothing.

## Verified Real-Robot Dataset

The source dataset copied from the real robot is:

```text
/home/crz/ur5e_ws/dataset_collection_0807/
  ui_capture/teleop_segment_010000_20260807_194620/
    cleaned/teleop/qpos_gripper
```

It contains 73 cleaned episodes and 9466 frames. All inspected external and
wrist frames are valid 640x480 RGB JPEG files; their state and action vectors
have seven values.

The following complete, verified exports exist beside the source dataset:

- ACT: `/home/crz/ur5e_ws/dataset_collection_0807/lerobot_act_v3_retry`
- VLA: `/home/crz/ur5e_ws/dataset_collection_0807/lerobot_vla_v3_retry`

Each has 73 episodes, 9466 frames, 15 Hz metadata, two H.264 MP4 streams, and
a successful `verify_lerobot_export` report at
`meta/data_collection_export_report.json`. The VLA export has 73 language
annotations and no skipped episode.

`/home/crz/ur5e_ws/dataset_collection_0807/lerobot_act_v3` is a partial failed
artifact from before the output-directory protection was added. Do not train
from it and do not overwrite it without an explicit archival or removal
decision.

## Fresh Verification

The last code verification was performed after commit `ce8bce7`:

```bash
cd /home/crz/src/data_collection_pkg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=/home/crz/src/data_collection_pkg \
python3 -m pytest -q test ../data_collection_rviz_panel/test

cd /home/crz/src
source /opt/ros/humble/setup.bash
colcon build --packages-select data_collection_pkg data_collection_rviz_panel
```

Results: 200 tests passed; both selected packages built successfully. The
workspace-wide `colcon build` has not been re-run as part of this handoff.

## Known Limits And Outstanding Work

- Real-robot acceptance testing is still needed after the latest export-retry
  UI build. Confirm the output directory suggestion and busy status on the
  actual operator desktop.
- MP4 creation is CPU-intensive: converting the verified 73-episode dataset
  took about 12 minutes per ACT or VLA export because 9466 JPEG frames are
  decoded and re-encoded into two H.264 streams. The backend runs it
  asynchronously; only one export may run at a time.
- Camera and robot-state synchronization now intentionally use `0.07 s` in the
  collector defaults, capture launch files, and Qt capture-manager fallback.
- The HTTP API package cannot be built in the current workspace until the
  external `robotiq_2f_gripper_msgs` package is built and installed. Its older
  `test_http_mode_guard.py` cases still assert the removed header-based control
  guard and should be updated separately if that package is brought back into
  the workspace build.
- Automatic `candidate_success`, `candidate_failure`, and `needs_review`
  classification based on safety/task-completion signals is not implemented.
  Current success/failure labels are human annotations after capture.
- The root-level untracked external ROS packages and documentation have not
  been classified or committed. Do not delete or bulk-stage them.

## New Conversation Checklist

1. Read this document, then inspect `git status --short` and `git log --oneline -12`.
2. Read [ACT/VLA design](superpowers/specs/2026-08-07-act-vla-export-design.md)
   and [real-robot guide](../data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md)
   before changing capture or export behavior.
3. Keep edits within the ownership boundary and preserve untracked hardware
   packages.
4. Use a new output directory for every LeRobot export. Never reuse a partial
   directory.
5. Run the focused test suite and both package builds before claiming a fix.
6. When changing capture thresholds or real-robot topics, validate with a
   short real-robot recording before producing a training dataset.
