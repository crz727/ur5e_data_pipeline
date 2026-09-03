"""ROS2 node entry point for the read-only Web dashboard."""

import threading

from data_collection_pkg.visualization.capture_manager import CaptureManager
from data_collection_pkg.visualization.web_dashboard import (
    DASHBOARD_CAMERAS,
    DashboardStateStore,
    create_dashboard_app,
)


DASHBOARD_TOPIC_SOURCES = {
    "/data_collection/topology_graph": "topology_graph",
    "/data_collection/flow_status": "flow_status",
    "/data_collection/quality_status": "quality_status",
    "/data_collection/drop_reason": "drop_reason",
    "/data_collection/replay/status": "replay_status",
}

DASHBOARD_CAMERA_TOPICS = {
    "external": "/camera2/scene_camera/color/image_raw/compressed",
    "wrist": "/camera1/wrist_camera/color/image_raw/compressed",
}

DASHBOARD_TELEMETRY_TOPICS = {
    "joint_states": "/joint_states",
    "gripper": "/robotiq_2f_gripper/joint_states",
    "end_effector_pose": "/tcp_pose_broadcaster/pose",
}


def start_dashboard_server(app, host: str, port: int):
    """Start a controllable Werkzeug server and return it with its thread."""
    from werkzeug.serving import make_server

    server = make_server(host, int(port), app, threaded=True)
    thread = threading.Thread(
        target=server.serve_forever,
        name="data_collection_dashboard_http",
        daemon=True,
    )
    thread.start()
    return server, thread


def stop_dashboard_server(server, thread) -> None:
    """Stop the HTTP server and wait for its worker thread to exit."""
    server.shutdown()
    server.server_close()
    thread.join(timeout=5.0)


def web_dashboard_node_main(args=None):
    """Start the ROS2-backed read-only Web dashboard."""
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from sensor_msgs.msg import JointState
    from sensor_msgs.msg import CompressedImage
    from std_msgs.msg import String

    rclpy.init(args=args)
    server = None
    server_thread = None
    capture_manager = None
    try:
        node = rclpy.create_node("data_collection_web_dashboard")
        _declare_parameters(node)
        store = DashboardStateStore()
        adapter = WebDashboardNodeAdapter(
            node=node,
            string_msg_type=String,
            compressed_image_msg_type=CompressedImage,
            store=store,
            camera_topics={
                "external": str(_parameter_value(
                    node,
                    "external_camera_topic",
                    DASHBOARD_CAMERA_TOPICS["external"],
                )),
                "wrist": str(_parameter_value(
                    node,
                    "wrist_camera_topic",
                    DASHBOARD_CAMERA_TOPICS["wrist"],
                )),
            },
            joint_state_msg_type=JointState,
            pose_msg_type=PoseStamped,
            telemetry_topics={
                "joint_states": str(_parameter_value(
                    node,
                    "joint_state_topic",
                    DASHBOARD_TELEMETRY_TOPICS["joint_states"],
                )),
                "gripper": str(_parameter_value(
                    node,
                    "gripper_state_topic",
                    DASHBOARD_TELEMETRY_TOPICS["gripper"],
                )),
                "end_effector_pose": str(_parameter_value(
                    node,
                    "end_effector_pose_topic",
                    DASHBOARD_TELEMETRY_TOPICS["end_effector_pose"],
                )),
            },
        )
        host = str(_parameter_value(node, "host", "0.0.0.0"))
        port = int(_parameter_value(node, "port", 8765))
        capture_root = str(_parameter_value(node, "capture_root", "~/ur5e_ws/datasets/ui_capture"))
        enable_capture_controls = bool(_parameter_value(node, "enable_capture_controls", True))
        capture_manager = (
            CaptureManager(root=capture_root)
            if enable_capture_controls
            else None
        )
        app = create_dashboard_app(store, capture_manager=capture_manager)
        try:
            server, server_thread = start_dashboard_server(app, host, port)
        except OSError as exc:
            node.get_logger().error(
                f"Could not bind dashboard to {host}:{port}: {exc}"
            )
            return
        node.get_logger().info(
            f"data_collection Web dashboard started on http://{host}:{port}"
        )
        rclpy.spin(node)
    finally:
        if capture_manager is not None:
            capture_manager.close()
        if server is not None and server_thread is not None:
            stop_dashboard_server(server, server_thread)
        rclpy.shutdown()


