"""ROS2 entry point for real-time topology and flow monitoring."""

import json

from data_collection_pkg.visualization.topology import (
    FlowHeartbeatMonitor,
    TopicEndpoint,
    build_topology_graph,
)

DEFAULT_MONITORED_TOPICS = (
    "/joint_states",
    "/tf",
    "/tf_static",
    "/robotiq_2f_gripper/joint_states",
    "/camera2/scene_camera/color/image_raw/compressed",
    "/camera1/wrist_camera/color/image_raw/compressed",
    "/tcp_pose_broadcaster/pose",
    "/safety/state",
    "/data_collection/quality_status",
    "/data_collection/drop_reason",
)


def topology_monitor_node_main(args=None):
    """Start the ROS2 topology monitor adapter."""
    import rclpy
    from std_msgs.msg import String

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("data_collection_topology_monitor")
        _declare_parameters(node)
        node_adapter = TopologyMonitorNodeAdapter(
            node=node,
            string_msg_type=String,
        )
        node.get_logger().info("data_collection topology monitor adapter started")
        rclpy.spin(node)
    finally:
        rclpy.shutdown()


class TopologyMonitorNodeAdapter:
    """Bridge ROS2 graph inspection into JSON topic outputs."""

    def __init__(self, *, node, string_msg_type) -> None:
        self.node = node
        self.string_msg_type = string_msg_type
        self.topology_publisher = node.create_publisher(
            string_msg_type,
            "/data_collection/topology_graph",
            10,
        )
        self.flow_publisher = node.create_publisher(
            string_msg_type,
            "/data_collection/flow_status",
            10,
        )
        self.monitored_topics = tuple(
            _parameter_list(node, "monitored_topics", DEFAULT_MONITORED_TOPICS)
        )
        self.active_age_s = float(_parameter_value(node, "active_age_s", 2.0))
        self.publish_rate_hz = float(_parameter_value(node, "publish_rate_hz", 2.0))
        self.heartbeat = FlowHeartbeatMonitor(self.monitored_topics)
        self.subscriptions = {}
        self._last_snapshot_key = None
        self._ensure_heartbeat_subscriptions()
        self.timer = node.create_timer(1.0 / self.publish_rate_hz, self.publish_status)
        self.publish_status()

    def _ensure_heartbeat_subscriptions(self) -> None:
        for topic in self.monitored_topics:
            if topic not in self.subscriptions:
                self._subscribe_topic(topic)

    def _subscribe_topic(self, topic: str) -> None:
        topic_type = _topic_type_name(self.node, topic)
        if topic_type is None:
            return
        message_type = _import_message_type(topic_type)
        if message_type is None:
            return

        def _callback(msg, topic_name=topic, topic_type_name=topic_type):
            self.heartbeat.mark_received(
                topic_name,
                timestamp=self.node.get_clock().now().nanoseconds / 1e9,
                topic_type=topic_type_name,
            )

        self.subscriptions[topic] = self.node.create_subscription(message_type, topic, _callback, 10)

    def publish_status(self) -> None:
        self._ensure_heartbeat_subscriptions()
        graph = self._read_topology_graph()
        now = self.node.get_clock().now().nanoseconds / 1e9
        flow_status = self.heartbeat.summarize(graph, now=now, active_age_s=self.active_age_s)
        graph_payload = json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True)
        flow_payload = json.dumps(flow_status, ensure_ascii=False, sort_keys=True)
        snapshot_key = (graph_payload, flow_payload)
        if snapshot_key == self._last_snapshot_key:
            return
        self._last_snapshot_key = snapshot_key
        self.topology_publisher.publish(self.string_msg_type(data=graph_payload))
        self.flow_publisher.publish(self.string_msg_type(data=flow_payload))

    def _read_topology_graph(self):
        endpoints = []
        for topic, _ in self.node.get_topic_names_and_types():
            for endpoint_info in self.node.get_publishers_info_by_topic(topic):
                endpoints.append(
                    TopicEndpoint(
                        topic=topic,
                        node=_endpoint_node_name(endpoint_info),
                        direction="publisher",
                    )
                )
            for endpoint_info in self.node.get_subscriptions_info_by_topic(topic):
                endpoints.append(
                    TopicEndpoint(
                        topic=topic,
                        node=_endpoint_node_name(endpoint_info),
                        direction="subscriber",
                    )
                )
        return build_topology_graph(endpoints)


def _declare_parameters(node) -> None:
    node.declare_parameter("publish_rate_hz", 2.0)
    node.declare_parameter("active_age_s", 2.0)
    node.declare_parameter("monitored_topics", "")


def _parameter_value(node, name: str, default):
    parameter = node.get_parameter(name)
    value = getattr(parameter, "value", None)
    return default if value is None else value


def _parameter_list(node, name: str, default):
    value = _parameter_value(node, name, default)
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return list(default)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return [value]


def _topic_type_name(node, topic: str):
    infos = node.get_publishers_info_by_topic(topic)
    if infos:
        topic_type = getattr(infos[0], "topic_type", None)
        if topic_type:
            return topic_type
    infos = node.get_subscriptions_info_by_topic(topic)
    if infos:
        topic_type = getattr(infos[0], "topic_type", None)
        if topic_type:
            return topic_type
    return None


def _import_message_type(type_name: str):
    try:
        package_name, _, message_name = type_name.partition("/msg/")
        if not message_name:
            return None
        module = __import__(f"{package_name}.msg", fromlist=[message_name])
        return getattr(module, message_name)
    except Exception:
        return None


def _endpoint_node_name(endpoint_info) -> str:
    name = str(getattr(endpoint_info, "node_name", ""))
    namespace = str(getattr(endpoint_info, "node_namespace", ""))
    if not namespace or namespace == "/":
        return name if name.startswith("/") else f"/{name}"
    return f"{namespace.rstrip('/')}/{name.lstrip('/')}"
