import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def _load_hardware_qpos_launch_description(monkeypatch):
    class LaunchDescription:
        def __init__(self, entities):
            self.entities = entities

    class DeclareLaunchArgument:
        def __init__(self, name, *, default_value):
            self.name = name
            self.default_value = default_value

    class LaunchConfiguration:
        def __init__(self, name):
            self.name = name

    class Node:
        def __init__(self, **kwargs):
            self.parameters = kwargs["parameters"]

    launch_module = ModuleType("launch")
    launch_module.LaunchDescription = LaunchDescription
    launch_actions = ModuleType("launch.actions")
    launch_actions.DeclareLaunchArgument = DeclareLaunchArgument
    launch_substitutions = ModuleType("launch.substitutions")
    launch_substitutions.LaunchConfiguration = LaunchConfiguration
    launch_ros_actions = ModuleType("launch_ros.actions")
    launch_ros_actions.Node = Node
    monkeypatch.setitem(sys.modules, "launch", launch_module)
    monkeypatch.setitem(sys.modules, "launch.actions", launch_actions)
    monkeypatch.setitem(sys.modules, "launch.substitutions", launch_substitutions)
    monkeypatch.setitem(sys.modules, "launch_ros", ModuleType("launch_ros"))
    monkeypatch.setitem(sys.modules, "launch_ros.actions", launch_ros_actions)

    launch_path = Path(__file__).resolve().parents[1] / "launch" / "data_collection_hardware_qpos.launch.py"
    spec = importlib.util.spec_from_file_location("hardware_qpos_launch_under_test", launch_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.generate_launch_description(), DeclareLaunchArgument, Node


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
    assert 'DeclareLaunchArgument("state_max_sync_delta_s", default_value="0.07")' in launch_text
    assert "action_topic" not in launch_text
    assert "launch/data_collection_hardware_qpos.launch.py" in setup_path.read_text(
        encoding="utf-8"
    )


def test_hardware_qpos_launch_declares_and_forwards_task_language_parameters(monkeypatch):
    description, argument_type, node_type = _load_hardware_qpos_launch_description(monkeypatch)

    declared = {
        entity.name: entity.default_value
        for entity in description.entities
        if isinstance(entity, argument_type)
    }
    node = next(entity for entity in description.entities if isinstance(entity, node_type))
    parameters = node.parameters[0]

    assert {
        "task_id": "",
        "language_instruction_en": "",
        "language_instruction_zh": "",
    }.items() <= declared.items()
    assert {
        name: parameters[name].name
        for name in (
            "task_id",
            "language_instruction_en",
            "language_instruction_zh",
        )
    } == {
        "task_id": "task_id",
        "language_instruction_en": "language_instruction_en",
        "language_instruction_zh": "language_instruction_zh",
    }


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
