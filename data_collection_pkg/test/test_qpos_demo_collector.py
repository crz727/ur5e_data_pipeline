import json

from data_collection_pkg.ros_capture.qpos_demo_collector import (
    FixedRateQposDemoEngine,
    QposDemoJsonlRecorder,
    UR5E_JOINT_NAMES,
)
from data_collection_pkg.ros_capture.collector_node import teleop_collector_config_from_parameters
from data_collection_pkg.ros_capture.synchronizer import Sample
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


class _Parameter:
    def __init__(self, value):
        self.value = value


class _Node:
    def __init__(self, values):
        self.values = values

    def get_parameter(self, name):
        return _Parameter(self.values.get(name))


def _joint_sample(timestamp, positions, joint_names=UR5E_JOINT_NAMES):
    return Sample(
        TELEOP_TOPICS["joint_states"],
        timestamp,
        {
            "joint_names": list(joint_names),
            "positions": positions,
            "velocities": [0.0] * 6,
            "efforts": [0.0] * 6,
        },
    )


def _gripper_sample(timestamp, value):
    return Sample(TELEOP_TOPICS["gripper_state"], timestamp, {"gripper": value})


def _raw_command_sample(timestamp):
    return Sample(
        TELEOP_TOPICS["servo_l_command"],
        timestamp,
        {
            "action": [0.4, 0.0, 0.3, 3.14, 0.0, 1.57, 0.6],
            "source": "teleop",
            "runtime_mode": "rtde_teleop",
            "action_schema": "teleop_servo_l_pose",
            "converted_from": "rtde_control.servoL",
        },
    )


def test_qpos_demo_recorder_persists_episode_annotation(tmp_path):
    annotation = {
        "task_name": "pick_place_batch_0807",
        "task_id": "pick_red_block_to_blue_tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
        "annotation_source": "capture_ui",
    }
    recorder = QposDemoJsonlRecorder(
        tmp_path,
        task="pick_place_batch_0807",
        episode_metadata=annotation,
    )
    engine = FixedRateQposDemoEngine(
        recorder=recorder,
        required_topics=(TELEOP_TOPICS["joint_states"], TELEOP_TOPICS["gripper_state"]),
        tolerance_s=0.05,
    )
    engine.add_sample(_joint_sample(1.0, [0.0] * 6))
    engine.add_sample(_gripper_sample(1.0, 0.2))
    assert engine.capture_at(1.0) is None
    engine.add_sample(_joint_sample(1.1, [0.1] * 6))
    engine.add_sample(_gripper_sample(1.1, 0.3))
    assert engine.capture_at(1.1).ok is True
    recorder.close()

    episode = json.loads((recorder.writer.meta_dir / "episodes.jsonl").read_text(encoding="utf-8"))

    assert episode["task"] == "pick_place_batch_0807"
    assert episode["task_name"] == "pick_place_batch_0807"
    assert episode["task_id"] == "pick_red_block_to_blue_tray"
    assert episode["language_instruction_en"] == "Pick up the red block and place it in the blue tray."
    assert episode["language_instruction_zh"] == "抓取红色方块并放入蓝色托盘。"
    assert episode["annotation_source"] == "capture_ui"


def test_fixed_rate_qpos_demo_uses_next_state_as_action(tmp_path):
    recorder = QposDemoJsonlRecorder(
        tmp_path,
        task="pick_place",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
        raw_command_topic=TELEOP_TOPICS["servo_l_command"],
    )
    engine = FixedRateQposDemoEngine(
        recorder=recorder,
        required_topics=(TELEOP_TOPICS["joint_states"], TELEOP_TOPICS["gripper_state"]),
        optional_topics=(TELEOP_TOPICS["servo_l_command"],),
        raw_command_topic=TELEOP_TOPICS["servo_l_command"],
        tolerance_s=0.05,
    )

    engine.add_sample(_joint_sample(10.0, [0.0, -1.0, 1.0, -1.5, -1.2, 0.1]))
    engine.add_sample(_gripper_sample(10.0, 0.2))
    engine.add_sample(_raw_command_sample(10.0))
    assert engine.capture_at(10.0) is None

    engine.add_sample(_joint_sample(10.1, [0.1, -0.9, 1.1, -1.4, -1.1, 0.2]))
    engine.add_sample(_gripper_sample(10.1, 0.35))
    engine.add_sample(_raw_command_sample(10.1))
    built = engine.capture_at(10.1)
    summary = recorder.close()

    assert built.ok is True
    assert built.observation["state"] == [0.0, -1.0, 1.0, -1.5, -1.2, 0.1, 0.2]
    assert built.action == [0.1, -0.9, 1.1, -1.4, -1.1, 0.2, 0.35]
    assert built.metadata["action_schema"] == "qpos_gripper"
    assert built.metadata["converted_from"] == "future_joint_state"
    assert built.metadata["raw_teleop_command"]["action"] == [
        0.4,
        0.0,
        0.3,
        3.14,
        0.0,
        1.57,
        0.6,
    ]
    assert summary["accepted_frames"] == 1

    frame_path = (
        tmp_path
        / "original"
        / "teleop"
        / "qpos_gripper"
        / "data"
        / "episode_000000.jsonl"
    )
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    assert frame["action"] == [0.1, -0.9, 1.1, -1.4, -1.1, 0.2, 0.35]
    assert frame["metadata"]["runtime_mode"] == "teleop"
    assert frame["metadata"]["dataset_stage"] == "original"


