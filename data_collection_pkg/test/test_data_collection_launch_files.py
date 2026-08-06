from pathlib import Path


def test_http_api_collection_launch_is_packaged():
    root = Path(__file__).resolve().parents[1]
    launch_path = root / "launch" / "data_collection_http_api.launch.py"
    setup_path = root / "setup.py"

    assert launch_path.exists()
    assert "launch/data_collection_http_api.launch.py" in setup_path.read_text(encoding="utf-8")


def test_hardware_qpos_collection_launch_is_packaged_and_fixed_rate():
    root = Path(__file__).resolve().parents[1]
    launch_path = root / "launch" / "data_collection_hardware_qpos.launch.py"
    setup_path = root / "setup.py"

    launch_text = launch_path.read_text(encoding="utf-8")
    assert launch_path.exists()
    assert '"sampling_mode": "fixed_rate"' in launch_text
    assert '"dataset_stage": LaunchConfiguration("dataset_stage")' in launch_text
    assert '"dataset_schema": "qpos_gripper"' in launch_text
    assert 'DeclareLaunchArgument("sample_rate_hz", default_value="15.0")' in launch_text
    assert 'DeclareLaunchArgument("max_sync_delta_s", default_value="0.07")' in launch_text
    assert 'DeclareLaunchArgument("state_max_sync_delta_s", default_value="0.03")' in launch_text
    assert "action_topic" not in launch_text
    assert "launch/data_collection_hardware_qpos.launch.py" in setup_path.read_text(
        encoding="utf-8"
    )


def test_teleop_launch_exposes_real_robot_topic_arguments():
    root = Path(__file__).resolve().parents[1]
    launch_text = (root / "launch" / "data_collection_teleop_ur_ros2.launch.py").read_text(
        encoding="utf-8"
    )

    assert "external_camera_topic" in launch_text
    assert "wrist_camera_topic" in launch_text
    assert "end_effector_pose_topic" in launch_text
    assert "/camera2/scene_camera/color/image_raw/compressed" in launch_text
    assert "/camera1/wrist_camera/color/image_raw/compressed" in launch_text


def test_topology_monitor_declares_monitored_topics_as_string_parameter():
    root = Path(__file__).resolve().parents[1]
    node_text = (
        root
        / "data_collection_pkg"
        / "visualization"
        / "topology_monitor_node.py"
    ).read_text(encoding="utf-8")

    assert 'node.declare_parameter("monitored_topics", "")' in node_text


def test_monitor_launch_uses_real_robot_active_window():
    root = Path(__file__).resolve().parents[1]
    launch_text = (root / "launch" / "data_collection_monitor.launch.py").read_text(
        encoding="utf-8"
    )

    assert 'DeclareLaunchArgument("active_age_s", default_value="2.0")' in launch_text
    assert "/camera2/scene_camera/color/image_raw/compressed" in launch_text
    assert "/camera1/wrist_camera/color/image_raw/compressed" in launch_text
