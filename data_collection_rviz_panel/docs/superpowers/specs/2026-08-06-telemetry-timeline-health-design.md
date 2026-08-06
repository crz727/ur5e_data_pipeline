# Telemetry Scale, Seek Timeline, and Health Bar Design

## Goal

Make the Qt/RViz console trustworthy during real-robot capture and replay:
telemetry uses comparable numeric y-scales, replay can seek to an exact frame,
and a persistent header reports the health of the robot, cameras, and writer.

## Scope

The UI work is in `data_collection_rviz_panel`. The only data-pipeline
changes are the dashboard replay controller and its read-only HTTP API. The
collector, camera drivers, robot driver, and motion-control topics are not
changed.

## Telemetry scales

Each chart computes one shared y-range from every visible joint curve, adds a
small margin and a chart-specific minimum range, then draws top/middle/bottom
numeric tick labels. This replaces per-line normalization, so values can be
compared across colors. Position is labelled rad, velocity rad/s, and effort
uses the source driver unit label.

## Seekable replay timeline

The replay card gains a horizontal slider, elapsed time, and
`current frame / total frames` readout. The slider is driven by
`replay_status.frame_index` and is not permitted until replay is active.
Dragging or clicking sends `POST /api/replay/seek` with a zero-based
`frame_index`.

The replay controller keeps the currently loaded episode in memory. A seek
clamps the requested index, applies that recorded observation immediately to
the dashboard telemetry and camera state, reports the selected frame, and
sets the worker's next frame to the following index. Seek is accepted while a
replay is running or paused. It never publishes to robot control topics.

## Header health bar

The existing dashboard connection label is retained. Four compact chips show:

- Robot: `/joint_states` heartbeat from `flow_status`;
- Scene camera: dashboard camera validity and age;
- Wrist camera: dashboard camera validity and age;
- Writer: capture manager availability/running/return code.

Green means active or ready, amber means stale/idle after a nonzero return
code, and red means unavailable or unseen. Chip text includes state and
message age where available.

## Error handling

Invalid seeks return a JSON error without changing telemetry. A seek after
the worker has ended is rejected; the UI disables the slider in terminal
states. Missing flow/camera state is treated as unavailable rather than
healthy. UI updates do not issue a seek while the slider is being programmatically
updated.

## Verification

Python tests cover seek clamping, immediate telemetry update, and next-frame
continuation. The Qt contract test covers scale ticks, timeline/seek wiring,
and the four health-chip fields. Build both packages and run their test suites.
