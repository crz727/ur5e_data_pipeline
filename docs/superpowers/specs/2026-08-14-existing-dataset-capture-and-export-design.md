# Existing Dataset Capture And Export Design

## Goal

Allow the Qt console to resume collection into an existing original
`qpos_gripper` dataset and launch ACT or VLA LeRobot conversion from any
selected cleaned dataset.

## Resume Capture

The user selects an exact `original/<mode>/qpos_gripper` directory. The
backend resolves and validates it, derives the task root and capture mode,
loads the latest episode's task/language metadata, and makes it the active
capture target. The UI updates its mode, task, language indicator, and dataset
path from dashboard state.

Capture can continue only with that directory's mode. The existing JSONL
writer selects the next available episode index, so new data is appended
without replacing previous episode JSONL files or images. `New Task` clears
the resumed-target state. Cleaning and LeRobot output are never changed by
resuming capture; the operator must clean again after appending episodes.

## Standalone LeRobot Conversion

The Capture section includes a `Convert LeRobot...` action independent of the
current capture task. It selects an exact `cleaned/<mode>/qpos_gripper`
directory, asks for ACT or VLA, then reuses the existing output-directory
selection, collision prevention, asynchronous export, busy indicator, and VLA
preflight. It does not accept original data or run cleaning automatically.

## Validation

The backend accepts historical directories anywhere on the local filesystem,
provided their resolved path matches the required stage/mode/schema structure
and contains `meta/episodes.jsonl`. A resumed mode mismatch rejects capture.
The UI performs matching structural validation before starting a standalone
export; converter-side validation remains authoritative.

## Non-goals

- Merging different task roots or runtime modes.
- Appending to cleaned or LeRobot output directories.
- Automatically cleaning, overwriting LeRobot output, or altering episode
  metadata already stored on disk.
