import inspect
import json
import pytest
from types import SimpleNamespace

import data_collection_pkg.action_replay.ursim_rviz_adapter_node as ursim_rviz
import data_collection_pkg.hardware_check.hardware_interface_check_node as hardware_check
import data_collection_pkg.ros_capture.collector_node as collector_node
import data_collection_pkg.ros_capture.teleop_bridge_node as teleop_bridge
import data_collection_pkg.visualization.web_dashboard_node as web_dashboard_node


def test_ros_node_module_imports_without_ros2_installed():
    assert callable(collector_node.collector_node_main)
    assert callable(teleop_bridge.teleop_bridge_node_main)
    assert callable(hardware_check.hardware_interface_check_node_main)
    assert callable(ursim_rviz.ursim_rviz_replay_adapter_node_main)
    assert callable(web_dashboard_node.web_dashboard_node_main)


def test_ros_nodes_keep_rclpy_imports_inside_startup_functions():
    source = inspect.getsource(collector_node)
    before_first_function = source.split("def collector_node_main", 1)[0]

    assert "import rclpy" not in before_first_function

    dashboard_source = inspect.getsource(web_dashboard_node)
    before_dashboard_start = dashboard_source.split("def web_dashboard_node_main", 1)[0]

    assert "import rclpy" not in before_dashboard_start

    hardware_source = inspect.getsource(hardware_check)
    before_hardware_start = hardware_source.split("def hardware_interface_check_node_main", 1)[0]

    assert "import rclpy" not in before_hardware_start


def test_collector_node_exposes_default_teleop_config():
    config = collector_node.default_teleop_collector_config()

    assert config["schema"] == "teleop_twist_gripper"
    assert "/joint_states" in config["required_topics"]
    assert "/teleop/command" in config["required_topics"]
    assert "/tool0/pose" in config["optional_topics"]
    assert config["dataset_source"] == "teleop"
    assert config["status_topic"] == "/data_collection/quality_status"
    assert config["drop_topic"] == "/data_collection/drop_reason"
    assert config["external_camera_topic"] == "/camera2/scene_camera/color/image_raw/compressed"
    assert config["wrist_camera_topic"] == "/camera1/wrist_camera/color/image_raw/compressed"


def test_collector_node_declares_real_ros2_subscription_message_types():
    names = collector_node.default_teleop_subscription_type_names()

    assert names["joint_states"] == "sensor_msgs.msg:JointState"
    assert names["servo_l_command"] == "std_msgs.msg:Float64MultiArray"
    assert names["gripper_state"] == "std_msgs.msg:Float64MultiArray"
    assert names["external_camera"] == "sensor_msgs.msg:CompressedImage"
    assert names["wrist_camera"] == "sensor_msgs.msg:CompressedImage"
    assert names["end_effector_pose"] == "geometry_msgs.msg:PoseStamped"
    assert object not in names.values()


def test_collector_timestamp_falls_back_for_messages_without_stamp():
    msg = SimpleNamespace()

    timestamp = collector_node._timestamp(msg, None, fallback=123.456)

    assert timestamp == 123.456


def test_collector_timestamp_can_require_message_stamp():
    msg = SimpleNamespace()

    timestamp = collector_node._timestamp(
        msg,
        None,
        fallback=123.456,
        require_stamp=True,
    )

    assert timestamp is None


def test_collector_timestamp_uses_header_stamp_when_present():
    msg = SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=12, nanosec=345000000),
        ),
    )

    timestamp = collector_node._timestamp(
        msg,
        None,
        fallback=999.0,
        require_stamp=True,
    )

    assert timestamp == 12.345


def test_collector_shutdown_ignores_already_shutdown_context():
    class FakeRclpy:
        @staticmethod
        def ok():
            return False

        @staticmethod
        def shutdown():
            raise AssertionError("shutdown should not be called")

    collector_node._shutdown_rclpy_if_needed(FakeRclpy)


