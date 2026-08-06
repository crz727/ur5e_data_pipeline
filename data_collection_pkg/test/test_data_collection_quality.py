import json

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.quality import (
    QualityConfig,
    check_dataset,
    check_frame,
    quality_check_items,
)


def _observation(timestamp=1.0):
    return {
        "timestamp": timestamp,
        "state": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2],
        "images": {"external": {"timestamp": timestamp}, "wrist": {"timestamp": timestamp}},
        "safety": {"software_estop": False, "protective_stop": False},
    }


def test_check_frame_accepts_realtime_ready_frame():
    result = check_frame(
        observation=_observation(timestamp=10.0),
        action=[0.0] * 7,
        schema_name="qpos_gripper",
        config=QualityConfig(required_cameras=("external", "wrist"), max_message_age_s=0.2),
        now=10.1,
        previous_timestamp=9.9,
    )

    assert result.ok is True
    assert result.drop_reasons == []


def test_check_frame_reports_stale_missing_camera_and_safety():
    observation = _observation(timestamp=1.0)
    observation["images"].pop("wrist")
    observation["safety"]["software_estop"] = True

    result = check_frame(
        observation=observation,
        action=[0.0] * 6,
        schema_name="qpos_gripper",
        config=QualityConfig(required_cameras=("external", "wrist"), max_message_age_s=0.5),
        now=2.0,
        previous_timestamp=1.1,
    )

    assert result.ok is False
    assert "message_age_exceeded" in result.drop_reasons
    assert "timestamp_moved_backward" in result.drop_reasons
    assert "missing_camera:wrist" in result.drop_reasons
    assert "action_dim_mismatch" in result.drop_reasons
    assert "safety_active:software_estop" in result.drop_reasons


def test_check_frame_can_require_end_effector_pose():
    missing = check_frame(
        observation=_observation(timestamp=1.0),
        action=[0.0] * 7,
        schema_name="qpos_gripper",
        config=QualityConfig(require_ee_pose=True),
    )

    observation = _observation(timestamp=1.0)
    observation["ee_pose"] = [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0]
    present = check_frame(
        observation=observation,
        action=[0.0] * 7,
        schema_name="qpos_gripper",
        config=QualityConfig(require_ee_pose=True),
    )

    assert missing.ok is False
    assert "ee_pose_missing" in missing.drop_reasons
    assert present.ok is True


def test_check_dataset_reports_saved_episode_issues(tmp_path):
    writer = JsonlDatasetWriter(tmp_path, "qpos_gripper", task="pick", source="teleop")
    writer.start_episode()
    writer.add_frame(_observation(), [0.0] * 7)
    writer.close_episode()

    frame_path = tmp_path / "trainable" / "policy" / "qpos_gripper" / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    frame["action"] = [0.0] * 6
    frame_path.write_text(json.dumps(frame) + "\n", encoding="utf-8")

    report = check_dataset(tmp_path / "trainable" / "policy" / "qpos_gripper")

    assert report.ok is False
    assert report.episode_count == 1
    assert report.frame_count == 1
    assert "episode_000000.jsonl frame 0: action_dim_mismatch" in report.issues


def test_quality_report_exposes_enabled_check_items(tmp_path):
    writer = JsonlDatasetWriter(tmp_path, "qpos_gripper", task="pick", source="teleop")
    writer.start_episode()
    writer.add_frame(_observation(), [0.0] * 7)
    writer.close_episode()

    report = check_dataset(
        tmp_path / "trainable" / "policy" / "qpos_gripper",
        config=QualityConfig.trainable(
            required_cameras=("external", "wrist"),
            max_sync_delta_s=0.05,
            target_fps=10.0,
            min_frame_count=1,
            require_ee_pose=True,
        ),
    )

    check_names = {item["name"] for item in report.checks}
    assert report.profile == "trainable"
    assert "metadata_file_exists" in check_names
    assert "required_cameras_present" in check_names
    assert "camera_frame_sync_delta" in check_names
    assert "target_frame_rate" in check_names
    assert "ee_pose_present" in check_names
    assert {
        "name": "camera_frame_sync_delta",
        "scope": "frame",
        "enabled": True,
        "threshold": {"max_sync_delta_s": 0.05},
    } in report.checks


def test_quality_check_items_describe_replay_profile():
    checks = quality_check_items(QualityConfig.replay())

    assert {
        "name": "replay_request_constructable",
        "scope": "frame",
        "enabled": True,
    } in checks


