# Qt Control Services Design

## Goal

Allow the data-collection Qt panel to start and stop the local HTTP API and
mode-manager processes through one stateful button, without taking ownership
of the UR driver or any hardware node.

## Scope

The Mode Manager panel receives one `Start control services` / `Stop control
services` button. It manages only processes the panel itself created:

- `ros2 run ur5e_http_api run_api`
- `ros2 run ur5e_mode_manager mode_manager`

The UR driver, External Control program, controller manager, cameras, gripper
driver, dashboard backend, and policy processes remain external prerequisites.
The panel detects ROS/HTTP state but never starts or stops those dependencies.

## Process Ownership

Before start, the panel checks whether the HTTP API and Mode Manager already
appear to be active. If either service is externally managed, the panel shows
that condition and does not create duplicate processes or claim it can stop
them. It starts owned services detached and records only their PIDs, so
closing the panel does not terminate them. Only PIDs created by the current
panel instance are eligible for stop.

Starting is ordered: launch the HTTP API, wait for `GET /api/health` to
succeed, launch the Mode Manager, then wait for a valid
`/control_mode/status` message. The button stays disabled while this sequence
is running. A failed start stops only the processes started by that attempt
and reports the failed stage.

Stopping is ordered: publish an `idle` request, wait for mode-manager status
`state=IDLE` and `owner=none`, terminate the owned Mode Manager, then
terminate the owned HTTP API. On timeout or an invalid status, processes stay
alive and the panel reports the failure. Closing the Qt window does not stop
control services.

## HIL Transition

`AUTO -> IDLE -> TELEOP` is a safe mode handoff, not a pause/resume feature.
The existing manager stops the AUTO process, cancels active motion, waits for
joint-state stability, and removes ownership before publishing `idle`. The
operator must wait for the resulting `IDLE` state and `owner=none` before
requesting TELEOP. Re-entering AUTO launches a new autonomous process and
does not restore its previous in-memory policy state.

## Verification

Source-contract tests cover the stateful button, explicit process ownership,
ordered health/status checks, idle-before-stop behavior, and the absence of
hardware-driver commands. Build verification covers the Qt package. Real
robot validation verifies the status transitions and that externally started
services are never stopped by the panel.

## Non-goals

- Adding the old GUI's broken fault-reset button.
- Starting or stopping UR driver, ros2_control, cameras, gripper, or policies.
- Changing mode-manager ownership transitions or collector behavior.
