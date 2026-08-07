"""Fixed-rate teleoperation demo capture for ACT-style qpos actions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.quality import QualityConfig, check_frame
from data_collection_pkg.ros_capture.synchronizer import Sample, SyncedFrame, TopicSynchronizer
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


FUTURE_JOINT_STATE_ACTION = "future_joint_state"
UR5E_JOINT_NAMES = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)


@dataclass(frozen=True)
class BuiltQposDemoFrame:
    """Result of mapping one fixed-rate demo sample into a qpos action frame."""

    ok: bool
    observation: Mapping[str, Any]
    action: Any
    metadata: Mapping[str, Any]
    drop_reasons: list


class QposDemoFrameBuilder:
    """Build ACT-style frames where action is the next sampled qpos+gripper state."""

    def __init__(
        self,
        *,
        required_cameras: Sequence[str] = (),
        quality_config: QualityConfig = None,
        source: str = "teleop",
        runtime_mode: str = "rtde_teleop",
        dataset_stage: str = "original",
        gripper_topic: str = TELEOP_TOPICS["gripper_state"],
        external_camera_topic: str = TELEOP_TOPICS["external_camera"],
        wrist_camera_topic: str = TELEOP_TOPICS["wrist_camera"],
        safety_state_topic: str = TELEOP_TOPICS["safety_state"],
        end_effector_pose_topic: str = TELEOP_TOPICS["end_effector_pose"],
        raw_command_topic: str = TELEOP_TOPICS["servo_l_command"],
        image_storage_format: str = "jpeg",
        jpeg_quality: int = 75,
    ) -> None:
        self.required_cameras = tuple(required_cameras)
        self.source = str(source)
        self.runtime_mode = str(runtime_mode)
        self.dataset_stage = str(dataset_stage)
        self.gripper_topic = str(gripper_topic)
        self.external_camera_topic = str(external_camera_topic)
        self.wrist_camera_topic = str(wrist_camera_topic)
        self.safety_state_topic = str(safety_state_topic)
        self.end_effector_pose_topic = str(end_effector_pose_topic)
        self.raw_command_topic = str(raw_command_topic)
        self.quality_config = quality_config or QualityConfig(
            required_cameras=tuple(required_cameras),
            max_message_age_s=None,
        )

    def build(self, observation_frame: SyncedFrame, action_frame: SyncedFrame) -> BuiltQposDemoFrame:
        """Build one frame from current observation and future qpos/gripper action."""
        metadata = {
            "source": self.source,
            "runtime_mode": self.runtime_mode,
            "dataset_stage": self.dataset_stage,
            "action_schema": "qpos_gripper",
            "converted_from": FUTURE_JOINT_STATE_ACTION,
        }
        if not observation_frame.ok:
            return self._dropped(metadata, observation_frame.drop_reasons)
        if not action_frame.ok:
            return self._dropped(metadata, action_frame.drop_reasons)

        try:
            observation = self._observation(observation_frame)
            action = self._qpos_gripper(action_frame)
        except Exception as exc:
            return self._dropped(metadata, [f"builder_error:{exc}"])

        raw_command = self._raw_command(observation_frame)
        if raw_command is not None:
            metadata["raw_teleop_command"] = raw_command

        quality = check_frame(
            observation=observation,
            action=action,
            schema_name="qpos_gripper",
            config=self.quality_config,
        )
        return BuiltQposDemoFrame(
            ok=quality.ok,
            observation=observation,
            action=action,
            metadata=metadata,
            drop_reasons=quality.drop_reasons,
        )

    def _dropped(self, metadata: Mapping[str, Any], reasons: Sequence[str]) -> BuiltQposDemoFrame:
        return BuiltQposDemoFrame(
            ok=False,
            observation={},
            action=None,
            metadata=dict(metadata),
            drop_reasons=list(reasons),
        )

    def _observation(self, frame: SyncedFrame) -> dict:
        samples = frame.samples
        joint_state = samples[TELEOP_TOPICS["joint_states"]].payload
        joint_names, qpos, qvel, effort = _canonical_ur5e_joint_state(joint_state)
        gripper = self._gripper(samples)
        return {
            "timestamp": float(frame.timestamp),
            "state": qpos + [gripper],
            "joint_names": joint_names,
            "qpos": qpos,
            "qvel": qvel,
            "effort": effort,
            "gripper": gripper,
            "images": self._images(samples),
            "safety": self._safety(samples),
            **self._end_effector_pose(samples),
        }

    def _qpos_gripper(self, frame: SyncedFrame) -> list:
        samples = frame.samples
        joint_state = samples[TELEOP_TOPICS["joint_states"]].payload
        _, qpos, _, _ = _canonical_ur5e_joint_state(joint_state)
        return qpos + [self._gripper(samples)]

    def _gripper(self, samples: Mapping[str, Sample]) -> float:
        gripper_state = samples[self.gripper_topic].payload
        return float(gripper_state.get("gripper", gripper_state.get("position", 0.0)))

    def _images(self, samples: Mapping[str, Sample]) -> dict:
        images = {}
        if self.external_camera_topic in samples:
            images["external"] = dict(samples[self.external_camera_topic].payload)
        if self.wrist_camera_topic in samples:
            images["wrist"] = dict(samples[self.wrist_camera_topic].payload)
        return images

    def _safety(self, samples: Mapping[str, Sample]) -> dict:
        sample = samples.get(self.safety_state_topic)
        if sample is None:
            return {}
        return dict(sample.payload)

    def _end_effector_pose(self, samples: Mapping[str, Sample]) -> dict:
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

    def _raw_command(self, frame: SyncedFrame):
        sample = frame.samples.get(self.raw_command_topic)
        if sample is None:
            return None
        return dict(sample.payload)


class QposDemoJsonlRecorder:
    """Write fixed-rate teleop demonstrations as trainable qpos_gripper data."""

    def __init__(
        self,
        root: Path,
        *,
        task: str,
        required_cameras: Sequence[str] = (),
        source: str = "teleop",
        runtime_mode: str = "rtde_teleop",
        dataset_stage: str = "original",
        gripper_topic: str = TELEOP_TOPICS["gripper_state"],
        external_camera_topic: str = TELEOP_TOPICS["external_camera"],
        wrist_camera_topic: str = TELEOP_TOPICS["wrist_camera"],
        safety_state_topic: str = TELEOP_TOPICS["safety_state"],
        end_effector_pose_topic: str = TELEOP_TOPICS["end_effector_pose"],
        raw_command_topic: str = TELEOP_TOPICS["servo_l_command"],
        image_storage_format: str = "jpeg",
        jpeg_quality: int = 75,
        episode_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.builder = QposDemoFrameBuilder(
            required_cameras=required_cameras,
            source=source,
            runtime_mode=runtime_mode,
            dataset_stage=dataset_stage,
            gripper_topic=gripper_topic,
            external_camera_topic=external_camera_topic,
            wrist_camera_topic=wrist_camera_topic,
            safety_state_topic=safety_state_topic,
            end_effector_pose_topic=end_effector_pose_topic,
            raw_command_topic=raw_command_topic,
        )
        self.writer = JsonlDatasetWriter(
            Path(root),
            "qpos_gripper",
            task=task,
            source=source,
            runtime_mode=runtime_mode,
            dataset_stage=dataset_stage,
            converted_from=FUTURE_JOINT_STATE_ACTION,
            image_storage_format=image_storage_format,
            jpeg_quality=jpeg_quality,
            episode_metadata=episode_metadata,
        )
        self._episode_started = False
        self.accepted_frames = 0
        self.dropped_frames = 0

    def record_pair(self, observation_frame: SyncedFrame, action_frame: SyncedFrame) -> BuiltQposDemoFrame:
        """Validate and write one observation frame labeled by the next qpos state."""
        built = self.builder.build(observation_frame, action_frame)
        if built.ok:
            if not self._episode_started:
                self.writer.start_episode()
                self._episode_started = True
            self.writer.add_frame(built.observation, built.action, metadata=built.metadata)
            self.accepted_frames += 1
        else:
            self.dropped_frames += 1
        return built

    def close(self) -> dict:
        """Close the active episode and return a summary."""
        if self._episode_started:
            self.writer.close_episode()
        return {
            "dataset_dir": str(self.writer.dataset_dir),
            "accepted_frames": self.accepted_frames,
            "dropped_frames": self.dropped_frames,
        }


class FixedRateQposDemoEngine:
    """Synchronize fixed-rate samples and write one delayed qpos-action frame per tick."""

    def __init__(
        self,
        *,
        recorder,
        required_topics,
        optional_topics=(),
        raw_command_topic: str = TELEOP_TOPICS["servo_l_command"],
        tolerance_s: float = 0.05,
        topic_tolerances=None,
        status_callback=None,
        drop_callback=None,
    ) -> None:
        self.recorder = recorder
        self.raw_command_topic = str(raw_command_topic)
        self.synchronizer = TopicSynchronizer(
            required_topics=tuple(required_topics),
            optional_topics=tuple(optional_topics),
            tolerance_s=tolerance_s,
            topic_tolerances=topic_tolerances or {},
        )
        self.status_callback = status_callback
        self.drop_callback = drop_callback
        self.accepted_frames = 0
        self.dropped_frames = 0
        self.last_status = "idle"
        self._pending_observation = None
        self._synchronized_once = False
        self._warmup_reasons = []

    def add_sample(self, sample: Sample) -> None:
        """Store one topic sample for future fixed-rate ticks."""
        self.synchronizer.add_sample(sample)

    def capture_at(self, timestamp: float):
        """Capture at a fixed-rate tick, labeling the previous tick with this tick state."""
        current = self.synchronizer.synchronize_at(timestamp)
        if not current.ok:
            if not self._synchronized_once:
                self.last_status = "warming_up"
                self._warmup_reasons = list(current.drop_reasons)
                self._emit_status()
                return current
            self.dropped_frames += 1
            self.last_status = "dropped"
            self._emit_drop(timestamp, current.drop_reasons)
            self._emit_status()
            return current

        if self._pending_observation is None:
            self._pending_observation = current
            self._synchronized_once = True
            self._warmup_reasons = []
            self.last_status = "primed"
            self._emit_status()
            return None

        built = self.recorder.record_pair(self._pending_observation, current)
        self._pending_observation = current
        if built.ok:
            self.accepted_frames += 1
            self.last_status = "accepted"
        else:
            self.dropped_frames += 1
            self.last_status = "dropped"
            self._emit_drop(timestamp, built.drop_reasons)
        self._emit_status()
        return built

    def _emit_status(self) -> None:
        if self.status_callback is None:
            return
        self.status_callback({
            "accepted_frames": self.accepted_frames,
            "dropped_frames": self.dropped_frames,
            "last_status": self.last_status,
            "sampling_mode": "fixed_rate_qpos",
            "warmup_reasons": list(self._warmup_reasons),
        })

    def _emit_drop(self, timestamp: float, drop_reasons: list) -> None:
        if self.drop_callback is None:
            return
        self.drop_callback({
            "timestamp": float(timestamp),
            "drop_reasons": list(drop_reasons),
        })


def _vector(value: Any, size: int, name: str) -> list:
    if value is None:
        raise ValueError(f"{name} must contain {size} values")
    values = [float(item) for item in value]
    if len(values) != size:
        raise ValueError(f"{name} must contain {size} values")
    return values


def _canonical_ur5e_joint_state(joint_state: Mapping[str, Any]) -> tuple[list, list, list, list]:
    """Select the six UR5e joints by name and return their fixed dataset order."""
    source_names = [str(name) for name in joint_state.get("joint_names", ())]
    indices = {}
    for index, name in enumerate(source_names):
        if name not in UR5E_JOINT_NAMES:
            continue
        if name in indices:
            raise ValueError(f"duplicate required joint name: {name}")
        indices[name] = index
    missing = [name for name in UR5E_JOINT_NAMES if name not in indices]
    if missing:
        raise ValueError(f"missing required joint names: {', '.join(missing)}")

    def ordered(field: str, *, required: bool) -> list:
        values = joint_state.get(field)
        if not values and not required:
            return [0.0] * len(UR5E_JOINT_NAMES)
        values = [float(value) for value in values or ()]
        if len(values) != len(source_names):
            raise ValueError(f"{field} must contain one value for each joint name")
        return [values[indices[name]] for name in UR5E_JOINT_NAMES]

    return (
        list(UR5E_JOINT_NAMES),
        ordered("positions", required=True),
        ordered("velocities", required=False),
        ordered("efforts", required=False),
    )
