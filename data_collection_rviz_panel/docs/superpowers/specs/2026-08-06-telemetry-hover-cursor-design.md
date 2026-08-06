# Telemetry Hover Cursor Design

## Goal

Make every telemetry chart inspectable: show a relative-time x-axis, a vertical
hover cursor, and the sampled values for every visible joint curve.

## Scope

Only `data_collection_rviz_panel` changes. Capture, replay services, RViz
models, camera transport, and dataset conversion are unchanged.

## Interaction

- Each `TelemetryChart` stores a timestamp together with each six-joint
  sample.
- A replay episode starts at `t = 0.00 s`; its x-axis is the elapsed time
  from that episode's first displayed frame.
- Live data uses a relative rolling time window. The first retained sample is
  the displayed origin.
- Moving the pointer within the plot area draws a vertical cursor at the
  nearest retained sample. A compact overlay shows the selected elapsed time
  and each chart-local joint name/value in that curve's legend color.
- Leaving the plot area hides the cursor and overlay.
- Starting a replay or selecting a different replay episode clears all three
  charts before adding frames, preventing prior live or episode data from
  contaminating the timeline.

## Rendering and units

The existing QWidget/QPainter implementation remains in place. It draws a
small x-axis with elapsed-second labels below the plot. Position values are
shown as rad, velocity as rad/s, and effort retains the incoming driver unit.
The selected frame uses a nearest-sample lookup rather than interpolation so
the values always correspond to recorded data.

## Error handling

The hover overlay is absent when no samples exist or the cursor is outside the
plot area. Samples with missing joints render and report a zero placeholder,
matching the existing chart behavior.

## Verification

The panel contract test asserts the timestamped chart API, hover event hooks,
cursor rendering, timeline label, and chart clearing on replay reset. The
package build and its CTest suite must succeed.
