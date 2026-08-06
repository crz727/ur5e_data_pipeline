"""Duck-typed ROS2 message adapters for teleop collection samples."""

import json

from data_collection_pkg.ros_capture.synchronizer import Sample
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


def joint_state_sample(msg, *, timestamp: float) -> Sample:
    """Convert a JointState-like message into a sample."""
    return Sample(
        topic=TELEOP_TOPICS["joint_states"],
        timestamp=float(timestamp),
        payload={
            "joint_names": [str(name) for name in _field(msg, "name", default=()) or ()],
            "positions": _values(_field(msg, "position", "positions")),
            "velocities": _values(_field(msg, "velocity", "velocities"), default=[]),
            "efforts": _values(_field(msg, "effort", "efforts"), default=[]),
        },
    )


def servo_l_command_sample(
    msg,
    *,
    timestamp: float,
    topic: str = TELEOP_TOPICS["servo_l_command"],
) -> Sample:
    """Convert a servoL command message into an action sample."""
    payload = _json_payload(msg)
    values = _field(payload, "action", "data", "servo_l_pose", "pose")
    sample_payload = {"action": dict(values) if isinstance(values, dict) else _values(values)}
    for name in ("source", "runtime_mode", "action_schema", "converted_from"):
        value = _field(payload, name, default=None)
        if value is not None:
            sample_payload[name] = str(value)
    return Sample(
        topic=topic,
        timestamp=float(timestamp),
        payload=sample_payload,
    )


def gripper_sample(
    msg,
    *,
    timestamp: float,
    topic: str = TELEOP_TOPICS["gripper_state"],
) -> Sample:
    """Convert a gripper state message into a gripper sample."""
    value = _field(msg, "data", "gripper", "position")
    values = _values(value)
    gripper = values[0] if isinstance(values, list) else float(values)
    return Sample(
        topic=topic,
        timestamp=float(timestamp),
        payload={"gripper": float(gripper)},
    )


def safety_sample(
    msg,
    *,
    timestamp: float,
    topic: str = TELEOP_TOPICS["safety_state"],
) -> Sample:
    """Convert a safety state message into a safety sample."""
    payload = _json_payload(msg)
    return Sample(
        topic=topic,
        timestamp=float(timestamp),
        payload={
            "software_estop": bool(_field(payload, "software_estop", default=False)),
            "protective_stop": bool(_field(payload, "protective_stop", default=False)),
            "gello_intervention": bool(_field(payload, "gello_intervention", default=False)),
        },
    )


def camera_sample(msg, *, topic: str, timestamp: float) -> Sample:
    """Convert an image-like message into a camera sample."""
    header = _field(msg, "header", default=None)
    frame_id = _field(header, "frame_id", default=None) if header is not None else None
    image_format = str(_field(msg, "format", default="raw") or "raw")
    payload = {
        "format": image_format,
        "data": _field(msg, "data", default=None),
        "frame_id": frame_id,
        "height": int(_field(msg, "height", default=0) or 0),
        "width": int(_field(msg, "width", default=0) or 0),
        "encoding": str(_field(msg, "encoding", default="")),
        "step": int(_field(msg, "step", default=0) or 0),
        "timestamp": float(timestamp),
    }
    # CompressedImage has only header, format, and data. Image messages may
    # carry a format-like field in test adapters, so dimensions disambiguate.
    if _is_compressed_image_message(msg, image_format):
        payload["transport"] = "compressed"
        payload["codec"] = _compressed_codec(image_format)
    return Sample(topic=topic, timestamp=float(timestamp), payload=payload)


def _is_compressed_image_message(msg, image_format: str) -> bool:
    """Return whether an image-like message contains encoded bytes."""
    if _compressed_codec(image_format) is None:
        return False
    return all(_field(msg, name, default=None) is None for name in (
        "height",
        "width",
        "encoding",
        "step",
    ))


def _compressed_codec(image_format: str):
    normalized = str(image_format or "").lower()
    if "jpeg" in normalized or "jpg" in normalized:
        return "jpeg"
    if "png" in normalized:
        return "png"
    return None


def end_effector_pose_sample(
    msg,
    *,
    timestamp: float,
    topic: str = TELEOP_TOPICS["end_effector_pose"],
) -> Sample:
    """Convert a PoseStamped-like tool pose message into an end-effector sample."""
    header = _field(msg, "header", default=None)
    frame_id = _field(header, "frame_id", default="base") if header is not None else "base"
    pose = _field(msg, "pose", default=msg)
    position = _field(pose, "position", default={})
    orientation = _field(pose, "orientation", default={})
    values = [
        _field(position, "x", default=0.0),
        _field(position, "y", default=0.0),
        _field(position, "z", default=0.0),
        _field(orientation, "x", "qx", default=0.0),
        _field(orientation, "y", "qy", default=0.0),
        _field(orientation, "z", "qz", default=0.0),
        _field(orientation, "w", "qw", default=1.0),
    ]
    return Sample(
        topic=topic,
        timestamp=float(timestamp),
        payload={
            "frame_id": str(frame_id),
            "child_frame_id": str(_field(msg, "child_frame_id", default="tool0")),
            "pose": [float(value) for value in values],
        },
    )


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


def _values(value, default=None):
    if value is None:
        return [] if default is None else default
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in value]
