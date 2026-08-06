"""Real-time and offline quality checks for data collection."""

import base64
import binascii
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from data_collection_pkg.dataset.schemas import get_schema


@dataclass(frozen=True)
class QualityConfig:
    """Configurable quality thresholds."""

    profile: str = "basic"
    required_cameras: Tuple[str, ...] = ()
    max_message_age_s: Optional[float] = None
    reject_safety_active: bool = True
    require_safety_fields: bool = False
    max_sync_delta_s: Optional[float] = None
    image_shapes: Mapping[str, Tuple[int, int]] = field(default_factory=dict)
    decode_images: bool = False
    qpos_limits: Optional[Tuple[Tuple[float, float], ...]] = None
    qvel_abs_limit: Optional[float] = None
    effort_abs_limit: Optional[float] = None
    gripper_range: Optional[Tuple[float, float]] = None
    action_ranges: Mapping[str, Tuple[Tuple[float, float], ...]] = field(default_factory=dict)
    max_action_step: Optional[Tuple[float, ...]] = None
    target_fps: Optional[float] = None
    fps_tolerance_ratio: float = 0.2
    fps_tolerance_s: Optional[float] = None
    min_frame_count: Optional[int] = None
    min_duration_s: Optional[float] = None
    require_replay_constructable: bool = False
    require_ee_pose: bool = False

    @classmethod
    def basic(cls, **kwargs: Any) -> "QualityConfig":
        """Return the default metadata/schema/safety validation profile."""
        return cls(profile="basic", **kwargs)

    @classmethod
    def trainable(cls, **kwargs: Any) -> "QualityConfig":
        """Return a stricter validation profile for trainable datasets."""
        defaults = {
            "profile": "trainable",
            "decode_images": True,
            "gripper_range": (0.0, 1.0),
            "require_safety_fields": False,
        }
        defaults.update(kwargs)
        return cls(**defaults)

    @classmethod
    def replay(cls, **kwargs: Any) -> "QualityConfig":
        """Return a validation profile for safe replay preparation."""
        defaults = {
            "profile": "replay",
            "require_replay_constructable": True,
        }
        defaults.update(kwargs)
        return cls(**defaults)


@dataclass(frozen=True)
class FrameQualityResult:
    """Result for one frame."""

    ok: bool
    drop_reasons: list


@dataclass(frozen=True)
class QualityReport:
    """Offline dataset quality report."""

    ok: bool
    episode_count: int
    frame_count: int
    issues: list
    profile: str
    checks: list


def check_frame(
    *,
    observation: Mapping[str, Any],
    action: Any,
    schema_name: str,
    config: Optional[QualityConfig] = None,
    now: Optional[float] = None,
    previous_timestamp: Optional[float] = None,
    previous_action: Optional[Any] = None,
) -> FrameQualityResult:
    """Validate one synchronized observation/action frame."""
    config = config or QualityConfig()
    schema = get_schema(schema_name)
    reasons = []
    timestamp = observation.get("timestamp")

    if not _finite_number(timestamp):
        reasons.append("timestamp_invalid")
    else:
        timestamp = float(timestamp)
        if previous_timestamp is not None and timestamp < float(previous_timestamp):
            reasons.append("timestamp_moved_backward")
        if now is not None and config.max_message_age_s is not None:
            if float(now) - timestamp > float(config.max_message_age_s):
                reasons.append("message_age_exceeded")

    state = _finite_vector_values(observation.get("state"), 7)
    if state is None:
        reasons.append("state_invalid")
    else:
        _check_state_ranges(observation, state, config, reasons)

    if schema.action_dim is None:
        if not isinstance(action, Mapping):
            reasons.append("action_mapping_required")
    elif not _finite_vector(action, schema.action_dim):
        reasons.append("action_dim_mismatch")
    else:
        action_values = _finite_vector_values(action, schema.action_dim)
        if action_values is not None:
            _check_action_ranges(schema_name, action_values, previous_action, config, reasons)

    if config.require_replay_constructable and not _replay_request_constructable(
        observation=observation,
        action=action,
        schema_name=schema_name,
    ):
        reasons.append("replay_request_unconstructable")

    ee_pose = observation.get("ee_pose")
    if config.require_ee_pose and ee_pose is None:
        reasons.append("ee_pose_missing")
    elif ee_pose is not None and not _finite_vector(ee_pose, 7):
        reasons.append("ee_pose_invalid")

    images = observation.get("images") or {}
    if images and not isinstance(images, Mapping):
        reasons.append("images_invalid")
        images = {}
    for camera_name in config.required_cameras:
        if camera_name not in images:
            reasons.append(f"missing_camera:{camera_name}")
    _check_images(timestamp, images, config, reasons)

    if config.reject_safety_active:
        safety = observation.get("safety") or {}
        if isinstance(safety, Mapping):
            for name in ("software_estop", "protective_stop", "gello_intervention"):
                if config.require_safety_fields and name not in safety:
                    reasons.append(f"safety_missing:{name}")
                if bool(safety.get(name, False)):
                    reasons.append(f"safety_active:{name}")
        else:
            reasons.append("safety_invalid")

    return FrameQualityResult(ok=not reasons, drop_reasons=reasons)


