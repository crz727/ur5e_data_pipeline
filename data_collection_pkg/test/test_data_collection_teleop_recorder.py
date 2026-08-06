import json

from data_collection_pkg.ros_capture.synchronizer import Sample, TopicSynchronizer
from data_collection_pkg.ros_capture.teleop_recorder import (
    TELEOP_TOPICS,
    TeleopFrameBuilder,
    TeleopJsonlRecorder,
)


def _synced_frame(
    timestamp=10.0,
    *,
    safety=None,
    action_topic=None,
    gripper_topic=None,
    external_camera_topic=None,
    wrist_camera_topic=None,
    end_effector_pose_topic=None,
):
    action_topic = action_topic or TELEOP_TOPICS["servo_l_command"]
    gripper_topic = gripper_topic or TELEOP_TOPICS["gripper_state"]
    external_camera_topic = external_camera_topic or TELEOP_TOPICS["external_camera"]
    wrist_camera_topic = wrist_camera_topic or TELEOP_TOPICS["wrist_camera"]
    end_effector_pose_topic = end_effector_pose_topic or TELEOP_TOPICS["end_effector_pose"]
    synchronizer = TopicSynchronizer(
        required_topics=(
            TELEOP_TOPICS["joint_states"],
            action_topic,
            gripper_topic,
        ),
        optional_topics=(
            external_camera_topic,
            wrist_camera_topic,
            TELEOP_TOPICS["safety_state"],
            end_effector_pose_topic,
        ),
        tolerance_s=0.05,
    )
    synchronizer.add_sample(Sample(
        TELEOP_TOPICS["joint_states"],
        timestamp,
        {
            "positions": [0.0, -1.0, 1.0, -1.5, -1.2, 0.1],
            "velocities": [0.0] * 6,
            "efforts": [0.0] * 6,
        },
    ))
    synchronizer.add_sample(Sample(
        action_topic,
        timestamp + 0.01,
        {"action": [0.4, 0.0, 0.3, 3.14, 0.0, 1.57, 0.6]},
    ))
    synchronizer.add_sample(Sample(
        gripper_topic,
        timestamp,
        {"gripper": 0.55},
    ))
    synchronizer.add_sample(Sample(
        external_camera_topic,
        timestamp,
        {"image": "external-frame"},
    ))
    synchronizer.add_sample(Sample(
        wrist_camera_topic,
        timestamp,
        {"image": "wrist-frame"},
    ))
    synchronizer.add_sample(Sample(
        TELEOP_TOPICS["safety_state"],
        timestamp,
        safety or {"software_estop": False, "protective_stop": False},
    ))
    synchronizer.add_sample(Sample(
        end_effector_pose_topic,
        timestamp,
        {
            "frame_id": "base",
            "child_frame_id": "tool0",
            "pose": [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0],
        },
    ))
    return synchronizer.synchronize_at(timestamp + 0.01)


def test_teleop_frame_builder_maps_synced_samples_to_trainable_frame():
    built = TeleopFrameBuilder(required_cameras=("external", "wrist")).build(_synced_frame())

    assert built.ok is True
    assert built.action == [0.4, 0.0, 0.3, 3.14, 0.0, 1.57, 0.6]
    assert built.observation["state"] == [0.0, -1.0, 1.0, -1.5, -1.2, 0.1, 0.55]
    assert built.observation["qpos"] == [0.0, -1.0, 1.0, -1.5, -1.2, 0.1]
    assert built.observation["ee_pose"] == [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0]
    assert built.observation["tool_pose"] == {
        "frame_id": "base",
        "child_frame_id": "tool0",
        "pose": [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0],
        "timestamp": 10.0,
    }
    assert built.observation["images"]["external"] == {"image": "external-frame"}
    assert built.observation["images"]["wrist"] == {"image": "wrist-frame"}
    assert built.metadata == {
        "source": "teleop",
        "runtime_mode": "teleop",
        "action_schema": "teleop_twist_gripper",
        "converted_from": TELEOP_TOPICS["servo_l_command"],
    }


def test_teleop_frame_builder_rejects_safety_active_frame():
    frame = _synced_frame(safety={"software_estop": True, "protective_stop": False})
    built = TeleopFrameBuilder(required_cameras=("external", "wrist")).build(frame)

    assert built.ok is False
    assert "safety_active:software_estop" in built.drop_reasons