def test_fixed_rate_qpos_demo_does_not_count_pre_sync_warmup_as_dropped(tmp_path):
    statuses = []
    drops = []
    recorder = QposDemoJsonlRecorder(tmp_path, task="pick")
    engine = FixedRateQposDemoEngine(
        recorder=recorder,
        required_topics=(TELEOP_TOPICS["joint_states"], TELEOP_TOPICS["gripper_state"]),
        tolerance_s=0.05,
        status_callback=statuses.append,
        drop_callback=drops.append,
    )

    engine.capture_at(1.0)

    assert engine.dropped_frames == 0
    assert drops == []
    assert statuses[-1]["last_status"] == "warming_up"
    assert statuses[-1]["warmup_reasons"] == [
        f"missing_topic:{TELEOP_TOPICS['joint_states']}",
        f"missing_topic:{TELEOP_TOPICS['gripper_state']}",
    ]


def test_qpos_demo_records_joint_states_in_canonical_ur5e_order(tmp_path):
    recorder = QposDemoJsonlRecorder(tmp_path, task="pick")
    engine = FixedRateQposDemoEngine(
        recorder=recorder,
        required_topics=(TELEOP_TOPICS["joint_states"], TELEOP_TOPICS["gripper_state"]),
        tolerance_s=0.05,
    )
    source_names = (
        "wrist_3_joint", "elbow_joint", "shoulder_pan_joint",
        "wrist_1_joint", "shoulder_lift_joint", "wrist_2_joint",
    )
    engine.add_sample(_joint_sample(1.0, [6.0, 3.0, 1.0, 4.0, 2.0, 5.0], source_names))
    engine.add_sample(_gripper_sample(1.0, 0.2))
    assert engine.capture_at(1.0) is None
    engine.add_sample(_joint_sample(1.1, [16.0, 13.0, 11.0, 14.0, 12.0, 15.0], source_names))
    engine.add_sample(_gripper_sample(1.1, 0.3))

    built = engine.capture_at(1.1)

    assert built.ok is True
    assert built.observation["joint_names"] == list(UR5E_JOINT_NAMES)
    assert built.observation["qpos"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert built.action == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 0.3]


def test_qpos_demo_drops_joint_state_without_all_ur5e_joint_names(tmp_path):
    recorder = QposDemoJsonlRecorder(tmp_path, task="pick")
    engine = FixedRateQposDemoEngine(
        recorder=recorder,
        required_topics=(TELEOP_TOPICS["joint_states"], TELEOP_TOPICS["gripper_state"]),
        tolerance_s=0.05,
    )
    incomplete_names = UR5E_JOINT_NAMES[:-1]
    engine.add_sample(_joint_sample(1.0, [0.0] * 5, incomplete_names))
    engine.add_sample(_gripper_sample(1.0, 0.2))
    assert engine.capture_at(1.0) is None
    engine.add_sample(_joint_sample(1.1, [0.0] * 5, incomplete_names))
    engine.add_sample(_gripper_sample(1.1, 0.3))

    built = engine.capture_at(1.1)

    assert built.ok is False
    assert built.drop_reasons == ["builder_error:missing required joint names: wrist_3_joint"]


def test_qpos_demo_recorder_does_not_create_empty_episode_without_frames(tmp_path):
    recorder = QposDemoJsonlRecorder(
        tmp_path,
        task="empty",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )

    summary = recorder.close()

    assert summary["accepted_frames"] == 0
    assert not (tmp_path / "original" / "teleop" / "qpos_gripper" / "data").exists()
    assert not (tmp_path / "original" / "teleop" / "qpos_gripper" / "meta").exists()


def test_fixed_rate_config_uses_qpos_schema_without_action_as_required_topic():
    config = teleop_collector_config_from_parameters(_Node({
        "sampling_mode": "fixed_rate",
        "dataset_stage": "original",
        "runtime_mode": "http",
        "dataset_schema": "teleop_servo_l_pose",
        "sample_rate_hz": 20.0,
        "action_topic": "/teleop/command",
        "gripper_state_topic": "/gripper/state",
    }))

    assert config["schema"] == "qpos_gripper"
    assert config["sampling_mode"] == "fixed_rate"
    assert config["dataset_stage"] == "original"
    assert config["runtime_mode"] == "http"
    assert config["sample_rate_hz"] == 20.0
    assert config["required_topics"] == (
        TELEOP_TOPICS["joint_states"],
        "/gripper/state",
    )
    assert "/teleop/command" in config["optional_topics"]