def check_dataset(dataset_dir: Path, config: Optional[QualityConfig] = None) -> QualityReport:
    """Validate one JSONL dataset directory."""
    config = config or QualityConfig()
    dataset_dir = Path(dataset_dir)
    issues = []
    metadata = _read_metadata(dataset_dir, issues)
    frame_count = 0

    for episode in metadata:
        schema_name = episode.get("action_schema")
        data_path = dataset_dir / str(episode.get("data_path", ""))
        if not data_path.exists():
            issues.append(f"episode {episode.get('episode_index')}: missing data file")
            continue
        previous_timestamp = None
        previous_action = None
        episode_timestamps = []
        episode_frame_count = 0
        with data_path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream):
                if not line.strip():
                    continue
                frame_count += 1
                episode_frame_count += 1
                frame = json.loads(line)
                result = check_frame(
                    observation=frame.get("observation", {}),
                    action=frame.get("action"),
                    schema_name=schema_name,
                    config=config,
                    previous_timestamp=previous_timestamp,
                    previous_action=previous_action,
                )
                frame_timestamp = frame.get("timestamp")
                observation_timestamp = frame.get("observation", {}).get("timestamp")
                if _finite_number(observation_timestamp):
                    episode_timestamps.append(float(observation_timestamp))
                if _frame_dt_out_of_range(previous_timestamp, frame_timestamp, config):
                    result.drop_reasons.append("frame_dt_out_of_range")
                previous_timestamp = frame_timestamp
                previous_action = frame.get("action")
                for reason in result.drop_reasons:
                    frame_index = frame.get("frame_index", line_number)
                    issues.append(f"{data_path.name} frame {frame_index}: {reason}")
        _check_episode_summary(episode, episode_frame_count, episode_timestamps, config, issues)

    return QualityReport(
        ok=not issues,
        episode_count=len(metadata),
        frame_count=frame_count,
        issues=issues,
        profile=config.profile,
        checks=quality_check_items(config),
    )


def quality_check_items(config: Optional[QualityConfig] = None) -> list:
    """Return the concrete quality checks enabled by one config."""
    config = config or QualityConfig()
    checks = [
        _check_item("metadata_file_exists", "dataset"),
        _check_item("episode_data_file_exists", "episode"),
        _check_item("timestamp_finite", "frame"),
        _check_item("timestamp_monotonic", "frame"),
        _check_item("state_vector_7d_finite", "frame"),
        _check_item("action_schema_dimension", "frame"),
        _check_item("safety_inactive", "frame"),
        _check_item("episode_frame_count_matches_metadata", "episode"),
    ]
    if config.max_message_age_s is not None:
        checks.append(_check_item(
            "message_age",
            "frame",
            threshold={"max_message_age_s": config.max_message_age_s},
        ))
    if config.required_cameras:
        checks.append(_check_item(
            "required_cameras_present",
            "frame",
            threshold={"required_cameras": list(config.required_cameras)},
        ))
    if config.max_sync_delta_s is not None:
        checks.append(_check_item(
            "camera_frame_sync_delta",
            "frame",
            threshold={"max_sync_delta_s": config.max_sync_delta_s},
        ))
    if config.decode_images:
        checks.append(_check_item("image_decodable", "frame"))
    if config.image_shapes:
        checks.append(_check_item(
            "image_shape_matches_declaration",
            "frame",
            threshold={"image_shapes": _json_safe_mapping(config.image_shapes)},
        ))
    if config.qpos_limits is not None:
        checks.append(_check_item("qpos_limits", "frame"))
    if config.qvel_abs_limit is not None:
        checks.append(_check_item(
            "qvel_abs_limit",
            "frame",
            threshold={"qvel_abs_limit": config.qvel_abs_limit},
        ))
    if config.effort_abs_limit is not None:
        checks.append(_check_item(
            "effort_abs_limit",
            "frame",
            threshold={"effort_abs_limit": config.effort_abs_limit},
        ))
    if config.gripper_range is not None:
        checks.append(_check_item(
            "gripper_range",
            "frame",
            threshold={"gripper_range": list(config.gripper_range)},
        ))
    if config.action_ranges:
        checks.append(_check_item(
            "action_ranges",
            "frame",
            threshold={"schemas": sorted(config.action_ranges)},
        ))
    if config.max_action_step is not None:
        checks.append(_check_item("action_step_delta", "frame"))
    if config.target_fps is not None:
        checks.append(_check_item(
            "target_frame_rate",
            "frame",
            threshold={
                "target_fps": config.target_fps,
                "fps_tolerance_ratio": config.fps_tolerance_ratio,
                "fps_tolerance_s": config.fps_tolerance_s,
            },
        ))
    if config.min_frame_count is not None:
        checks.append(_check_item(
            "episode_min_frame_count",
            "episode",
            threshold={"min_frame_count": config.min_frame_count},
        ))
    if config.min_duration_s is not None:
        checks.append(_check_item(
            "episode_min_duration",
            "episode",
            threshold={"min_duration_s": config.min_duration_s},
        ))
    if config.require_safety_fields:
        checks.append(_check_item("safety_fields_present", "frame"))
    if config.require_replay_constructable:
        checks.append(_check_item("replay_request_constructable", "frame"))
    if config.require_ee_pose:
        checks.append(_check_item("ee_pose_present", "frame"))
        checks.append(_check_item("ee_pose_7d_finite", "frame"))
    return checks


