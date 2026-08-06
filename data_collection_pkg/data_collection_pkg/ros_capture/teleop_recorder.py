"""Teleoperation capture core for trainable servoL pose datasets."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.quality import QualityConfig, check_frame
from data_collection_pkg.dataset.schemas import get_schema
from data_collection_pkg.ros_capture.synchronizer import SyncedFrame


TELEOP_TOPICS = {
    "joint_states": "/joint_states",
    "servo_l_command": "/teleop/command",
    "gripper_state": "/gripper/state",
    "external_camera": "/camera2/scene_camera/color/image_raw/compressed",
    "wrist_camera": "/camera1/wrist_camera/color/image_raw/compressed",
    "safety_state": "/safety/state",
    "end_effector_pose": "/tool0/pose",
}


@dataclass(frozen=True)
class BuiltTeleopFrame:
    """Result of mapping one synchronized teleop frame."""

    ok: bool
    observation: Mapping[str, Any]
    action: Any
    metadata: Mapping[str, Any]
    drop_reasons: list


class TeleopFrameBuilder:
    """Map synchronized ROS2 topic samples into trainable action frames."""

    def __init__(
        self,
        *,
        required_cameras: Sequence[str] = (),
        quality_config: QualityConfig = None,
        source: str = "teleop",
        runtime_mode: str = "teleop",
        schema_name: str = "teleop_twist_gripper",
        action_topic: str = TELEOP_TOPICS["servo_l_command"],
        gripper_topic: str = TELEOP_TOPICS["gripper_state"],
        external_camera_topic: str = TELEOP_TOPICS["external_camera"],
        wrist_camera_topic: str = TELEOP_TOPICS["wrist_camera"],
        safety_state_topic: str = TELEOP_TOPICS["safety_state"],
        end_effector_pose_topic: str = TELEOP_TOPICS["end_effector_pose"],
    ) -> None:
        self.required_cameras = tuple(required_cameras)
        self.source = str(source)
        self.runtime_mode = str(runtime_mode)
        self.schema_name = str(schema_name)
        self.action_topic = str(action_topic)
        self.gripper_topic = str(gripper_topic)
        self.external_camera_topic = str(external_camera_topic)
        self.wrist_camera_topic = str(wrist_camera_topic)
        self.safety_state_topic = str(safety_state_topic)
        self.end_effector_pose_topic = str(end_effector_pose_topic)
        self.quality_config = quality_config or QualityConfig(
            required_cameras=tuple(required_cameras),
            max_message_age_s=None,
        )

    def build(self, synced_frame: SyncedFrame) -> BuiltTeleopFrame:
        """Build and validate one trainable teleop frame."""
        metadata = {
            "source": self.source,
            "runtime_mode": self.runtime_mode,
            "action_schema": self.schema_name,
            "converted_from": self.action_topic,
        }
        if not synced_frame.ok:
            return BuiltTeleopFrame(
                ok=False,
                observation={},
                action=None,
                metadata=metadata,
                drop_reasons=list(synced_frame.drop_reasons),
            )

        samples = synced_frame.samples
        joint_state = samples[TELEOP_TOPICS["joint_states"]].payload
        gripper_state = samples[self.gripper_topic].payload
        command = samples[self.action_topic].payload
        metadata.update({
            name: str(command[name])
            for name in ("source", "runtime_mode", "action_schema", "converted_from")
            if name in command
        })

        qpos = _vector(joint_state.get("positions"), 6, "positions")
        gripper = float(gripper_state.get("gripper", gripper_state.get("position", 0.0)))
        observation = {
            "timestamp": float(synced_frame.timestamp),
            "state": qpos + [gripper],
            "qpos": qpos,
            "qvel": _vector(joint_state.get("velocities", [0.0] * 6), 6, "velocities"),
            "effort": _vector(joint_state.get("efforts", [0.0] * 6), 6, "efforts"),
            "gripper": gripper,
            "images": self._images(samples),
            "safety": self._safety(samples),
            **self._end_effector_pose(samples),
        }
        action_value = command.get("action", command.get("servo_l_pose"))
        schema = get_schema(metadata["action_schema"])
        if schema.action_dim is None:
            action = dict(action_value) if isinstance(action_value, Mapping) else {"values": action_value}
        else:
            action = _vector(action_value, schema.action_dim, "servo_l_command")
        quality = check_frame(
            observation=observation,
            action=action,
            schema_name=metadata["action_schema"],
            config=self.quality_config,
        )

        return BuiltTeleopFrame(
            ok=quality.ok,
            observation=observation,
            action=action,
            metadata=metadata,
            drop_reasons=quality.drop_reasons,
        )

    def _images(self, samples: Mapping[str, Any]) -> dict:
        images = {}
        if self.external_camera_topic in samples:
            images["external"] = dict(samples[self.external_camera_topic].payload)
        if self.wrist_camera_topic in samples:
            images["wrist"] = dict(samples[self.wrist_camera_topic].payload)
        return images

    def _safety(self, samples: Mapping[str, Any]) -> dict:
        sample = samples.get(self.safety_state_topic)
        if sample is None:
            return {}
        return dict(sample.payload)

    def _end_effector_pose(self, samples: Mapping[str, Any]) -> dict:
        sample = samples.get(self.end_effector_pose_topic)
        if sample is None:
            return {}
        payload = dict(sample.payload)
        pose = _vector(payload.get("pose"), 7, "ee_pose")
        return {
            "ee_pose": pose,
            "tool_pose": {
                "frame_id": payload.get("frame_id", "base"),
                "child_frame_id": payload.get("child_frame_id", "tool0"),
                "pose": pose,
                "timestamp": float(sample.timestamp),
            },
        }


class TeleopJsonlRecorder:
    """Write accepted synchronized frames into a classified JSONL dataset."""

    def __init__(
        self,
        root: Path,
        *,
        task: str,
        required_cameras: Sequence[str] = (),
        source: str = "teleop",
        runtime_mode: str = "teleop",
        schema_name: str = "teleop_twist_gripper",
        action_topic: str = TELEOP_TOPICS["servo_l_command"],
        gripper_topic: str = TELEOP_TOPICS["gripper_state"],
        external_camera_topic: str = TELEOP_TOPICS["external_camera"],
        wrist_camera_topic: str = TELEOP_TOPICS["wrist_camera"],
        safety_state_topic: str = TELEOP_TOPICS["safety_state"],
        end_effector_pose_topic: str = TELEOP_TOPICS["end_effector_pose"],
    ) -> None:
        self.builder = TeleopFrameBuilder(
            required_cameras=required_cameras,
            source=source,
            runtime_mode=runtime_mode,
            schema_name=schema_name,
            action_topic=action_topic,
            gripper_topic=gripper_topic,
            external_camera_topic=external_camera_topic,
            wrist_camera_topic=wrist_camera_topic,
            safety_state_topic=safety_state_topic,
            end_effector_pose_topic=end_effector_pose_topic,
        )
        self.writer = JsonlDatasetWriter(
            Path(root),
            schema_name,
            task=task,
            source=source,
            runtime_mode=runtime_mode,
            converted_from=action_topic,
        )
        self.writer.start_episode()
        self.accepted_frames = 0
        self.dropped_frames = 0

    def record_synced_frame(self, synced_frame: SyncedFrame) -> BuiltTeleopFrame:
        """Validate and write one synchronized frame."""
        built = self.builder.build(synced_frame)
        if built.ok:
            self.writer.add_frame(built.observation, built.action, metadata=built.metadata)
            self.accepted_frames += 1
        else:
            self.dropped_frames += 1
        return built

    def close(self) -> dict:
        """Close the active episode and return a summary."""
        self.writer.close_episode()
        return {
            "dataset_dir": str(self.writer.dataset_dir),
            "accepted_frames": self.accepted_frames,
            "dropped_frames": self.dropped_frames,
        }


def _vector(value: Any, size: int, name: str) -> list:
    if value is None:
        raise ValueError(f"{name} must contain {size} values")
    values = [float(item) for item in value]
    if len(values) != size:
        raise ValueError(f"{name} must contain {size} values")
    return values
