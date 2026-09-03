# 30 Hz Capture Defaults Design

## Goal

Make the hardware data pipeline use a consistent 30 Hz default from capture
through cleaning and LeRobot export, while preserving explicit request
overrides and compatibility for the previous joint-state tolerance parameter.

## Default Contract

Hardware capture defaults to the scene-camera header clock and these values:

| Setting | Default |
|---|---:|
| `sample_rate_hz` | `30.0` |
| `sampling_clock` | `scene_camera_header` |
| `camera_sync_tolerance_s` | `0.02` |
| `joint_state_sync_tolerance_s` | `0.02` |
| `gripper_sync_tolerance_s` | `0.03` |
| `scene_camera_settle_delay_s` | `0.07` |
| `camera_receive_delay_health_threshold_s` | `0.05` |

The scene and wrist images, and `/joint_states`, must supply header timestamps
in scene-camera-clock mode. The binary `Int8` gripper remains receive-time
stamped and uses its separate 30 ms threshold.

## Parameter Compatibility

`joint_state_sync_tolerance_s` is the canonical joint-state parameter.
`state_max_sync_delta_s` remains accepted only as a legacy fallback:

1. Use `joint_state_sync_tolerance_s` when explicitly supplied.
2. Otherwise use an explicitly supplied `state_max_sync_delta_s` value.
3. Otherwise use the 20 ms default.

The UI and CaptureManager send only the canonical joint-state parameter.

## Cleaning And Export

Cleaning defaults to `target_fps=30.0`, `max_sync_delta_s=0.02`, and retains
the existing 30% frame-period tolerance. Its synchronization check covers
stored image timestamps against the observation timestamp; it cannot recreate
the original joint or receive-time gripper match after capture.

LeRobot export defaults to `fps=30.0`. The generated metadata and encoded
videos therefore use the capture-rate baseline unless an explicit export
request overrides it.

## UI And API

The Qt panel includes capture, cleaning, and export request fields with the
new defaults. The dashboard endpoints forward their JSON payloads unchanged to
CaptureManager. CaptureManager constructs `CleaningConfig` from accepted clean
request fields and passes export `fps` to the converter.

Replay retains its existing independent operator-selected rate. It is not an
offline resampling stage and does not alter the stored timestamps.

## Validation

Tests cover launch and manager defaults, canonical-versus-legacy joint
tolerance precedence, clean-request configuration propagation, and export FPS
propagation. Run the complete Python test suite and build both owned ROS
packages before completion.