def _check_item(name: str, scope: str, *, threshold: Optional[Mapping[str, Any]] = None) -> dict:
    item = {
        "name": name,
        "scope": scope,
        "enabled": True,
    }
    if threshold is not None:
        item["threshold"] = threshold
    return item


def _json_safe_mapping(value: Mapping[str, Any]) -> dict:
    return {
        key: list(item) if isinstance(item, tuple) else item
        for key, item in value.items()
    }


def _read_metadata(dataset_dir: Path, issues: list) -> list:
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    if not metadata_path.exists():
        issues.append("missing meta/episodes.jsonl")
        return []
    rows = []
    with metadata_path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _finite_vector(value: Any, size: int) -> bool:
    return _finite_vector_values(value, size) is not None


def _finite_vector_values(value: Any, size: int) -> Optional[list]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    if len(value) != size:
        return None
    if not all(_finite_number(item) for item in value):
        return None
    return [float(item) for item in value]


def _check_state_ranges(observation: Mapping[str, Any], state: list, config: QualityConfig, reasons: list) -> None:
    qpos = _finite_vector_values(observation.get("qpos"), 6) or state[:6]
    if config.qpos_limits is not None:
        for index, value in enumerate(qpos):
            if index >= len(config.qpos_limits):
                break
            low, high = config.qpos_limits[index]
            if value < low or value > high:
                reasons.append(f"qpos_range_exceeded:{index}")

    qvel = _finite_vector_values(observation.get("qvel"), 6)
    if qvel is not None and config.qvel_abs_limit is not None:
        for index, value in enumerate(qvel):
            if abs(value) > config.qvel_abs_limit:
                reasons.append(f"qvel_range_exceeded:{index}")

    effort = _finite_vector_values(observation.get("effort"), 6)
    if effort is not None and config.effort_abs_limit is not None:
        for index, value in enumerate(effort):
            if abs(value) > config.effort_abs_limit:
                reasons.append(f"effort_range_exceeded:{index}")

    gripper = observation.get("gripper", state[6])
    if config.gripper_range is not None and _finite_number(gripper):
        low, high = config.gripper_range
        if float(gripper) < low or float(gripper) > high:
            reasons.append("gripper_range_exceeded")


def _check_action_ranges(
    schema_name: str,
    action_values: list,
    previous_action: Optional[Any],
    config: QualityConfig,
    reasons: list,
) -> None:
    ranges = config.action_ranges.get(schema_name)
    if ranges is not None:
        for index, value in enumerate(action_values):
            if index >= len(ranges):
                break
            low, high = ranges[index]
            if value < low or value > high:
                reasons.append(f"action_range_exceeded:{index}")

    previous_values = _finite_vector_values(previous_action, len(action_values)) if previous_action is not None else None
    if previous_values is not None and config.max_action_step is not None:
        for index, (value, previous) in enumerate(zip(action_values, previous_values)):
            if index >= len(config.max_action_step):
                break
            if abs(value - previous) > config.max_action_step[index]:
                reasons.append(f"action_step_exceeded:{index}")


def _check_images(timestamp: Any, images: Mapping[str, Any], config: QualityConfig, reasons: list) -> None:
    camera_names = set(images)
    camera_names.update(config.image_shapes)
    for camera_name in sorted(camera_names):
        payload = images.get(camera_name)
        if not isinstance(payload, Mapping):
            if camera_name in images:
                reasons.append(f"image_invalid:{camera_name}")
            continue
        image_timestamp = payload.get("timestamp")
        if config.max_sync_delta_s is not None and _finite_number(timestamp) and _finite_number(image_timestamp):
            if abs(float(image_timestamp) - float(timestamp)) > float(config.max_sync_delta_s):
                reasons.append(f"sync_delta_exceeded:{camera_name}")

        expected_shape = config.image_shapes.get(camera_name)
        if expected_shape is not None:
            actual_shape = _image_shape(payload)
            if actual_shape != tuple(expected_shape):
                reasons.append(f"image_shape_mismatch:{camera_name}")

        if config.decode_images and camera_name in images and not _image_decodable(payload):
            reasons.append(f"image_decode_failed:{camera_name}")


