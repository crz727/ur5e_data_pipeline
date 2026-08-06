import json
import math
import inspect
from types import SimpleNamespace

import data_collection_pkg.hardware_check.hardware_interface_check_node as hardware_check
from data_collection_pkg.hardware_check.hardware_interface_check_node import (
    HardwareInterfaceReport,
    _as_bool,
    _message_type_parts,
    check_gripper_state,
    check_image,
    check_joint_state,
    check_safety_state,
)


def test_joint_state_check_accepts_six_finite_positions():
    msg = SimpleNamespace(
        position=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        velocity=[0.0] * 6,
        effort=[0.0] * 6,
    )

    result = check_joint_state(msg)

    assert result["ok"] is True
    assert result["details"]["joint_count"] == 6


def test_joint_state_check_rejects_nonfinite_values():
    msg = SimpleNamespace(position=[0.0, 0.1, math.nan, 0.3, 0.4, 0.5])

    result = check_joint_state(msg)

    assert result["ok"] is False
    assert result["reason"] == "position contains non-finite values"


def test_gripper_check_normalizes_robotiq_gpo():
    msg = SimpleNamespace(gPO=128)

    result = check_gripper_state(msg)

    assert result["ok"] is True
    assert result["details"]["field"] == "gPO"
    assert result["details"]["gripper"] == 128 / 255.0


def test_gripper_check_accepts_normalized_position_field():
    msg = SimpleNamespace(position=0.25)

    result = check_gripper_state(msg)

    assert result["ok"] is True
    assert result["details"]["gripper"] == 0.25


def test_gripper_check_reports_unknown_field_layout():
    msg = SimpleNamespace(actual_position=12)

    result = check_gripper_state(msg)

    assert result["ok"] is False
    assert result["reason"] == "no supported gripper field found"


def test_image_check_requires_dimensions_and_data():
    msg = SimpleNamespace(width=640, height=480, data=b"123")

    result = check_image(msg)

    assert result["ok"] is True
    assert result["details"]["width"] == 640
    assert result["details"]["height"] == 480


def test_image_check_accepts_compressed_jpeg_without_raw_dimensions():
    msg = SimpleNamespace(format="jpeg", data=b"\xff\xd8jpeg\xff\xd9")

    result = check_image(msg)

    assert result["ok"] is True
    assert result["details"]["codec"] == "jpeg"


def test_safety_check_accepts_inactive_json_string():
    msg = SimpleNamespace(data=json.dumps({
        "software_estop": False,
        "protective_stop": False,
        "gello_intervention": False,
    }))

    result = check_safety_state(msg)

    assert result["ok"] is True


def test_report_ok_requires_required_checks_to_pass():
    report = HardwareInterfaceReport()
    report.set_check("joint_states", True)
    report.set_check("robotiq_state", False, reason="missing")

    payload = report.to_dict(required=("joint_states", "robotiq_state"))

    assert payload["ok"] is False
    assert payload["checks"][1]["reason"] == "missing"


def test_ros_bool_parameter_strings_are_parsed_explicitly():
    assert _as_bool("false") is False
    assert _as_bool("true") is True
    assert _as_bool(False) is False


def test_message_type_parser_accepts_ros2_and_python_forms():
    assert _message_type_parts("std_msgs.msg:Float64MultiArray") == (
        "std_msgs.msg",
        "Float64MultiArray",
    )
    assert _message_type_parts("robotiq_2f_msgs/msg/Robotiq2FGripperRobotInput") == (
        "robotiq_2f_msgs.msg",
        "Robotiq2FGripperRobotInput",
    )


def test_hardware_check_does_not_create_publishers():
    source = inspect.getsource(hardware_check)

    assert "create_publisher" not in source
