from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launch_and_hardware_defaults_use_neutral_gripper_topic():
    files = [
        ROOT / "launch" / "data_collection_teleop_ur_ros2.launch.py",
        ROOT / "data_collection_pkg" / "hardware_check" / "hardware_interface_check_node.py",
    ]

    for path in files:
        source = path.read_text(encoding="utf-8")
        assert 'default_value="/gripper/state"' in source or '"/gripper/state"' in source
        assert "/robotiq/gripper/state" not in source


def test_user_docs_do_not_reference_removed_teleop_dataset_paths():
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "REAL_ROBOT_VALIDATION.md",
        ROOT / "docs" / "ros2_manual_verification.md",
    ]

    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "trainable/teleop_servo_l_pose" not in source
        assert "trainable/teleop/servo_l_pose" not in source
