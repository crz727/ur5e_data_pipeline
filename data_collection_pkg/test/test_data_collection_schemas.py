import pytest
from setuptools import find_packages

from data_collection_pkg.dataset.schemas import dataset_relative_dir, get_schema


def test_schemas_use_source_aligned_dataset_dirs():
    assert dataset_relative_dir("qpos_gripper") == "trainable/policy/qpos_gripper"
    assert dataset_relative_dir("teleop_servo_l_pose") == "trainable/teleop/servo_l_pose"
    assert dataset_relative_dir("teleop_twist_gripper") == "trainable/teleop/twist_gripper"
    assert dataset_relative_dir("delta_ee_pose") == "debug/http_api/delta_ee_pose"


def test_qpos_schema_can_be_staged_by_runtime_mode():
    assert (
        dataset_relative_dir(
            "qpos_gripper",
            dataset_stage="original",
            runtime_mode="teleop",
        )
        == "original/teleop/qpos_gripper"
    )
    assert (
        dataset_relative_dir(
            "qpos_gripper",
            dataset_stage="original",
            runtime_mode="http",
        )
        == "original/http/qpos_gripper"
    )
    assert (
        dataset_relative_dir(
            "qpos_gripper",
            dataset_stage="trainable",
            runtime_mode="policy",
        )
        == "trainable/policy/qpos_gripper"
    )


def test_macro_and_debug_schemas_are_separate_from_trainable():
    assert dataset_relative_dir("auto_grasp") == "macro/auto_grasp"
    assert dataset_relative_dir("http_api_action") == "debug/http_api/action"
    assert dataset_relative_dir("debug_replay") == "debug/replay"


def test_schema_metadata_does_not_depend_on_http_endpoints():
    schema = get_schema("teleop_servo_l_pose")

    assert schema.category == "trainable"
    assert schema.runtime_mode == "teleop"
    assert schema.action_dim == 7
    assert not hasattr(schema, "control_endpoint")


def test_teleop_ur_ros2_twist_schema_matches_servo_command_shape():
    schema = get_schema("teleop_twist_gripper")

    assert schema.category == "trainable"
    assert schema.runtime_mode == "teleop"
    assert schema.action_fields == ("vx", "vy", "vz", "wx", "wy", "wz", "gripper")
    assert schema.action_dim == 7


def test_unknown_schema_is_rejected():
    with pytest.raises(KeyError, match="unknown action schema"):
        get_schema("http_macro")


def test_data_collection_package_is_discovered():
    assert "data_collection_pkg" in find_packages(exclude=["test"])
    assert "data_collection_pkg.dataset" in find_packages(exclude=["test"])
    assert "ur5e_lerobot_dataset" not in find_packages(exclude=["test"])
