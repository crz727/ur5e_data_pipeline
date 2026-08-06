"""Command-triggered teleop collection engine."""

from data_collection_pkg.ros_capture.synchronizer import Sample, TopicSynchronizer
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


class TeleopCollectorEngine:
    """Synchronize samples and record a frame when a servoL command arrives."""

    def __init__(
        self,
        *,
        recorder,
        required_topics=None,
        optional_topics=None,
        action_topic=None,
        tolerance_s: float = 0.05,
        status_callback=None,
        drop_callback=None,
    ) -> None:
        self.recorder = recorder
        self.action_topic = action_topic or TELEOP_TOPICS["servo_l_command"]
        self.synchronizer = TopicSynchronizer(
            required_topics=required_topics or (
                TELEOP_TOPICS["joint_states"],
                TELEOP_TOPICS["servo_l_command"],
                TELEOP_TOPICS["gripper_state"],
            ),
            optional_topics=optional_topics or (
                TELEOP_TOPICS["external_camera"],
                TELEOP_TOPICS["wrist_camera"],
                TELEOP_TOPICS["safety_state"],
            ),
            tolerance_s=tolerance_s,
        )
        self.status_callback = status_callback
        self.drop_callback = drop_callback
        self.accepted_frames = 0
        self.dropped_frames = 0
        self.last_status = "idle"

    def add_sample(self, sample: Sample):
        """Add one sample and record when the sample is a servoL command."""
        self.synchronizer.add_sample(sample)
        if sample.topic != self.action_topic:
            return None

        synced = self.synchronizer.synchronize_at(sample.timestamp)
        if not synced.ok:
            self.dropped_frames += 1
            self.last_status = "dropped"
            self._emit_drop(sample.timestamp, synced.drop_reasons)
            self._emit_status()
            return synced

        built = self.recorder.record_synced_frame(synced)
        if built.ok:
            self.accepted_frames += 1
            self.last_status = "accepted"
        else:
            self.dropped_frames += 1
            self.last_status = "dropped"
            self._emit_drop(sample.timestamp, built.drop_reasons)
        self._emit_status()
        return built

    def _emit_status(self) -> None:
        if self.status_callback is None:
            return
        self.status_callback({
            "accepted_frames": self.accepted_frames,
            "dropped_frames": self.dropped_frames,
            "last_status": self.last_status,
        })

    def _emit_drop(self, timestamp: float, drop_reasons: list) -> None:
        if self.drop_callback is None:
            return
        self.drop_callback({
            "timestamp": float(timestamp),
            "drop_reasons": list(drop_reasons),
        })