class WebDashboardNodeAdapter:
    """Subscribe to ROS2 JSON status topics and update the dashboard store."""

    def __init__(
        self,
        *,
        node,
        string_msg_type,
        compressed_image_msg_type=None,
        store: DashboardStateStore,
        camera_topics=None,
        joint_state_msg_type=None,
        pose_msg_type=None,
        telemetry_topics=None,
    ) -> None:
        self.node = node
        self.string_msg_type = string_msg_type
        self.store = store
        self.subscriptions = []
        for topic, source in DASHBOARD_TOPIC_SOURCES.items():
            self.subscriptions.append(
                node.create_subscription(
                    string_msg_type,
                    topic,
                    self._callback_for(source),
                    10,
                )
            )
        self.camera_topics = dict(camera_topics or DASHBOARD_CAMERA_TOPICS)
        if compressed_image_msg_type is not None:
            for camera in DASHBOARD_CAMERAS:
                self.subscriptions.append(
                    node.create_subscription(
                        compressed_image_msg_type,
                        self.camera_topics[camera],
                        self._camera_callback_for(camera),
                        10,
                    )
                )
        self.telemetry_topics = dict(telemetry_topics or DASHBOARD_TELEMETRY_TOPICS)
        if joint_state_msg_type is not None:
            self.subscriptions.append(
                node.create_subscription(
                    joint_state_msg_type,
                    self.telemetry_topics["joint_states"],
                    self._joint_state_callback,
                    10,
                )
            )
            self.subscriptions.append(
                node.create_subscription(
                    joint_state_msg_type,
                    self.telemetry_topics["gripper"],
                    self._gripper_callback,
                    10,
                )
            )
        if pose_msg_type is not None:
            self.subscriptions.append(
                node.create_subscription(
                    pose_msg_type,
                    self.telemetry_topics["end_effector_pose"],
                    self._pose_callback,
                    10,
                )
            )

    def _callback_for(self, source: str):
        def _callback(msg) -> None:
            timestamp = self.node.get_clock().now().nanoseconds / 1e9
            self.store.update_json(source, msg.data, timestamp=timestamp)

        return _callback

    def _camera_callback_for(self, camera: str):
        def _callback(msg) -> None:
            timestamp = self.node.get_clock().now().nanoseconds / 1e9
            codec = _compressed_codec(getattr(msg, "format", "jpeg"))
            self.store.update_image(
                camera,
                bytes(msg.data),
                codec=codec or "jpeg",
                timestamp=timestamp,
            )

        return _callback

    def _joint_state_callback(self, msg) -> None:
        self.store.update_telemetry(
            {
                "joint_names": list(getattr(msg, "name", ()) or ()),
                "qpos": _numbers(getattr(msg, "position", ())),
                "qvel": _numbers(getattr(msg, "velocity", ())),
                "effort": _numbers(getattr(msg, "effort", ())),
            },
            timestamp=self._timestamp(),
        )

    def _gripper_callback(self, msg) -> None:
        positions = _numbers(getattr(msg, "position", ()))
        if positions:
            self.store.update_telemetry(
                {"gripper": positions[0]},
                timestamp=self._timestamp(),
            )

    def _pose_callback(self, msg) -> None:
        pose = getattr(msg, "pose", msg)
        position = getattr(pose, "position", None)
        orientation = getattr(pose, "orientation", None)
        if position is None or orientation is None:
            return
        self.store.update_telemetry(
            {
                "ee_pose": [
                    float(getattr(position, "x", 0.0)),
                    float(getattr(position, "y", 0.0)),
                    float(getattr(position, "z", 0.0)),
                    float(getattr(orientation, "x", 0.0)),
                    float(getattr(orientation, "y", 0.0)),
                    float(getattr(orientation, "z", 0.0)),
                    float(getattr(orientation, "w", 1.0)),
                ],
            },
            timestamp=self._timestamp(),
        )

    def _timestamp(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1e9


def _declare_parameters(node) -> None:
    node.declare_parameter("host", "0.0.0.0")
    node.declare_parameter("port", 8765)
    node.declare_parameter("capture_root", "~/ur5e_ws/datasets/ui_capture")
    node.declare_parameter("enable_capture_controls", True)
    node.declare_parameter("external_camera_topic", DASHBOARD_CAMERA_TOPICS["external"])
    node.declare_parameter("wrist_camera_topic", DASHBOARD_CAMERA_TOPICS["wrist"])
    node.declare_parameter("joint_state_topic", DASHBOARD_TELEMETRY_TOPICS["joint_states"])
    node.declare_parameter("gripper_state_topic", DASHBOARD_TELEMETRY_TOPICS["gripper"])
    node.declare_parameter("end_effector_pose_topic", DASHBOARD_TELEMETRY_TOPICS["end_effector_pose"])


def _parameter_value(node, name: str, default):
    parameter = node.get_parameter(name)
    value = getattr(parameter, "value", None)
    return default if value is None else value


def _compressed_codec(image_format: str):
    normalized = str(image_format or "").lower()
    if "jpeg" in normalized or "jpg" in normalized:
        return "jpeg"
    if "png" in normalized:
        return "png"
    return None


def _numbers(values) -> list:
    return [float(value) for value in (values or ())]