def test_teleop_jsonl_recorder_writes_valid_frames_and_counts_drops(tmp_path):
    recorder = TeleopJsonlRecorder(
        tmp_path,
        task="teleop_pick",
        required_cameras=("external", "wrist"),
    )

    accepted = recorder.record_synced_frame(_synced_frame())
    dropped = recorder.record_synced_frame(
        _synced_frame(safety={"software_estop": True, "protective_stop": False})
    )
    summary = recorder.close()

    assert accepted.ok is True
    assert dropped.ok is False
    assert summary == {
        "dataset_dir": str(tmp_path / "trainable" / "teleop" / "twist_gripper"),
        "accepted_frames": 1,
        "dropped_frames": 1,
    }

    frame_path = tmp_path / "trainable" / "teleop" / "twist_gripper" / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    assert frame["metadata"]["source"] == "teleop"
    assert frame["metadata"]["converted_from"] == TELEOP_TOPICS["servo_l_command"]


def test_recorder_can_classify_http_api_action_source(tmp_path):
    action_topic = "/ur5e/control/action_event"
    recorder = TeleopJsonlRecorder(
        tmp_path,
        task="api_pick",
        required_cameras=("external", "wrist"),
        source="http_api",
        runtime_mode="http_api",
        schema_name="qpos_gripper",
        action_topic=action_topic,
    )

    accepted = recorder.record_synced_frame(_synced_frame(action_topic=action_topic))
    summary = recorder.close()

    assert accepted.ok is True
    assert summary["dataset_dir"] == str(tmp_path / "trainable" / "policy" / "qpos_gripper")

    frame_path = tmp_path / "trainable" / "policy" / "qpos_gripper" / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    assert frame["metadata"]["source"] == "http_api"
    assert frame["metadata"]["runtime_mode"] == "http_api"
    assert frame["metadata"]["action_schema"] == "qpos_gripper"
    assert frame["metadata"]["converted_from"] == action_topic


def test_frame_metadata_can_come_from_action_event_payload():
    action_topic = "/ur5e/control/action_event"
    frame = _synced_frame(action_topic=action_topic)
    frame.samples[action_topic].payload.update({
        "source": "http_api",
        "runtime_mode": "http_api",
        "action_schema": "qpos_gripper",
        "converted_from": action_topic,
    })

    built = TeleopFrameBuilder(
        source="configured",
        runtime_mode="configured",
        schema_name="qpos_gripper",
        action_topic=action_topic,
    ).build(frame)

    assert built.metadata == {
        "source": "http_api",
        "runtime_mode": "http_api",
        "action_schema": "qpos_gripper",
        "converted_from": action_topic,
    }


def test_frame_builder_accepts_custom_gripper_topic():
    gripper_topic = "/robotiq/gripper/state"
    built = TeleopFrameBuilder(
        gripper_topic=gripper_topic,
    ).build(_synced_frame(gripper_topic=gripper_topic))

    assert built.ok is True
    assert built.observation["gripper"] == 0.55


def test_frame_builder_accepts_real_robot_camera_and_tcp_topics():
    external_camera_topic = "/camera2/scene_camera/color/image_raw"
    wrist_camera_topic = "/camera1/wrist_camera/color/image_raw"
    end_effector_pose_topic = "/tcp_pose_broadcaster/pose"

    built = TeleopFrameBuilder(
        required_cameras=("external", "wrist"),
        external_camera_topic=external_camera_topic,
        wrist_camera_topic=wrist_camera_topic,
        end_effector_pose_topic=end_effector_pose_topic,
    ).build(_synced_frame(
        external_camera_topic=external_camera_topic,
        wrist_camera_topic=wrist_camera_topic,
        end_effector_pose_topic=end_effector_pose_topic,
    ))

    assert built.ok is True
    assert built.observation["images"]["external"] == {"image": "external-frame"}
    assert built.observation["images"]["wrist"] == {"image": "wrist-frame"}
    assert built.observation["ee_pose"] == [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0]


def test_recorder_can_store_http_api_action_as_debug_event(tmp_path):
    action_topic = "/ur5e/control/action_event"
    recorder = TeleopJsonlRecorder(
        tmp_path,
        task="api_pick",
        required_cameras=("external", "wrist"),
        source="http_api",
        runtime_mode="http_api",
        schema_name="http_api_action",
        action_topic=action_topic,
    )
    frame = _synced_frame(action_topic=action_topic)
    frame.samples[action_topic].payload.update({
        "source": "http_api",
        "runtime_mode": "http_api",
        "action_schema": "http_api_action",
        "converted_from": action_topic,
        "action": {
            "command_schema": "qpos_gripper",
            "values": [0, 1, 2, 3, 4, 5, 0.6],
        },
    })

    accepted = recorder.record_synced_frame(frame)
    summary = recorder.close()

    assert accepted.ok is True
    assert summary["dataset_dir"] == str(tmp_path / "debug" / "http_api" / "action")

    frame_path = tmp_path / "debug" / "http_api" / "action" / "data" / "episode_000000.jsonl"
    frame_data = json.loads(frame_path.read_text(encoding="utf-8").strip())
    assert frame_data["metadata"]["action_schema"] == "http_api_action"
    assert frame_data["action"]["command_schema"] == "qpos_gripper"