def _image_shape(payload: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    height = payload.get("height")
    width = payload.get("width")
    if isinstance(height, int) and isinstance(width, int):
        return (height, width)
    image_bytes = _image_bytes(payload)
    if image_bytes is None:
        return None
    return _encoded_image_shape(image_bytes)


def _image_decodable(payload: Mapping[str, Any]) -> bool:
    if _raw_image_payload_present(payload):
        return True
    image_bytes = _image_bytes(payload)
    if image_bytes is None:
        return False
    return _encoded_image_shape(image_bytes) is not None


def _raw_image_payload_present(payload: Mapping[str, Any]) -> bool:
    height = payload.get("height")
    width = payload.get("width")
    data = payload.get("data")
    if not isinstance(height, int) or not isinstance(width, int):
        return False
    if height <= 0 or width <= 0:
        return False
    if payload.get("data_path") and int(payload.get("byte_length", 0) or 0) > 0:
        return True
    if data is None:
        return False
    try:
        return len(data) > 0
    except TypeError:
        return False


def _image_bytes(payload: Mapping[str, Any]) -> Optional[bytes]:
    for key in ("data", "base64", "jpeg", "png"):
        value = payload.get(key)
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            try:
                return base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                return None
    return None


def _encoded_image_shape(image_bytes: bytes) -> Optional[Tuple[int, int]]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        width, height = struct.unpack(">II", image_bytes[16:24])
        return (int(height), int(width))
    if image_bytes.startswith(b"\xff\xd8"):
        return _jpeg_shape(image_bytes)
    return None


def _jpeg_shape(image_bytes: bytes) -> Optional[Tuple[int, int]]:
    index = 2
    while index + 9 < len(image_bytes):
        if image_bytes[index] != 0xFF:
            index += 1
            continue
        marker = image_bytes[index + 1]
        index += 2
        if marker in (0xD8, 0xD9):
            continue
        if index + 2 > len(image_bytes):
            return None
        segment_length = int.from_bytes(image_bytes[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(image_bytes):
            return None
        if marker in (0xC0, 0xC2):
            height = int.from_bytes(image_bytes[index + 3:index + 5], "big")
            width = int.from_bytes(image_bytes[index + 5:index + 7], "big")
            return (height, width)
        index += segment_length
    return None


def _replay_request_constructable(*, observation: Mapping[str, Any], action: Any, schema_name: str) -> bool:
    try:
        schema = get_schema(schema_name)
    except KeyError:
        return False
    if not isinstance(observation, Mapping):
        return False
    if not _finite_number(observation.get("timestamp")):
        return False
    if schema.action_dim is None:
        return isinstance(action, Mapping)
    return _finite_vector(action, schema.action_dim)


def _frame_dt_out_of_range(previous_timestamp: Any, timestamp: Any, config: QualityConfig) -> bool:
    if previous_timestamp is None or config.target_fps is None:
        return False
    if not _finite_number(previous_timestamp) or not _finite_number(timestamp):
        return False
    expected_dt = 1.0 / float(config.target_fps)
    actual_dt = float(timestamp) - float(previous_timestamp)
    tolerance = config.fps_tolerance_s
    if tolerance is None:
        tolerance = expected_dt * float(config.fps_tolerance_ratio)
    return abs(actual_dt - expected_dt) > float(tolerance)


def _check_episode_summary(
    episode: Mapping[str, Any],
    episode_frame_count: int,
    timestamps: Sequence[float],
    config: QualityConfig,
    issues: list,
) -> None:
    episode_index = episode.get("episode_index")
    metadata_frame_count = episode.get("frame_count")
    if isinstance(metadata_frame_count, int) and metadata_frame_count != episode_frame_count:
        issues.append(f"episode {episode_index}: frame_count_mismatch:{metadata_frame_count}!={episode_frame_count}")
    if config.min_frame_count is not None and episode_frame_count < int(config.min_frame_count):
        issues.append(f"episode {episode_index}: frame_count_below_min:{episode_frame_count}<{int(config.min_frame_count)}")
    if config.min_duration_s is not None:
        duration = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0.0
        if duration < float(config.min_duration_s):
            issues.append(f"episode {episode_index}: duration_below_min:{duration:.6f}<{float(config.min_duration_s):.6f}")