def test_collector_shutdown_calls_active_context():
    class FakeRclpy:
        shutdown_called = False

        @staticmethod
        def ok():
            return True

        @classmethod
        def shutdown(cls):
            cls.shutdown_called = True

    collector_node._shutdown_rclpy_if_needed(FakeRclpy)

    assert FakeRclpy.shutdown_called is True


def test_collector_can_override_subscription_message_type_names_from_parameters():
    node = _ParameterNode({
        "servo_l_command_msg_type": "custom_msgs.msg:ServoCommandStamped",
        "gripper_state_msg_type": "custom_msgs.msg:GripperStateStamped",
        "require_message_stamps": True,
    })

    names = collector_node.teleop_subscription_type_names_from_parameters(node)

    assert names["servo_l_command"] == "custom_msgs.msg:ServoCommandStamped"
    assert names["gripper_state"] == "custom_msgs.msg:GripperStateStamped"
    assert collector_node.teleop_requires_message_stamps_from_parameters(node) is True


def test_collector_config_can_be_overridden_for_http_api_source():
    node = _ParameterNode({
        "source": "http_api",
        "runtime_mode": "http_api",
        "dataset_schema": "qpos_gripper",
        "action_topic": "/ur5e/control/action_event",
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["schema"] == "qpos_gripper"
    assert config["dataset_source"] == "http_api"
    assert config["runtime_mode"] == "http_api"
    assert "/ur5e/control/action_event" in config["required_topics"]
    assert "/teleop/command" not in config["required_topics"]


def test_collector_config_can_override_gripper_state_topic():
    node = _ParameterNode({
        "gripper_state_topic": "/robotiq/gripper/state",
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["gripper_state_topic"] == "/robotiq/gripper/state"
    assert "/robotiq/gripper/state" in config["required_topics"]
    assert "/gripper/state" not in config["required_topics"]


def test_collector_config_can_override_real_robot_camera_and_tcp_topics():
    node = _ParameterNode({
        "external_camera_topic": "/camera2/scene_camera/color/image_raw",
        "wrist_camera_topic": "/camera1/wrist_camera/color/image_raw",
        "end_effector_pose_topic": "/tcp_pose_broadcaster/pose",
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["external_camera_topic"] == "/camera2/scene_camera/color/image_raw"
    assert config["wrist_camera_topic"] == "/camera1/wrist_camera/color/image_raw"
    assert config["end_effector_pose_topic"] == "/tcp_pose_broadcaster/pose"
    assert "/camera2/scene_camera/color/image_raw" in config["optional_topics"]
    assert "/camera1/wrist_camera/color/image_raw" in config["optional_topics"]
    assert "/tcp_pose_broadcaster/pose" in config["optional_topics"]
    assert "/camera/external/color/image_raw" not in config["optional_topics"]
    assert "/camera/wrist/color/image_raw" not in config["optional_topics"]
    assert "/tool0/pose" not in config["optional_topics"]


def test_collector_config_can_disable_required_cameras_for_debug_sources():
    node = _ParameterNode({
        "required_cameras": "",
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["default_required_cameras"] == ()


def test_collector_config_treats_none_required_cameras_as_disabled():
    node = _ParameterNode({
        "required_cameras": "none",
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["default_required_cameras"] == ()


def test_collector_config_can_override_sync_tolerance():
    node = _ParameterNode({
        "max_sync_delta_s": 0.02,
    })

    config = collector_node.teleop_collector_config_from_parameters(node)

    assert config["sync_tolerance_s"] == 0.02


def test_fixed_rate_config_enables_scene_camera_clock_with_independent_tolerances():
    config = collector_node.teleop_collector_config_from_parameters(_ParameterNode({
        "sampling_mode": "fixed_rate",
        "sampling_clock": "scene_camera_header",
        "camera_sync_tolerance_s": 0.02,
        "joint_state_sync_tolerance_s": 0.02,
        "gripper_sync_tolerance_s": 0.03,
        "scene_camera_settle_delay_s": 0.07,
    }))

    assert config["sampling_clock"] == "scene_camera_header"
    assert config["camera_sync_tolerance_s"] == 0.02
    assert config["state_sync_tolerance_s"] == 0.02
    assert config["gripper_sync_tolerance_s"] == 0.03
    assert config["scene_camera_settle_delay_s"] == 0.07
    assert config["external_camera_topic"] in config["required_topics"]
    assert config["wrist_camera_topic"] in config["required_topics"]


def test_fixed_rate_config_uses_legacy_state_tolerance_only_without_canonical_parameter():
    legacy = collector_node.teleop_collector_config_from_parameters(_ParameterNode({
        "sampling_mode": "fixed_rate",
        "state_max_sync_delta_s": 0.04,
    }))
    canonical = collector_node.teleop_collector_config_from_parameters(_ParameterNode({
        "sampling_mode": "fixed_rate",
        "state_max_sync_delta_s": 0.04,
        "joint_state_sync_tolerance_s": 0.02,
    }))

    assert legacy["state_sync_tolerance_s"] == 0.04
    assert canonical["state_sync_tolerance_s"] == 0.02
    assert canonical["sample_rate_hz"] == 15.0


def test_fixed_rate_adapter_queues_scene_camera_header_only_in_camera_clock_mode(tmp_path):
    config = collector_node.default_teleop_collector_config()
    config.update({
        "sampling_mode": "fixed_rate",
        "sampling_clock": "scene_camera_header",
        "required_topics": ("/joint_states", "/gripper/state", "/scene", "/wrist"),
        "optional_topics": (),
        "external_camera_topic": "/scene",
        "wrist_camera_topic": "/wrist",
        "default_required_cameras": ("external", "wrist"),
    })
    node = _FixedRateFakeNode()
    adapter = collector_node.FixedRateQposDemoNodeAdapter(
        node,
        root=tmp_path,
        task="camera_clock",
        config=config,
    )

    node.subscriptions["/scene"](SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(sec=12, nanosec=0)),
        format="jpeg",
        data=b"scene",
    ))

    assert adapter.engine.camera_anchor_timestamps == [12.0]
    assert adapter._camera_receive_delay_s == pytest.approx(111.456789)


def test_camera_clock_rejects_unstamped_joint_and_wrist_samples(tmp_path):
    config = collector_node.default_teleop_collector_config()
    config.update({
        "sampling_mode": "fixed_rate",
        "sampling_clock": "scene_camera_header",
        "required_topics": ("/joint_states", "/gripper/state", "/scene", "/wrist"),
        "optional_topics": (),
        "external_camera_topic": "/scene",
        "wrist_camera_topic": "/wrist",
    })
    node = _FixedRateFakeNode()
    collector_node.FixedRateQposDemoNodeAdapter(
        node,
        root=tmp_path,
        task="camera_clock",
        config=config,
    )

    node.subscriptions["/joint_states"](SimpleNamespace(position=[0.0] * 6))
    node.subscriptions["/wrist"](SimpleNamespace(format="jpeg", data=b"wrist"))

    drops = [json.loads(message.data)["drop_reasons"] for message in node.publishers[
        "/data_collection/drop_reason"
    ].messages]
    assert ["missing_timestamp:/joint_states"] in drops
    assert ["missing_timestamp:/wrist"] in drops


def test_fixed_rate_node_adapter_forwards_annotation_to_episode_metadata(tmp_path):
    annotation = {
        "task_name": "pick_place_batch_0807",
        "task_id": "pick_red_block_to_blue_tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
        "annotation_source": "capture_ui",
    }
    config = collector_node.default_teleop_collector_config()
    config.update({
        "sampling_mode": "fixed_rate",
        "schema": "qpos_gripper",
        "default_required_cameras": (),
        "required_topics": ("/joint_states", "/gripper/state"),
        "optional_topics": (),
    })
    node = _FixedRateFakeNode()
    adapter = collector_node.FixedRateQposDemoNodeAdapter(
        node,
        root=tmp_path,
        task="pick_place_batch_0807",
        config=config,
        episode_metadata=annotation,
    )
    adapter.recorder.writer.start_episode()
    adapter.recorder.writer.add_frame({"timestamp": 1.0, "state": [0.0] * 7}, [0.0] * 7)
    adapter.recorder.writer.close_episode()

    episode = json.loads((adapter.recorder.writer.meta_dir / "episodes.jsonl").read_text(encoding="utf-8"))

    assert episode["task_name"] == "pick_place_batch_0807"
    assert episode["task_id"] == "pick_red_block_to_blue_tray"
    assert episode["language_instruction_en"] == "Pick up the red block and place it in the blue tray."
    assert episode["language_instruction_zh"] == "抓取红色方块并放入蓝色托盘。"
    assert episode["annotation_source"] == "capture_ui"


def test_collector_config_reads_capture_task_annotation_parameters():
    config = collector_node.teleop_collector_config_from_parameters(_ParameterNode({
        "task_id": "pick-red-block-to-blue-tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
    }))

    assert config["task_id"] == "pick-red-block-to-blue-tray"
    assert config["language_instruction_en"] == "Pick up the red block and place it in the blue tray."
    assert config["language_instruction_zh"] == "抓取红色方块并放入蓝色托盘。"


def test_strict_collector_drops_unstamped_command_without_crashing(tmp_path):
    node = _FakeNode()
    adapter = collector_node.TeleopCollectorNodeAdapter(
        node,
        root=tmp_path,
        task="strict",
        require_message_stamps=True,
    )

    node.subscriptions["/teleop/command"](SimpleNamespace(data=[0.0] * 7))

    assert adapter.engine.accepted_frames == 0
    assert node.publishers["/data_collection/drop_reason"].messages
    assert "missing_timestamp:/teleop/command" in (
        node.publishers["/data_collection/drop_reason"].messages[-1].data
    )


def test_collector_adapter_records_from_custom_action_topic(tmp_path):
    action_topic = "/ur5e/control/action_event"
    config = collector_node.default_teleop_collector_config()
    config.update({
        "schema": "qpos_gripper",
        "dataset_source": "http_api",
        "runtime_mode": "http_api",
        "action_topic": action_topic,
        "required_topics": (
            "/joint_states",
            action_topic,
            "/gripper/state",
        ),
        "default_required_cameras": (),
    })
    node = _FakeNode()
    adapter = collector_node.TeleopCollectorNodeAdapter(
        node,
        root=tmp_path,
        task="api",
        config=config,
    )

    node.subscriptions["/joint_states"](SimpleNamespace(
        position=[0.0] * 6,
        velocity=[0.0] * 6,
        effort=[0.0] * 6,
    ))
    node.subscriptions["/gripper/state"](SimpleNamespace(data=[0.5]))
    node.subscriptions[action_topic](SimpleNamespace(data=[0.1] * 7))

    assert adapter.engine.accepted_frames == 1


def test_collector_adapter_records_from_custom_gripper_topic(tmp_path):
    gripper_topic = "/robotiq/gripper/state"
    config = collector_node.default_teleop_collector_config()
    config.update({
        "gripper_state_topic": gripper_topic,
        "required_topics": (
            "/joint_states",
            "/teleop/command",
            gripper_topic,
        ),
        "default_required_cameras": (),
    })
    node = _FakeNode()
    adapter = collector_node.TeleopCollectorNodeAdapter(
        node,
        root=tmp_path,
        task="robotiq",
        config=config,
    )

    node.subscriptions["/joint_states"](SimpleNamespace(
        position=[0.0] * 6,
        velocity=[0.0] * 6,
        effort=[0.0] * 6,
    ))
    node.subscriptions[gripper_topic](SimpleNamespace(data=[0.5]))
    node.subscriptions["/teleop/command"](SimpleNamespace(data=[0.1] * 7))

    assert adapter.engine.accepted_frames == 1


def test_collector_adapter_subscribes_to_custom_real_robot_topics(tmp_path):
    config = collector_node.default_teleop_collector_config()
    config.update({
        "external_camera_topic": "/camera2/scene_camera/color/image_raw",
        "wrist_camera_topic": "/camera1/wrist_camera/color/image_raw",
        "end_effector_pose_topic": "/tcp_pose_broadcaster/pose",
        "optional_topics": (
            "/camera2/scene_camera/color/image_raw",
            "/camera1/wrist_camera/color/image_raw",
            "/safety/state",
            "/tcp_pose_broadcaster/pose",
        ),
        "default_required_cameras": (),
    })
    node = _FakeNode()

    collector_node.TeleopCollectorNodeAdapter(
        node,
        root=tmp_path,
        task="real_topics",
        config=config,
    )

    assert "/camera2/scene_camera/color/image_raw" in node.subscriptions
    assert "/camera1/wrist_camera/color/image_raw" in node.subscriptions
    assert "/tcp_pose_broadcaster/pose" in node.subscriptions
    assert "/camera/external/color/image_raw" not in node.subscriptions
    assert "/camera/wrist/color/image_raw" not in node.subscriptions
    assert "/tool0/pose" not in node.subscriptions


def test_action_replay_subpackage_is_discovered():
    from setuptools import find_packages

    packages = find_packages(exclude=["test"])

    assert "data_collection_pkg.action_replay" in packages
    assert "data_collection_pkg.ros_capture" in packages
    assert "data_collection_pkg.visualization" in packages


def test_dashboard_adapter_subscribes_to_compressed_camera_topics():
    node = _FakeNode()
    store = web_dashboard_node.DashboardStateStore()
    web_dashboard_node.WebDashboardNodeAdapter(
        node=node,
        string_msg_type=object,
        compressed_image_msg_type=object,
        store=store,
    )

    assert "/camera2/scene_camera/color/image_raw/compressed" in node.subscriptions
    assert "/camera1/wrist_camera/color/image_raw/compressed" in node.subscriptions
    node.subscriptions["/camera2/scene_camera/color/image_raw/compressed"](
        SimpleNamespace(format="jpeg", data=b"\xff\xd8scene\xff\xd9")
    )

    assert store.image("external")["codec"] == "jpeg"
    assert store.image("external")["data"] == b"\xff\xd8scene\xff\xd9"


def test_dashboard_adapter_subscribes_to_live_telemetry_topics():
    node = _FakeNode()
    store = web_dashboard_node.DashboardStateStore()
    web_dashboard_node.WebDashboardNodeAdapter(
        node=node,
        string_msg_type=object,
        compressed_image_msg_type=object,
        joint_state_msg_type=object,
        pose_msg_type=object,
        store=store,
    )

    assert "/joint_states" in node.subscriptions
    assert "/robotiq_2f_gripper/joint_states" in node.subscriptions
    assert "/tcp_pose_broadcaster/pose" in node.subscriptions
    node.subscriptions["/joint_states"](SimpleNamespace(
        name=["shoulder_pan_joint"],
        position=[0.25],
        velocity=[0.5],
        effort=[0.75],
    ))

    latest = store.snapshot()["telemetry"]["latest"]
    assert latest["joint_names"] == ["shoulder_pan_joint"]
    assert latest["qpos"] == [0.25]


class _ParameterNode:
    def __init__(self, values):
        self.values = dict(values)
        self.declared = {}

    def declare_parameter(self, name, default):
        self.declared[name] = default
        return SimpleNamespace(value=self.values.get(name, default))

    def get_parameter(self, name):
        return SimpleNamespace(value=self.values.get(name, self.declared.get(name)))


class _FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class _FakeClock:
    def now(self):
        return SimpleNamespace(nanoseconds=123456789000)


class _FakeNode:
    def __init__(self):
        self.publishers = {}
        self.subscriptions = {}

    def create_publisher(self, _msg_type, topic, _qos):
        publisher = _FakePublisher()
        self.publishers[topic] = publisher
        return publisher

    def create_subscription(self, _msg_type, topic, callback, _qos):
        self.subscriptions[topic] = callback
        return callback

    def get_clock(self):
        return _FakeClock()


class _FixedRateFakeNode(_FakeNode):
    def create_timer(self, _period, callback):
        self.timer = callback
        return callback
