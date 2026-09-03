"""ROS2 entry point for synchronized data collection."""

import json
from importlib import import_module
from pathlib import Path

from data_collection_pkg.dataset.task_annotations import parse_capture_task_annotation
from data_collection_pkg.ros_capture.collector_engine import TeleopCollectorEngine
from data_collection_pkg.ros_capture.message_adapters import (
    camera_sample,
    gripper_sample,
    joint_state_sample,
    safety_sample,
    servo_l_command_sample,
    end_effector_pose_sample,
)
from data_collection_pkg.ros_capture.qpos_demo_collector import (
    FixedRateQposDemoEngine,
    QposDemoJsonlRecorder,
)
from data_collection_pkg.ros_capture.teleop_recorder import (
    TELEOP_TOPICS,
    TeleopJsonlRecorder,
)


def default_teleop_collector_config() -> dict:
    """Return the default topic/schema contract for teleop collection."""
    return {
        "schema": "teleop_twist_gripper",
        "dataset_source": "teleop",
        "runtime_mode": "teleop",
        "dataset_stage": "original",
        "action_topic": TELEOP_TOPICS["servo_l_command"],
        "gripper_state_topic": TELEOP_TOPICS["gripper_state"],
        "external_camera_topic": TELEOP_TOPICS["external_camera"],
        "wrist_camera_topic": TELEOP_TOPICS["wrist_camera"],
        "safety_state_topic": TELEOP_TOPICS["safety_state"],
        "end_effector_pose_topic": TELEOP_TOPICS["end_effector_pose"],
        "required_topics": (
            TELEOP_TOPICS["joint_states"],
            TELEOP_TOPICS["servo_l_command"],
            TELEOP_TOPICS["gripper_state"],
        ),
        "optional_topics": (
            TELEOP_TOPICS["external_camera"],
            TELEOP_TOPICS["wrist_camera"],
            TELEOP_TOPICS["safety_state"],
            TELEOP_TOPICS["end_effector_pose"],
        ),
        "default_required_cameras": ("external", "wrist"),
        "sync_tolerance_s": 0.07,
        "state_sync_tolerance_s": 0.07,
        "sampling_clock": "timer",
        "camera_sync_tolerance_s": 0.02,
        "gripper_sync_tolerance_s": 0.03,
        "scene_camera_settle_delay_s": 0.07,
        "camera_receive_delay_health_threshold_s": 0.05,
        "sampling_mode": "action_triggered",
        "sample_rate_hz": 15.0,
        "image_storage_format": "jpeg",
        "jpeg_quality": 75,
        "status_topic": "/data_collection/quality_status",
        "drop_topic": "/data_collection/drop_reason",
    }


def default_teleop_subscription_type_names() -> dict:
    """Return ROS2 message type imports for default teleop subscriptions."""
    return {
        "joint_states": "sensor_msgs.msg:JointState",
        "servo_l_command": "std_msgs.msg:Float64MultiArray",
        "gripper_state": "std_msgs.msg:Float64MultiArray",
        "external_camera": "sensor_msgs.msg:CompressedImage",
        "wrist_camera": "sensor_msgs.msg:CompressedImage",
        "safety_state": "std_msgs.msg:String",
        "end_effector_pose": "geometry_msgs.msg:PoseStamped",
    }