def test_trainable_profile_checks_sync_images_ranges_and_action_steps():
    observation = _observation(timestamp=10.0)
    observation["state"] = [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.5]
    observation["images"]["external"] = {
        "timestamp": 10.1,
        "width": 3,
        "height": 2,
        "data": "not-base64",
    }

    result = check_frame(
        observation=observation,
        action=[2.0] * 7,
        schema_name="qpos_gripper",
        config=QualityConfig.trainable(
            required_cameras=("external", "wrist"),
            max_sync_delta_s=0.02,
            image_shapes={"external": (2, 2)},
            qpos_limits=((-1.0, 1.0),) * 6,
            gripper_range=(0.0, 1.0),
            action_ranges={"qpos_gripper": ((-1.0, 1.0),) * 7},
            max_action_step=(0.5,) * 7,
        ),
        previous_action=[0.0] * 7,
    )

    assert result.ok is False
    assert "sync_delta_exceeded:external" in result.drop_reasons
    assert "image_shape_mismatch:external" in result.drop_reasons
    assert "qpos_range_exceeded:0" in result.drop_reasons
    assert "gripper_range_exceeded" in result.drop_reasons
    assert "action_range_exceeded:0" in result.drop_reasons
    assert "action_step_exceeded:0" in result.drop_reasons


def test_trainable_profile_accepts_ros_raw_image_payloads_without_safety_topic():
    observation = _observation(timestamp=10.0)
    observation["images"]["external"] = {
        "timestamp": 10.0,
        "width": 2,
        "height": 1,
        "encoding": "rgb8",
        "data": [255, 0, 0, 0, 255, 0],
    }
    observation["images"]["wrist"] = {
        "timestamp": 10.0,
        "width": 2,
        "height": 1,
        "encoding": "rgb8",
        "data": [0, 0, 255, 255, 255, 255],
    }
    observation["safety"] = {}

    result = check_frame(
        observation=observation,
        action=[0.0] * 7,
        schema_name="teleop_servo_l_pose",
        config=QualityConfig.trainable(
            required_cameras=("external", "wrist"),
            max_sync_delta_s=0.05,
        ),
    )

    assert result.ok is True
    assert result.drop_reasons == []


def test_trainable_profile_does_not_require_custom_safety_fields_by_default():
    assert QualityConfig.trainable().require_safety_fields is False


def test_trainable_profile_can_skip_image_decode_for_legacy_raw_payloads():
    observation = _observation(timestamp=10.0)
    observation["images"]["external"] = {
        "timestamp": 10.0,
        "data": [255, 0, 0, 0, 255, 0],
    }
    observation["images"]["wrist"] = {
        "timestamp": 10.0,
        "data": [0, 0, 255, 255, 255, 255],
    }

    result = check_frame(
        observation=observation,
        action=[0.0] * 7,
        schema_name="teleop_servo_l_pose",
        config=QualityConfig.trainable(
            required_cameras=("external", "wrist"),
            decode_images=False,
        ),
    )

    assert result.ok is True
    assert result.drop_reasons == []


def test_trainable_dataset_checks_frequency_and_episode_shape(tmp_path):
    writer = JsonlDatasetWriter(tmp_path, "qpos_gripper", task="pick", source="teleop")
    writer.start_episode()
    writer.add_frame(_observation(timestamp=1.0), [0.0] * 7)
    writer.add_frame(_observation(timestamp=1.5), [0.1] * 7)
    writer.close_episode()

    report = check_dataset(
        tmp_path / "trainable" / "policy" / "qpos_gripper",
        config=QualityConfig.trainable(
            target_fps=10.0,
            fps_tolerance_ratio=0.2,
            min_frame_count=3,
            min_duration_s=1.0,
        ),
    )

    assert report.ok is False
    assert "episode 0: frame_count_below_min:2<3" in report.issues
    assert "episode 0: duration_below_min:0.500000<1.000000" in report.issues
    assert "episode_000000.jsonl frame 1: frame_dt_out_of_range" in report.issues


def test_replay_profile_checks_replay_request_constructability(tmp_path):
    dataset_dir = tmp_path / "trainable" / "policy" / "qpos_gripper"
    (dataset_dir / "meta").mkdir(parents=True)
    (dataset_dir / "data").mkdir()
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "action_schema": "qpos_gripper",
            "frame_count": 1,
            "data_path": "data/episode_000000.jsonl",
        })
        + "\n",
        encoding="utf-8",
    )
    (dataset_dir / "data" / "episode_000000.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "frame_index": 0,
            "timestamp": 1.0,
            "observation": _observation(timestamp=1.0),
            "action": None,
        })
        + "\n",
        encoding="utf-8",
    )

    report = check_dataset(dataset_dir, config=QualityConfig.replay())

    assert report.ok is False
    assert "episode_000000.jsonl frame 0: replay_request_unconstructable" in report.issues
