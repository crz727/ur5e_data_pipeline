from data_collection_pkg.ros_capture.collector_engine import TeleopCollectorEngine
from data_collection_pkg.ros_capture.synchronizer import Sample
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


class FakeRecorder:
    def __init__(self, ok=True):
        self.ok = ok
        self.frames = []

    def record_synced_frame(self, frame):
        self.frames.append(frame)
        return type(
            "Built",
            (),
            {
                "ok": self.ok,
                "drop_reasons": [] if self.ok else ["safety_active:software_estop"],
            },
        )()


def _sample(topic, timestamp, payload):
    return Sample(topic=topic, timestamp=timestamp, payload=payload)


def _ready_samples(timestamp=10.0):
    return [
        _sample(TELEOP_TOPICS["joint_states"], timestamp, {"positions": [0.0] * 6}),
        _sample(TELEOP_TOPICS["gripper_state"], timestamp, {"gripper": 0.5}),
        _sample(TELEOP_TOPICS["external_camera"], timestamp, {"image": "external"}),
        _sample(TELEOP_TOPICS["wrist_camera"], timestamp, {"image": "wrist"}),
        _sample(TELEOP_TOPICS["safety_state"], timestamp, {"software_estop": False}),
    ]


def test_collector_engine_records_when_command_arrives_and_frame_is_synced():
    statuses = []
    recorder = FakeRecorder(ok=True)
    engine = TeleopCollectorEngine(recorder=recorder, status_callback=statuses.append)

    for sample in _ready_samples():
        engine.add_sample(sample)
    result = engine.add_sample(
        _sample(TELEOP_TOPICS["servo_l_command"], 10.01, {"action": [0.0] * 7})
    )

    assert result.ok is True
    assert len(recorder.frames) == 1
    assert statuses[-1]["accepted_frames"] == 1
    assert statuses[-1]["dropped_frames"] == 0
    assert statuses[-1]["last_status"] == "accepted"


def test_collector_engine_reports_drop_reasons():
    statuses = []
    drops = []
    recorder = FakeRecorder(ok=False)
    engine = TeleopCollectorEngine(
        recorder=recorder,
        status_callback=statuses.append,
        drop_callback=drops.append,
    )

    for sample in _ready_samples():
        engine.add_sample(sample)
    result = engine.add_sample(
        _sample(TELEOP_TOPICS["servo_l_command"], 10.01, {"action": [0.0] * 7})
    )

    assert result.ok is False
    assert statuses[-1]["accepted_frames"] == 0
    assert statuses[-1]["dropped_frames"] == 1
    assert drops[-1] == {
        "timestamp": 10.01,
        "drop_reasons": ["safety_active:software_estop"],
    }
