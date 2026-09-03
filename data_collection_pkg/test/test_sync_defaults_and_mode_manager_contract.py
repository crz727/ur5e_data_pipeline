from pathlib import Path

import pytest

from data_collection_pkg.ros_capture.collector_node import default_teleop_collector_config


SRC_ROOT = Path(__file__).resolve().parents[2]


def test_capture_sync_defaults_separate_camera_joint_and_gripper_tolerances():
    config = default_teleop_collector_config()
    assert config["sync_tolerance_s"] == 0.07
    assert config["state_sync_tolerance_s"] == 0.02
    assert config["joint_state_sync_tolerance_s"] == 0.02
    assert config["camera_sync_tolerance_s"] == 0.02
    assert config["gripper_sync_tolerance_s"] == 0.03

    collector_source = (
        SRC_ROOT / "data_collection_pkg" / "data_collection_pkg" / "ros_capture" / "collector_node.py"
    ).read_text(encoding="utf-8")
    assert 'declare("max_sync_delta_s", 0.07)' in collector_source
    assert 'declare("camera_sync_tolerance_s", 0.02)' in collector_source
    assert 'declare("joint_state_sync_tolerance_s", None)' in collector_source
    assert 'declare("gripper_sync_tolerance_s", 0.03)' in collector_source

    hardware_launch = (
        SRC_ROOT / "data_collection_pkg" / "launch" / "data_collection_hardware_qpos.launch.py"
    ).read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("max_sync_delta_s", default_value="0.07")' in hardware_launch
    assert 'DeclareLaunchArgument("camera_sync_tolerance_s", default_value="0.02")' in hardware_launch
    assert 'DeclareLaunchArgument("joint_state_sync_tolerance_s", default_value="0.02")' in hardware_launch
    assert 'DeclareLaunchArgument("gripper_sync_tolerance_s", default_value="0.03")' in hardware_launch

    for launch_name in (
        "data_collection_http_api.launch.py",
        "data_collection_teleop_demo_qpos.launch.py",
        "data_collection_teleop_ur_ros2.launch.py",
    ):
        launch_source = (
            SRC_ROOT / "data_collection_pkg" / "launch" / launch_name
        ).read_text(encoding="utf-8")
        assert 'DeclareLaunchArgument("max_sync_delta_s", default_value="0.07")' in launch_source

    capture_manager_source = (
        SRC_ROOT / "data_collection_pkg" / "data_collection_pkg" / "visualization" / "capture_manager.py"
    ).read_text(encoding="utf-8")
    assert "payload.get('camera_sync_tolerance_s', 0.02)" in capture_manager_source
    assert "payload.get('joint_state_sync_tolerance_s', payload.get('state_max_sync_delta_s', 0.02))" in capture_manager_source
    assert "payload.get('gripper_sync_tolerance_s', 0.03)" in capture_manager_source


def test_panel_mode_topics_and_mode_manager_runtime_contract_match():
    panel_source = (
        SRC_ROOT / "data_collection_rviz_panel" / "src" / "main_window.cpp"
    ).read_text(encoding="utf-8")
    for topic in ("/control_mode/request", "/control_mode", "/control_mode/status"):
        assert topic in panel_source
    for mode in ("idle", "auto", "api", "teleop"):
        assert mode in panel_source

    external_sources = (
        SRC_ROOT / "ur5e_mode_manager" / "ur5e_mode_manager" / "mode_manager.py",
        SRC_ROOT / "ur5e_http_api" / "ur5e_http_api" / "ros_controller.py",
        SRC_ROOT / "ur5e_mode_manager" / "package.xml",
        SRC_ROOT / "ur5e_mode_manager" / "setup.py",
    )
    if not all(path.is_file() for path in external_sources):
        pytest.skip("external mode-manager and HTTP API packages are not in this checkout")

    mode_manager_source = (
        SRC_ROOT / "ur5e_mode_manager" / "ur5e_mode_manager" / "mode_manager.py"
    ).read_text(encoding="utf-8")
    ros_controller_source = (
        SRC_ROOT / "ur5e_http_api" / "ur5e_http_api" / "ros_controller.py"
    ).read_text(encoding="utf-8")
    package_xml = (
        SRC_ROOT / "ur5e_mode_manager" / "package.xml"
    ).read_text(encoding="utf-8")

    for topic in ("/control_mode/request", "/control_mode", "/control_mode/status"):
        assert topic in mode_manager_source
    for mode in ("idle", "auto", "api", "teleop"):
        assert mode in panel_source
        assert mode in mode_manager_source
    assert '"none", "idle", "autonomous", "http_control", "teleop"' in ros_controller_source
    assert 'self._http("POST", "/api/system/mode"' in mode_manager_source
    assert 'if "HTTP 404:" not in str(exc):' in mode_manager_source
    assert 'self._http("POST", "/api/system/owner"' in mode_manager_source
    assert "<depend>sensor_msgs</depend>" in package_xml
    assert "mode_manager = ur5e_mode_manager.mode_manager:main" in (
        SRC_ROOT / "ur5e_mode_manager" / "setup.py"
    ).read_text(encoding="utf-8")
