# Capture Mode Boundary Design

## Goal

Make the capture-mode contract explicit and remove the startup failure caused
by empty ROS launch arguments, while keeping control-mode ownership in the
Mode Manager.

## Scope

The capture UI and dashboard expose four capture profiles:

- `teleop`
- `http`
- `act`
- `vla`

The profile is a storage and metadata classification only. Every profile uses
the same fixed-rate `qpos_gripper` collector, with the existing 15 Hz sampling
and 0.07 s camera/state synchronization defaults. `CaptureManager` starts and
stops only that collector process; it does not start teleoperation, HTTP,
ACT/VLA policy processes, robot drivers, or the Mode Manager.

The existing `runtime_mode` field is retained for API, JSONL, cleaning, and
replay compatibility. Its meaning is documented as a capture profile rather
than a robot control mode. Historical `policy` directories remain readable,
but new capture requests reject `policy` and use `act` or `vla` instead.

## Annotation Launch Contract

`task_id`, `language_instruction_en`, and `language_instruction_zh` are
optional launch arguments. `CaptureManager` appends `name:=value` only when a
normalized annotation value is non-empty. An empty annotation therefore
produces a valid `ros2 launch` command without `task_id:=` or language
arguments. Non-empty values continue to be passed unchanged after the
existing annotation normalization/validation.

Capture itself does not require language, including for the `vla` profile.
VLA export preflight remains the gate that accepts only episodes with valid
English instructions and reports skipped episodes. This preserves the ability
to record first and annotate later without making collector startup fragile.

## UI/API Behavior

The Qt capture selector and the Web dashboard selector use the same four
profile values. Start responses continue to report `runtime_mode` and the
resolved dataset path. No control-mode request is emitted as a side effect of
starting capture.

## Verification

Tests will cover:

1. the allowlist accepts `teleop`, `http`, `act`, and `vla`, and rejects new
   `policy` capture requests;
2. empty annotations are omitted from the launch command and a no-language
   start regression remains valid;
3. non-empty annotations are still forwarded;
4. capture commands contain only the hardware collector launch and no control
   process command;
5. Qt and Web selectors expose the four profiles and no `policy` option;
6. existing synchronization defaults and historical dataset/replay behavior
   remain unchanged.

## Non-goals

- Starting or configuring ACT/VLA policy execution.
- Changing Mode Manager control-mode names or ownership transitions.
- Changing fixed-rate sampling, action semantics, camera topics, or dataset
  schemas.
- Migrating or deleting existing `policy` datasets.
