"""Read-only ROS2 hardware interface verification for UR5e data capture."""

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class HardwareInterfaceReport:
    """Mutable collection of hardware interface check results."""

    checks: dict = field(default_factory=dict)

    def set_check(self, name: str, ok: bool, *, reason: str = "", details: Mapping[str, Any] = None) -> None:
        item = {"name": str(name), "ok": bool(ok)}
        if reason:
            item["reason"] = str(reason)
        if details:
            item["details"] = dict(details)
        self.checks[str(name)] = item

    def to_dict(self, *, required=()) -> dict:
        required_names = tuple(required)
        ok = all(self.checks.get(name, {"ok": False})["ok"] for name in required_names)
        return {
            "ok": ok,
            "checks": [self.checks[name] for name in sorted(self.checks)],
        }


def check_joint_state(msg) -> dict:
    """Validate a JointState-like message for UR5e recording."""
    positions = _values(_field(msg, "position", "positions", default=[]))
    if len(positions) != 6:
        return _result(False, "position must contain 6 joints", joint_count=len(positions))
    for name in ("position", "velocity", "effort"):
        values = _values(_field(msg, name, f"{name}s", default=[]))
        if values and not _all_finite(values):
            return _result(False, f"{name} contains non-finite values")
    return _result(True, joint_count=len(positions))


def check_gripper_state(msg) -> dict:
    """Validate and normalize a Robotiq-like gripper state message."""
    for name in ("gripper", "position", "data", "gPO"):
        value = _field(msg, name, default=None)
        if value is None:
            continue
        numeric = _first_numeric(value)
        if numeric is None or not math.isfinite(numeric):
            return _result(False, f"{name} is not finite", field=name)
        gripper = _normalize_gripper(numeric, raw_robotiq=(name == "gPO"))
        if not 0.0 <= gripper <= 1.0:
            return _result(False, f"{name} is outside normalized range", field=name, gripper=gripper)
        return _result(True, field=name, gripper=gripper)
    return _result(False, "no supported gripper field found")


def check_image(msg) -> dict:
    """Validate a raw or compressed ROS image-like message."""
    image_format = str(_field(msg, "format", default="") or "").lower()
    data = _field(msg, "data", default=None)
    if ("jpeg" in image_format or "jpg" in image_format or "png" in image_format):
        if data is None or len(data) == 0:
            return _result(False, "compressed image data is empty")
        codec = "jpeg" if "jpeg" in image_format or "jpg" in image_format else "png"
        return _result(True, codec=codec, byte_length=len(data))
    width = int(_field(msg, "width", default=0) or 0)
    height = int(_field(msg, "height", default=0) or 0)
    if width <= 0 or height <= 0:
        return _result(False, "image dimensions are missing", width=width, height=height)
    if data is None or len(data) == 0:
        return _result(False, "image data is empty", width=width, height=height)
    return _result(True, width=width, height=height, encoding=str(_field(msg, "encoding", default="")))


def check_safety_state(msg) -> dict:
    """Validate a safety state message is inactive."""
    payload = _json_payload(msg)
    active_fields = []
    for name in ("software_estop", "protective_stop", "gello_intervention"):
        if bool(_field(payload, name, default=False)):
            active_fields.append(name)
    if active_fields:
        return _result(False, "safety state is active", active_fields=active_fields)
    return _result(True)


