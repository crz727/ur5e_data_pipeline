"""ROS2 entry point for URSim plus RViz replay visualization."""

import json

from data_collection_pkg.action_replay.replay_topics import REPLAY_TOPICS


def ursim_rviz_replay_adapter_node_main(args=None):
    """Start the URSim/RViz replay adapter node.

    The adapter boundary is simulation-only by default. It bridges
    `/data_collection/replay/...` streams to URSim-safe control interfaces and
    RViz marker topics without publishing to real robot execution topics.
    """
    import rclpy
    from geometry_msgs.msg import Point
    from std_msgs.msg import String
    from visualization_msgs.msg import Marker

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("ursim_rviz_replay_adapter")
        _declare_parameters(node)
        adapter = UrsimRvizReplayAdapter(
            node=node,
            string_msg_type=String,
            marker_msg_type=Marker,
            point_msg_type=Point,
            sim_command_topic=_parameter_value(
                node,
                "sim_command_topic",
                "/ur_control/sim/replay_command",
            ),
            frame_id=_parameter_value(node, "frame_id", "base"),
        )
        node.get_logger().info(
            "URSim/RViz replay adapter started "
            f"sim_command_topic={adapter.sim_command_topic}"
        )
        rclpy.spin(node)
    finally:
        rclpy.shutdown()


class UrsimRvizReplayAdapter:
    """Bridge replay actions to URSim-safe commands and RViz markers."""

    def __init__(
        self,
        *,
        node,
        string_msg_type,
        marker_msg_type,
        point_msg_type,
        sim_command_topic: str,
        frame_id: str,
    ) -> None:
        self.node = node
        self.string_msg_type = string_msg_type
        self.marker_msg_type = marker_msg_type
        self.point_msg_type = point_msg_type
        self.sim_command_topic = str(sim_command_topic)
        self.frame_id = str(frame_id)
        self.path_points = []
        self.sim_command_publisher = node.create_publisher(
            string_msg_type,
            self.sim_command_topic,
            10,
        )
        self.marker_publisher = node.create_publisher(
            marker_msg_type,
            REPLAY_TOPICS["marker"],
            10,
        )
        self.subscription = node.create_subscription(
            string_msg_type,
            REPLAY_TOPICS["action"],
            self.on_replay_action,
            10,
        )

    def on_replay_action(self, msg) -> None:
        """Forward one replay action to simulation and RViz."""
        try:
            event = json.loads(msg.data)
        except Exception as exc:
            self.node.get_logger().warning(f"invalid replay action JSON: {exc}")
            return
        self._publish_sim_command(event)
        point = self._extract_point(event)
        if point is not None:
            self.path_points.append(point)
            self._publish_path_marker(event)

    def _publish_sim_command(self, event: dict) -> None:
        command = {
            "execute_real": False,
            "target": "ursim",
            "action_schema": event.get("action_schema"),
            "frame_index": event.get("frame_index"),
            "timestamp": event.get("timestamp"),
            "action": event.get("action"),
        }
        self.sim_command_publisher.publish(
            self.string_msg_type(data=json.dumps(command))
        )

    def _extract_point(self, event: dict):
        action = event.get("action")
        schema = event.get("action_schema")
        if schema == "teleop_servo_l_pose" and isinstance(action, list) and len(action) >= 3:
            return tuple(float(value) for value in action[:3])
        observation = event.get("observation") or {}
        ee_pose = observation.get("ee_pose")
        if isinstance(ee_pose, list) and len(ee_pose) >= 3:
            return tuple(float(value) for value in ee_pose[:3])
        return None

    def _publish_path_marker(self, event: dict) -> None:
        marker = self.marker_msg_type()
        marker.header.frame_id = self.frame_id
        marker.ns = "data_collection_replay"
        marker.id = 0
        marker.type = self.marker_msg_type.LINE_STRIP
        marker.action = self.marker_msg_type.ADD
        marker.scale.x = 0.01
        marker.color.r = 0.1
        marker.color.g = 0.7
        marker.color.b = 1.0
        marker.color.a = 1.0
        marker.points = [
            self.point_msg_type(x=x, y=y, z=z)
            for x, y, z in self.path_points
        ]
        self.marker_publisher.publish(marker)


def _declare_parameters(node) -> None:
    node.declare_parameter("sim_command_topic", "/ur_control/sim/replay_command")
    node.declare_parameter("frame_id", "base")


def _parameter_value(node, name: str, default):
    parameter = node.get_parameter(name)
    value = getattr(parameter, "value", None)
    return default if value is None else value
