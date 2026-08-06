# LeRobot v3 MP4 Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LeRobot v3 exports store each camera as MP4 video rather than embedding image bytes in Parquet.

**Architecture:** Keep ROS capture, original JSONL, and cleaned datasets unchanged. Add a `visual_storage` export setting that defaults to `video`; the LeRobot writer declares visual features as `video` and delegates MP4 encoding to the official LeRobot API. The verifier recognizes v3 video metadata/files and the CLI and dashboard propagate the setting.

**Tech Stack:** Python, ROS2 ament_python, LeRobot 0.4.4, FFmpeg through LeRobot, pytest.

## Global Constraints

- Preserve `original` and `cleaned` datasets; only create a new export directory.
- Default exported visual storage is `video` with the LeRobot `h264` codec name.
- LeRobot video export accepts integer FPS only; this pipeline exports its fixed 15 Hz data as 15 FPS video.
- The legacy `image` mode remains available for compatibility.
- Output remains official LeRobot v3, with `codebase_version: v3.0`.

---

### Task 1: Add video-aware writer and converter configuration

**Files:**
- Modify: `data_collection_pkg/dataset/lerobot_writer.py`
- Modify: `data_collection_pkg/dataset/converter.py`
- Test: `test/test_data_collection_lerobot_writer.py`
- Test: `test/test_data_collection_converter.py`

**Interfaces:**
- Produces `LeRobotDatasetWriter(..., visual_storage="video", video_codec="h264")`.
- Produces `convert_jsonl_to_lerobot(..., visual_storage="video", video_codec="h264")`.

- [x] Write failing tests that assert default camera features use `dtype="video"` and that `visual_storage="image"` preserves `dtype="image"`.
- [x] Run the focused tests and confirm they fail because the writer always declares image features.
- [x] Add validated visual-storage arguments, pass `use_videos=True` and `vcodec` to the official dataset only for video output, and declare the selected feature dtype.
- [x] Run focused writer/converter tests and confirm they pass.

### Task 2: Propagate CLI/dashboard settings and verify v3 videos

**Files:**
- Modify: `data_collection_pkg/cli.py`
- Modify: `data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/dataset/lerobot_verify.py`
- Test: `test/test_capture_manager.py`
- Test: `test/test_data_collection_lerobot_verify.py`

**Interfaces:**
- CLI: `convert-jsonl-to-lerobot ... --visual-storage video --video-codec h264`.
- Dashboard payload: `visual_storage` and `video_codec`, defaulting to video/h264.
- Verifier accepts one non-empty `videos/<camera>/...mp4` tree for each expected camera in video mode.

- [x] Write failing tests for CLI/dashboard defaults and video-tree verification.
- [x] Run the focused tests and confirm they fail because the arguments and video verifier are absent.
- [x] Propagate the settings and verify v3 video files without accepting embedded Parquet images in video mode.
- [x] Run focused tests and confirm they pass.

### Task 3: Export and inspect real cleaned data

**Files:**
- Create: `/home/crz/ur5e_ws/datasets/cleaned_0805/lerobot_export_0806_mp4_h264_15hz/`

- [x] Build the data-pipeline package and run its full test suite.
- [x] Export the existing cleaned qpos/gripper data with default video storage into the new directory.
- [x] Verify 23 episodes, 3,589 frames, two MP4 camera trees, and no embedded `observation.images.*` Parquet columns.