class HardwareInterfaceCheckNode:
    """Subscribe to hardware topics for a fixed duration and print a JSON report."""

    def __init__(self, node) -> None:
        from sensor_msgs.msg import CompressedImage, JointState
        from std_msgs.msg import String
        from tf2_msgs.msg import TFMessage

        self.node = node
        self.report = HardwareInterfaceReport()
        self.required = ["joint_states", "robotiq_state"]
        self.timeout_s = float(_parameter(node, "timeout_s", 3.0))
        self.base_frame = str(_parameter(node, "base_frame", "base_link"))
        self.tool_frame = str(_parameter(node, "tool_frame", "tool0"))
        self.gripper_topic = str(_parameter(node, "gripper_state_topic", "/gripper/state"))
        gripper_msg_type = str(_parameter(node, "gripper_state_msg_type", "std_msgs.msg:Float64MultiArray"))
        self.require_cameras = _as_bool(_parameter(node, "require_cameras", False))
        self.external_camera_topic = str(_parameter(
            node,
            "external_camera_topic",
            "/camera2/scene_camera/color/image_raw/compressed",
        ))
        self.wrist_camera_topic = str(_parameter(
            node,
            "wrist_camera_topic",
            "/camera1/wrist_camera/color/image_raw/compressed",
        ))
        self.safety_topic = str(_parameter(node, "safety_topic", "/safety/state"))

        gripper_type = _load_message_type(gripper_msg_type)
        node.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)
        node.create_subscription(gripper_type, self.gripper_topic, self._on_gripper, 10)
        node.create_subscription(TFMessage, "/tf", lambda _msg: self.report.set_check("tf", True), 10)
        node.create_subscription(TFMessage, "/tf_static", lambda _msg: self.report.set_check("tf_static", True), 10)
        node.create_subscription(String, self.safety_topic, self._on_safety, 10)
        node.create_subscription(CompressedImage, self.external_camera_topic, self._on_external_camera, 10)
        node.create_subscription(CompressedImage, self.wrist_camera_topic, self._on_wrist_camera, 10)

        if self.require_cameras:
            self.required.extend(["external_camera", "wrist_camera"])

        self._setup_tf_lookup()
        node.create_timer(self.timeout_s, self._finish)

    def _setup_tf_lookup(self) -> None:
        try:
            import tf2_ros

            self.tf_buffer = tf2_ros.Buffer()
            self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self.node)
        except Exception as exc:
            self.tf_buffer = None
            self.report.set_check("tf_lookup", False, reason=f"tf listener unavailable: {exc}")

    def _on_joint_states(self, msg) -> None:
        self._store("joint_states", check_joint_state(msg))

    def _on_gripper(self, msg) -> None:
        self._store("robotiq_state", check_gripper_state(msg))

    def _on_external_camera(self, msg) -> None:
        self._store("external_camera", check_image(msg))

    def _on_wrist_camera(self, msg) -> None:
        self._store("wrist_camera", check_image(msg))

    def _on_safety(self, msg) -> None:
        self._store("safety_state", check_safety_state(msg))

    def _store(self, name: str, result: Mapping[str, Any]) -> None:
        self.report.set_check(
            name,
            bool(result["ok"]),
            reason=str(result.get("reason", "")),
            details=result.get("details", {}),
        )

    def _finish(self) -> None:
        self._check_missing_topics()
        self._check_tf_transform()
        print(json.dumps(self.report.to_dict(required=self.required), indent=2, sort_keys=True))
        raise SystemExit(0)

    def _check_missing_topics(self) -> None:
        for name in self.required:
            if name not in self.report.checks:
                self.report.set_check(name, False, reason="no message received before timeout")

    def _check_tf_transform(self) -> None:
        if self.tf_buffer is None:
            return
        try:
            self.tf_buffer.lookup_transform(self.base_frame, self.tool_frame, _tf_time(), timeout=_tf_duration(0.2))
        except Exception as exc:
            self.report.set_check("tf_lookup", False, reason=f"{self.base_frame}->{self.tool_frame} unavailable: {exc}")
            return
        self.report.set_check("tf_lookup", True, details={"base_frame": self.base_frame, "tool_frame": self.tool_frame})


def hardware_interface_check_node_main(args=None):
    """Run the read-only hardware interface check node."""
    import rclpy

    rclpy.init(args=args)
    node = rclpy.create_node("hardware_interface_check")
    checker = HardwareInterfaceCheckNode(node)
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return checker.report.to_dict(required=checker.required)


def main(args=None):
    hardware_interface_check_node_main(args=args)


def _parameter(node, name: str, default):
    node.declare_parameter(name, default)
    return node.get_parameter(name).value


def _load_message_type(type_name: str):
    module_name, class_name = _message_type_parts(type_name)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)


def _message_type_parts(type_name: str):
    value = str(type_name)
    if ":" in value:
        return tuple(value.split(":", 1))
    parts = value.split("/")
    if len(parts) == 3 and parts[1] == "msg":
        return f"{parts[0]}.msg", parts[2]
    raise ValueError(f"unsupported ROS2 message type format: {type_name}")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _tf_time():
    from rclpy.time import Time

    return Time()


def _tf_duration(seconds: float):
    from rclpy.duration import Duration

    return Duration(seconds=seconds)


def _result(ok: bool, reason: str = "", **details) -> dict:
    result = {"ok": bool(ok), "details": dict(details)}
    if reason:
        result["reason"] = reason
    return result


def _field(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _json_payload(msg):
    data = _field(msg, "data", default=None)
    if isinstance(data, str):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return msg
        if isinstance(payload, dict):
            return payload
    return msg


def _values(value):
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in value]


def _first_numeric(value):
    try:
        return _values(value)[0]
    except (TypeError, ValueError, IndexError):
        return None


def _all_finite(values) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _normalize_gripper(value: float, *, raw_robotiq: bool) -> float:
    if raw_robotiq:
        return float(value) / 255.0
    if value > 1.0:
        return float(value) / 255.0
    return float(value)
