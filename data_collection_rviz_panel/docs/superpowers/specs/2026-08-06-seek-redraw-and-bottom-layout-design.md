# Seek Redraw and Bottom Operation Layout Design

## Goal

Keep telemetry visible after replay seeking and make diagnostic information and
operator controls occupy distinct, predictable regions.

## Seek redraw

The replay dashboard already returns bounded telemetry history. On a
non-adjacent replay frame change, each chart replaces its data with the
timestamp-sorted history for its own field (qpos, qvel, or effort) instead of
clearing and appending only the selected sample. The selected observation still
updates the replay robot model and cameras. This preserves a visible line
after seek while retaining the current timeline position.

## Layout

The upper workspace retains the left RViz/camera column and the right
telemetry charts. The lower workspace becomes a horizontal splitter:

- lower left: compact JSON diagnostic tabs;
- lower right: a vertically scrollable Mode, Capture, and Replay operation
  area.

The fixed Replay Timeline remains above the workspace. The lower right is
reserved for controls, not diagnostic JSON.

## Capture result dialog

Replace the platform-dependent QMessageBox ordering with a custom QDialog.
Its horizontal button row is always Success, Failure, Cancel from left to
right. Success and Failure remain explicit annotation actions; Cancel leaves
the episode unreviewed.

## Verification

The panel contract test covers history replacement, the lower splitter,
operation scroll area, and dialog button order. The panel must compile and
the test suite must pass.
