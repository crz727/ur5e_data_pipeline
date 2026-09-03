# HIL Mode Design

## Scope

Add a HIL control mode to the Qt Mode Manager and `ur5e_mode_manager`. HIL is
the existing `pika_teleop` control path without resetting the robot before
teleoperation. Capture modes and the data collection backend are out of scope.

## Control Modes

`teleop` continues to launch `pika_teleop` with
`reset_before_teleop:=true`. New `hil` launches the same executable with
`reset_before_teleop:=false`.

The mode manager owns independent managed processes for Teleop and HIL. A
switch always follows the existing safety sequence: revoke HTTP ownership,
stop AUTO, cancel current ROS motion, stop both Teleop variants, wait for
`/joint_states` to be stable, start the requested target, then publish its
owner. Entering HIL publishes `mode=hil`, `state=ACTIVE`, and `owner=hil`.
Entering IDLE or handling a fault stops both variants.

## Qt Layout

Replace the separate service-control row and four-mode grid with one fixed
two-column, three-row action grid:

```text
Start | IDLE
AUTO  | API
TELEOP| HIL
```

The first button reads `Start` before the panel owns the control services and
`Stop` while it owns and can stop them. Columns have equal stretch and all
buttons retain a fixed minimum row height. No status label shares a row with
the Start/Stop button, so narrow sidebars and scrolling cannot overlap text.

## Interfaces and Tests

The Qt HIL button publishes `std_msgs/String("hil")` on
`/control_mode/request`. The external control requirements remain unchanged:
the HTTP API must be reachable and `/joint_states` must be fresh and stable.

Contract tests assert the HIL command, aliases, cleanup behavior, mode status,
and six-button grid. The focused Python and Qt-panel test suites plus the Qt
package build verify the change.