class TeleopCollectorNodeAdapter:
    """Wire a node-like object to the teleop collection engine."""

    def __init__(
        self,
        node,
        *,
        root: Path,
        task: str,
        config: dict = None,
        string_msg_type=None,
        subscription_msg_types: dict = None,
        require_message_stamps: bool = False,
        qos: int = 10,
    ) -> None:
        self.node = node
        self.config = config or default_teleop_collector_config()
        self.string_msg_type = string_msg_type or _StringMessage
        self.subscription_msg_types = (
            subscription_msg_types or _placeholder_subscription_message_types()
        )
        self.require_message_stamps = bool(require_message_stamps)
        self.status_publisher = node.create_publisher(
            self.string_msg_type,
            self.config["status_topic"],
            qos,
        )
        self.drop_publisher = node.create_publisher(
            self.string_msg_type,
            self.config["drop_topic"],
            qos,
        )
        self.recorder = TeleopJsonlRecorder(
            Path(root),
            task=task,
            required_cameras=self.config["default_required_cameras"],
            source=self.config["dataset_source"],
            runtime_mode=self.config["runtime_mode"],
            schema_name=self.config["schema"],
            action_topic=self.config["action_topic"],
            gripper_topic=self.config["gripper_state_topic"],
            external_camera_topic=self.config["external_camera_topic"],
            wrist_camera_topic=self.config["wrist_camera_topic"],
            safety_state_topic=self.config["safety_state_topic"],
            end_effector_pose_topic=self.config["end_effector_pose_topic"],
        )
        self.engine = TeleopCollectorEngine(
            recorder=self.recorder,
            required_topics=self.config["required_topics"],
            optional_topics=self.config["optional_topics"],
            action_topic=self.config["action_topic"],
            tolerance_s=self.config["sync_tolerance_s"],
            status_callback=self._publish_status,
            drop_callback=self._publish_drop,
        )
        self._subscriptions = []
        self._wire_subscriptions(qos)

    def close(self) -> dict:
        """Close the underlying recorder."""
        return self.recorder.close()

    def _wire_subscriptions(self, qos: int) -> None:
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["joint_states"],
            TELEOP_TOPICS["joint_states"],
            lambda msg, timestamp=None: self._add_sample(
                TELEOP_TOPICS["joint_states"],
                joint_state_sample,
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["gripper_state"],
            self.config["gripper_state_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["gripper_state_topic"],
                lambda gripper_msg, *, timestamp: gripper_sample(
                    gripper_msg,
                    timestamp=timestamp,
                    topic=self.config["gripper_state_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["servo_l_command"],
            self.config["action_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["action_topic"],
                lambda command_msg, *, timestamp: servo_l_command_sample(
                    command_msg,
                    timestamp=timestamp,
                    topic=self.config["action_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["external_camera"],
            self.config["external_camera_topic"],
            lambda msg, timestamp=None: self._add_camera_sample(
                self.config["external_camera_topic"],
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["wrist_camera"],
            self.config["wrist_camera_topic"],
            lambda msg, timestamp=None: self._add_camera_sample(
                self.config["wrist_camera_topic"],
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["safety_state"],
            self.config["safety_state_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["safety_state_topic"],
                lambda safety_msg, *, timestamp: safety_sample(
                    safety_msg,
                    timestamp=timestamp,
                    topic=self.config["safety_state_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["end_effector_pose"],
            self.config["end_effector_pose_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["end_effector_pose_topic"],
                lambda pose_msg, *, timestamp: end_effector_pose_sample(
                    pose_msg,
                    timestamp=timestamp,
                    topic=self.config["end_effector_pose_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))

    def _add_sample(self, topic: str, sample_factory, msg, explicit_timestamp=None):
        timestamp = self._sample_timestamp(msg, explicit_timestamp)
        if timestamp is None:
            self._publish_drop({
                "timestamp": self._receive_timestamp(),
                "drop_reasons": [f"missing_timestamp:{topic}"],
            })
            return None
        try:
            return self.engine.add_sample(sample_factory(msg, timestamp=timestamp))
        except Exception as exc:
            self._publish_drop({
                "timestamp": timestamp,
                "drop_reasons": [f"adapter_error:{topic}:{exc}"],
            })
            return None

    def _add_camera_sample(self, topic: str, msg, explicit_timestamp=None):
        timestamp = self._sample_timestamp(msg, explicit_timestamp)
        if timestamp is None:
            self._publish_drop({
                "timestamp": self._receive_timestamp(),
                "drop_reasons": [f"missing_timestamp:{topic}"],
            })
            return None
        try:
            return self.engine.add_sample(camera_sample(msg, topic=topic, timestamp=timestamp))
        except Exception as exc:
            self._publish_drop({
                "timestamp": timestamp,
                "drop_reasons": [f"adapter_error:{topic}:{exc}"],
            })
            return None

    def _sample_timestamp(self, msg, explicit=None) -> float:
        return _timestamp(
            msg,
            explicit,
            fallback=self._receive_timestamp(),
            require_stamp=self.require_message_stamps,
        )

    def _receive_timestamp(self) -> float:
        now = self.node.get_clock().now().nanoseconds * 1e-9
        return float(now)

    def _publish_status(self, payload: dict) -> None:
        self.status_publisher.publish(self.string_msg_type(data=json.dumps(payload)))

    def _publish_drop(self, payload: dict) -> None:
        self.drop_publisher.publish(self.string_msg_type(data=json.dumps(payload)))


class FixedRateQposDemoNodeAdapter:
    """Wire a node-like object to fixed-rate ACT-style qpos demonstration capture."""

    def __init__(
        self,
        node,
        *,
        root: Path,
        task: str,
        config: dict = None,
        string_msg_type=None,
        subscription_msg_types: dict = None,
        require_message_stamps: bool = False,
        episode_metadata: dict = None,
        qos: int = 10,
    ) -> None:
        self.node = node
        self.config = config or default_teleop_collector_config()
        self.string_msg_type = string_msg_type or _StringMessage
        self.subscription_msg_types = (
            subscription_msg_types or _placeholder_subscription_message_types()
        )
        self.require_message_stamps = bool(require_message_stamps)
        self.status_publisher = node.create_publisher(
            self.string_msg_type,
            self.config["status_topic"],
            qos,
        )
        self.drop_publisher = node.create_publisher(
            self.string_msg_type,
            self.config["drop_topic"],
            qos,
        )
        self.recorder = QposDemoJsonlRecorder(
            Path(root),
            task=task,
            required_cameras=self.config["default_required_cameras"],
            source=self.config["dataset_source"],
            runtime_mode=self.config["runtime_mode"],
            dataset_stage=self.config["dataset_stage"],
            gripper_topic=self.config["gripper_state_topic"],
            external_camera_topic=self.config["external_camera_topic"],
            wrist_camera_topic=self.config["wrist_camera_topic"],
            safety_state_topic=self.config["safety_state_topic"],
            end_effector_pose_topic=self.config["end_effector_pose_topic"],
            raw_command_topic=self.config["action_topic"],
            image_storage_format=self.config["image_storage_format"],
            jpeg_quality=self.config["jpeg_quality"],
            episode_metadata=episode_metadata,
        )
        self.engine = FixedRateQposDemoEngine(
            recorder=self.recorder,
            required_topics=self.config["required_topics"],
            optional_topics=self.config["optional_topics"],
            raw_command_topic=self.config["action_topic"],
            tolerance_s=self.config["sync_tolerance_s"],
            topic_tolerances={
                TELEOP_TOPICS["joint_states"]: self._state_tolerance(),
                self.config["gripper_state_topic"]: self._gripper_tolerance(),
                self.config["external_camera_topic"]: self._camera_tolerance(),
                self.config["wrist_camera_topic"]: self._camera_tolerance(),
            },
            camera_settle_delay_s=self.config["scene_camera_settle_delay_s"],
            sample_rate_hz=self.config["sample_rate_hz"],
            status_callback=self._publish_status,
            drop_callback=self._publish_drop,
        )
        self._subscriptions = []
        self._camera_receive_delay_s = None
        self._camera_receive_delay_exceeded = False
        self._wire_subscriptions(qos)
        self._timer = node.create_timer(
            1.0 / float(self.config["sample_rate_hz"]),
            self._capture_tick,
        )

    def close(self) -> dict:
        """Close the underlying recorder."""
        return self.recorder.close()

    def _wire_subscriptions(self, qos: int) -> None:
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["joint_states"],
            TELEOP_TOPICS["joint_states"],
            lambda msg, timestamp=None: self._add_sample(
                TELEOP_TOPICS["joint_states"],
                joint_state_sample,
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["gripper_state"],
            self.config["gripper_state_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["gripper_state_topic"],
                lambda gripper_msg, *, timestamp: gripper_sample(
                    gripper_msg,
                    timestamp=timestamp,
                    topic=self.config["gripper_state_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["servo_l_command"],
            self.config["action_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["action_topic"],
                lambda command_msg, *, timestamp: servo_l_command_sample(
                    command_msg,
                    timestamp=timestamp,
                    topic=self.config["action_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["external_camera"],
            self.config["external_camera_topic"],
            lambda msg, timestamp=None: self._add_camera_sample(
                self.config["external_camera_topic"],
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["wrist_camera"],
            self.config["wrist_camera_topic"],
            lambda msg, timestamp=None: self._add_camera_sample(
                self.config["wrist_camera_topic"],
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["safety_state"],
            self.config["safety_state_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["safety_state_topic"],
                lambda safety_msg, *, timestamp: safety_sample(
                    safety_msg,
                    timestamp=timestamp,
                    topic=self.config["safety_state_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))
        self._subscriptions.append(self.node.create_subscription(
            self.subscription_msg_types["end_effector_pose"],
            self.config["end_effector_pose_topic"],
            lambda msg, timestamp=None: self._add_sample(
                self.config["end_effector_pose_topic"],
                lambda pose_msg, *, timestamp: end_effector_pose_sample(
                    pose_msg,
                    timestamp=timestamp,
                    topic=self.config["end_effector_pose_topic"],
                ),
                msg,
                timestamp,
            ),
            qos,
        ))

    def _capture_tick(self) -> None:
        now = self._receive_timestamp()
        if self.config["sampling_clock"] == "scene_camera_header":
            self.engine.flush_camera_anchors(now=now)
            return
        self.engine.capture_at(now)

    def _add_sample(self, topic: str, sample_factory, msg, explicit_timestamp=None):
        timestamp = self._sample_timestamp(
            msg,
            explicit_timestamp,
            require_stamp=self._requires_header_timestamp(topic),
        )
        if timestamp is None:
            self._publish_drop({
                "timestamp": self._receive_timestamp(),
                "drop_reasons": [f"missing_timestamp:{topic}"],
            })
            return None
        try:
            return self.engine.add_sample(sample_factory(msg, timestamp=timestamp))
        except Exception as exc:
            self._publish_drop({
                "timestamp": timestamp,
                "drop_reasons": [f"adapter_error:{topic}:{exc}"],
            })
            return None

    def _add_camera_sample(self, topic: str, msg, explicit_timestamp=None):
        received_at = self._receive_timestamp()
        timestamp = self._sample_timestamp(
            msg,
            explicit_timestamp,
            require_stamp=self._requires_header_timestamp(topic),
        )
        if self._uses_scene_camera_clock() and topic == self.config["external_camera_topic"]:
            header_timestamp = _timestamp(msg, explicit_timestamp, require_stamp=True)
            if header_timestamp is None:
                self._publish_drop({
                    "timestamp": received_at,
                    "drop_reasons": [f"missing_timestamp:{topic}"],
                })
                return None
            timestamp = header_timestamp
        if timestamp is None:
            self._publish_drop({
                "timestamp": self._receive_timestamp(),
                "drop_reasons": [f"missing_timestamp:{topic}"],
            })
            return None
        try:
            sample = camera_sample(msg, topic=topic, timestamp=timestamp)
            self.engine.add_sample(sample)
            if topic == self.config["external_camera_topic"]:
                self._record_camera_receive_delay(received_at, timestamp)
                if self._uses_scene_camera_clock():
                    self.engine.capture_camera_anchor(timestamp, now=received_at)
            return sample
        except Exception as exc:
            self._publish_drop({
                "timestamp": timestamp,
                "drop_reasons": [f"adapter_error:{topic}:{exc}"],
            })
            return None

    def _sample_timestamp(self, msg, explicit=None, *, require_stamp=None) -> float:
        return _timestamp(
            msg,
            explicit,
            fallback=self._receive_timestamp(),
            require_stamp=(
                self.require_message_stamps if require_stamp is None else bool(require_stamp)
            ),
        )

    def _receive_timestamp(self) -> float:
        now = self.node.get_clock().now().nanoseconds * 1e-9
        return float(now)

    def _publish_status(self, payload: dict) -> None:
        status = dict(payload)
        status.update({
            "sampling_clock": self.config["sampling_clock"],
            "camera_receive_delay_s": self._camera_receive_delay_s,
            "camera_receive_delay_health": (
                "unknown" if self._camera_receive_delay_s is None
                else "warning" if self._camera_receive_delay_exceeded
                else "ok"
            ),
            "camera_receive_delay_health_threshold_s": self.config[
                "camera_receive_delay_health_threshold_s"
            ],
        })
        self.status_publisher.publish(self.string_msg_type(data=json.dumps(status)))

    def _publish_drop(self, payload: dict) -> None:
        self.drop_publisher.publish(self.string_msg_type(data=json.dumps(payload)))

    def _uses_scene_camera_clock(self) -> bool:
        return self.config["sampling_clock"] == "scene_camera_header"

    def _requires_header_timestamp(self, topic: str) -> bool:
        if self.require_message_stamps:
            return True
        if not self._uses_scene_camera_clock():
            return False
        return topic in (
            TELEOP_TOPICS["joint_states"],
            self.config["external_camera_topic"],
            self.config["wrist_camera_topic"],
        )

    def _camera_tolerance(self) -> float:
        if self._uses_scene_camera_clock():
            return self.config["camera_sync_tolerance_s"]
        return self.config["sync_tolerance_s"]

    def _state_tolerance(self) -> float:
        if self._uses_scene_camera_clock():
            return self.config["state_sync_tolerance_s"]
        return self.config["state_sync_tolerance_s"]

    def _gripper_tolerance(self) -> float:
        if self._uses_scene_camera_clock():
            return self.config["gripper_sync_tolerance_s"]
        return self.config["state_sync_tolerance_s"]

    def _record_camera_receive_delay(self, received_at: float, header_timestamp: float) -> None:
        self._camera_receive_delay_s = float(received_at) - float(header_timestamp)
        self._camera_receive_delay_exceeded = (
            self._camera_receive_delay_s > self.config["camera_receive_delay_health_threshold_s"]
        )


def collector_node_main(args=None):
    """Start the ROS2 collector node adapter."""
    import rclpy

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("data_collection_collector")
        _declare_parameters(node)
        config = teleop_collector_config_from_parameters(node)
        root = _parameter_value(node, "root", "datasets")
        task = _parameter_value(node, "task", "teleop")
        episode_metadata = parse_capture_task_annotation(
            task_name=str(task),
            task_id=config["task_id"],
            english=config["language_instruction_en"],
            chinese=config["language_instruction_zh"],
        )
        try:
            from std_msgs.msg import String
        except Exception:
            String = _StringMessage
        adapter_class = (
            FixedRateQposDemoNodeAdapter
            if config.get("sampling_mode") == "fixed_rate"
            else TeleopCollectorNodeAdapter
        )
        adapter = adapter_class(
            node,
            root=Path(root),
            task=str(task),
            config=config,
            string_msg_type=String,
            subscription_msg_types=_load_teleop_subscription_message_types(
                teleop_subscription_type_names_from_parameters(node)
            ),
            require_message_stamps=teleop_requires_message_stamps_from_parameters(node),
            **({"episode_metadata": episode_metadata} if adapter_class is FixedRateQposDemoNodeAdapter else {}),
        )
        node.get_logger().info(
            "data_collection collector adapter started "
            f"for schema={config['schema']} sampling_mode={config['sampling_mode']}"
        )
        rclpy.spin(node)
    finally:
        if "adapter" in locals():
            adapter.close()
        _shutdown_rclpy_if_needed(rclpy)


class _StringMessage:
    def __init__(self, data=""):
        self.data = data


class _PlaceholderMessage:
    pass


def _placeholder_subscription_message_types() -> dict:
    return {
        name: _PlaceholderMessage
        for name in default_teleop_subscription_type_names()
    }


def teleop_subscription_type_names_from_parameters(node) -> dict:
    """Return teleop subscription type names, allowing ROS parameters to override defaults."""
    names = dict(default_teleop_subscription_type_names())
    for name in tuple(names):
        parameter_name = f"{name}_msg_type"
        names[name] = str(_parameter_value(node, parameter_name, names[name]))
    return names


def teleop_collector_config_from_parameters(node) -> dict:
    """Return collector config after applying source/schema/action topic parameters."""
    config = dict(default_teleop_collector_config())
    source = str(_parameter_value(node, "source", config["dataset_source"]))
    runtime_mode = str(_parameter_value(node, "runtime_mode", source))
    dataset_stage = str(_parameter_value(node, "dataset_stage", config["dataset_stage"]))
    schema = str(_parameter_value(node, "dataset_schema", config["schema"]))
    sampling_mode = str(_parameter_value(node, "sampling_mode", config["sampling_mode"]))
    sample_rate_hz = float(_parameter_value(node, "sample_rate_hz", config["sample_rate_hz"]))
    sampling_clock = str(_parameter_value(node, "sampling_clock", config["sampling_clock"]))
    camera_sync_tolerance_s = float(_parameter_value(
        node, "camera_sync_tolerance_s", config["camera_sync_tolerance_s"]
    ))
    gripper_sync_tolerance_s = float(_parameter_value(
        node, "gripper_sync_tolerance_s", config["gripper_sync_tolerance_s"]
    ))
    scene_camera_settle_delay_s = float(_parameter_value(
        node, "scene_camera_settle_delay_s", config["scene_camera_settle_delay_s"]
    ))
    camera_receive_delay_health_threshold_s = float(_parameter_value(
        node,
        "camera_receive_delay_health_threshold_s",
        config["camera_receive_delay_health_threshold_s"],
    ))
    image_storage_format = str(_parameter_value(node, "image_storage_format", config["image_storage_format"]))
    jpeg_quality = int(_parameter_value(node, "jpeg_quality", config["jpeg_quality"]))
    task_id = _parameter_value(node, "task_id", "")
    language_instruction_en = _parameter_value(node, "language_instruction_en", "")
    language_instruction_zh = _parameter_value(node, "language_instruction_zh", "")
    action_topic = str(_parameter_value(node, "action_topic", config["action_topic"]))
    gripper_state_topic = str(_parameter_value(node, "gripper_state_topic", config["gripper_state_topic"]))
    external_camera_topic = str(_parameter_value(node, "external_camera_topic", config["external_camera_topic"]))
    wrist_camera_topic = str(_parameter_value(node, "wrist_camera_topic", config["wrist_camera_topic"]))
    safety_state_topic = str(_parameter_value(node, "safety_state_topic", config["safety_state_topic"]))
    end_effector_pose_topic = str(_parameter_value(
        node,
        "end_effector_pose_topic",
        config["end_effector_pose_topic"],
    ))
    required_cameras = _camera_names_from_parameter(
        _parameter_value(node, "required_cameras", ",".join(config["default_required_cameras"]))
    )
    sync_tolerance_s = float(_parameter_value(node, "max_sync_delta_s", config["sync_tolerance_s"]))
    state_sync_tolerance_s = float(_parameter_value(
        node,
        "state_max_sync_delta_s",
        config["state_sync_tolerance_s"],
    ))
    if sampling_mode == "fixed_rate":
        schema = "qpos_gripper"
        required_topics = (
            TELEOP_TOPICS["joint_states"],
            gripper_state_topic,
        )
        optional_topics = (
            action_topic,
            external_camera_topic,
            wrist_camera_topic,
            safety_state_topic,
            end_effector_pose_topic,
        )
        if sampling_clock == "scene_camera_header":
            required_topics += (external_camera_topic, wrist_camera_topic)
            optional_topics = tuple(
                topic for topic in optional_topics
                if topic not in (external_camera_topic, wrist_camera_topic)
            )
    else:
        required_topics = (
            TELEOP_TOPICS["joint_states"],
            action_topic,
            gripper_state_topic,
        )
        optional_topics = (
            external_camera_topic,
            wrist_camera_topic,
            safety_state_topic,
            end_effector_pose_topic,
        )
    config.update({
        "schema": schema,
        "dataset_source": source,
        "runtime_mode": runtime_mode,
        "dataset_stage": dataset_stage,
        "sampling_mode": sampling_mode,
        "sample_rate_hz": sample_rate_hz,
        "sampling_clock": sampling_clock,
        "camera_sync_tolerance_s": camera_sync_tolerance_s,
        "gripper_sync_tolerance_s": gripper_sync_tolerance_s,
        "scene_camera_settle_delay_s": scene_camera_settle_delay_s,
        "camera_receive_delay_health_threshold_s": camera_receive_delay_health_threshold_s,
        "image_storage_format": image_storage_format,
        "jpeg_quality": jpeg_quality,
        "task_id": task_id,
        "language_instruction_en": language_instruction_en,
        "language_instruction_zh": language_instruction_zh,
        "action_topic": action_topic,
        "gripper_state_topic": gripper_state_topic,
        "external_camera_topic": external_camera_topic,
        "wrist_camera_topic": wrist_camera_topic,
        "safety_state_topic": safety_state_topic,
        "end_effector_pose_topic": end_effector_pose_topic,
        "default_required_cameras": required_cameras,
        "sync_tolerance_s": sync_tolerance_s,
        "state_sync_tolerance_s": state_sync_tolerance_s,
        "required_topics": required_topics,
        "optional_topics": optional_topics,
    })
    return config


def teleop_requires_message_stamps_from_parameters(node) -> bool:
    """Return whether input messages must carry their own timestamps."""
    return bool(_parameter_value(node, "require_message_stamps", False))


def _shutdown_rclpy_if_needed(rclpy_module) -> None:
    ok = getattr(rclpy_module, "ok", None)
    if callable(ok) and not ok():
        return
    try:
        rclpy_module.shutdown()
    except Exception as exc:
        if "rcl_shutdown already called" not in str(exc):
            raise


def _camera_names_from_parameter(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, str):
        if value.strip().lower() in ("", "none", "null", "[]"):
            return ()
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(
        str(item).strip()
        for item in value
        if str(item).strip() and str(item).strip().lower() not in ("none", "null")
    )


def _load_teleop_subscription_message_types(type_names=None) -> dict:
    type_names = type_names or default_teleop_subscription_type_names()
    return {
        name: _load_message_type(type_name)
        for name, type_name in type_names.items()
    }


def _load_message_type(type_name: str):
    module_name, class_name = type_name.split(":", 1)
    return getattr(import_module(module_name), class_name)


def _declare_parameters(node) -> None:
    declare = getattr(node, "declare_parameter", None)
    if not callable(declare):
        return
    declare("root", "datasets")
    declare("task", "teleop")
    declare("source", "teleop")
    declare("runtime_mode", "teleop")
    declare("dataset_stage", "original")
    declare("dataset_schema", "teleop_twist_gripper")
    declare("sampling_mode", "action_triggered")
    declare("sample_rate_hz", 15.0)
    declare("sampling_clock", "timer")
    declare("camera_sync_tolerance_s", 0.02)
    declare("gripper_sync_tolerance_s", 0.03)
    declare("scene_camera_settle_delay_s", 0.07)
    declare("camera_receive_delay_health_threshold_s", 0.05)
    declare("image_storage_format", "jpeg")
    declare("jpeg_quality", 75)
    declare("task_id", "")
    declare("language_instruction_en", "")
    declare("language_instruction_zh", "")
    declare("action_topic", TELEOP_TOPICS["servo_l_command"])
    declare("gripper_state_topic", TELEOP_TOPICS["gripper_state"])
    declare("external_camera_topic", TELEOP_TOPICS["external_camera"])
    declare("wrist_camera_topic", TELEOP_TOPICS["wrist_camera"])
    declare("safety_state_topic", TELEOP_TOPICS["safety_state"])
    declare("end_effector_pose_topic", TELEOP_TOPICS["end_effector_pose"])
    declare("required_cameras", "external,wrist")
    declare("max_sync_delta_s", 0.07)
    declare("state_max_sync_delta_s", 0.07)
    declare("require_message_stamps", False)
    for name, type_name in default_teleop_subscription_type_names().items():
        declare(f"{name}_msg_type", type_name)


def _parameter_value(node, name: str, default):
    get_parameter = getattr(node, "get_parameter", None)
    if callable(get_parameter):
        try:
            parameter = get_parameter(name)
        except Exception:
            return default
        value = getattr(parameter, "value", None)
        if value is not None:
            return value
    return default


def _timestamp(msg, explicit, fallback=0.0, require_stamp=False):
    if explicit is not None:
        return explicit
    if isinstance(msg, dict) and "timestamp" in msg:
        return msg["timestamp"]
    if hasattr(msg, "timestamp"):
        return msg.timestamp
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None) if header is not None else None
    sec = getattr(stamp, "sec", None)
    nanosec = getattr(stamp, "nanosec", None)
    if sec is not None and nanosec is not None:
        return float(sec) + float(nanosec) * 1e-9
    if require_stamp:
        return None
    return float(fallback)
