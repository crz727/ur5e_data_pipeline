import json
from pathlib import Path

from data_collection_pkg.cli import main
from data_collection_pkg.dataset.cleaner import CleaningConfig, clean_original_dataset
from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter


JPEG_BYTES = (
    b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03"
    + b"\x00" * 10
    + b"\xff\xd9"
)


def _observation(timestamp, *, qpos=None, gripper=0.4):
    qpos = qpos or [0.1, -0.2, 0.3, -0.4, 0.5, -0.6]
    return {
        "timestamp": timestamp,
        "state": qpos + [gripper],
        "qpos": qpos,
        "qvel": [0.0] * 6,
        "effort": [0.0] * 6,
        "gripper": gripper,
        "ee_pose": [0.2, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0],
        "safety": {"software_estop": False, "protective_stop": False},
        "images": {
            "external": {"timestamp": timestamp, "format": "jpeg", "data": JPEG_BYTES},
            "wrist": {"timestamp": timestamp, "format": "jpeg", "data": JPEG_BYTES},
        },
    }


def _write_original_dataset(tmp_path, annotations, *, episode_metadata=None):
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
        episode_metadata=episode_metadata,
    )
    for episode_index in range(4):
        writer.start_episode()
        for frame_index in range(31):
            timestamp = 10.0 + episode_index * 10.0 + frame_index / 15.0
            qpos = [0.1 + 0.003 * frame_index, -0.2, 0.3, -0.4, 0.5, -0.6]
            writer.add_frame(_observation(timestamp, qpos=qpos), [0.1] * 7)
        writer.close_episode()

    annotation_path = writer.dataset_dir / "meta" / "episode_annotations.jsonl"
    with annotation_path.open("w", encoding="utf-8") as stream:
        for episode_index, outcome in annotations.items():
            stream.write(json.dumps({
                "schema_version": 1,
                "episode_index": episode_index,
                "outcome": outcome,
                "review_status": "reviewed",
                "source": "human",
            }) + "\n")
    return writer.dataset_dir


def _write_motion_episode(tmp_path, *, states, outcome="success"):
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    for frame_index, qpos in enumerate(states):
        timestamp = 10.0 + frame_index / 15.0
        writer.add_frame(_observation(timestamp, qpos=qpos), qpos + [0.4])
    writer.close_episode()
    (writer.dataset_dir / "meta" / "episode_annotations.jsonl").write_text(
        json.dumps({
            "schema_version": 1,
            "episode_index": 0,
            "outcome": outcome,
            "review_status": "reviewed",
            "source": "human",
        }) + "\n",
        encoding="utf-8",
    )
    return writer.dataset_dir


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_cleaner_copies_only_successful_quality_approved_episode(tmp_path):
    source = _write_original_dataset(tmp_path, {0: "success", 1: "failure", 3: "success"})
    invalid_path = source / "data" / "episode_000003.jsonl"
    invalid_frame = _read_jsonl(invalid_path)[0]
    invalid_frame["action"] = [0.1] * 6
    invalid_path.write_text(json.dumps(invalid_frame) + "\n", encoding="utf-8")

    result = clean_original_dataset(source)

    cleaned = Path(result["cleaned_dataset_dir"])
    assert result["accepted_episode_indices"] == [0]
    assert result["rejected_episode_indices"] == [1, 3]
    assert result["needs_review_episode_indices"] == [2]
    assert (cleaned / "data" / "episode_000000.jsonl").is_file()
    accepted_frame = _read_jsonl(cleaned / "data" / "episode_000000.jsonl")[0]
    external_path = accepted_frame["observation"]["images"]["external"]["data_path"]
    assert (cleaned / external_path).is_file()
    assert not (cleaned / "data" / "episode_000001.jsonl").exists()
    assert source.is_dir()
    assert (source / "data" / "episode_000003.jsonl").is_file()


def test_cleaner_retains_episode_language_annotation_fields_unchanged(tmp_path):
    annotation = {
        "task_name": "pick_place_batch_0807",
        "task_id": "pick-red-block-to-blue-tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
        "annotation_source": "capture_ui",
    }
    source = _write_original_dataset(
        tmp_path,
        {0: "success", 1: "failure", 3: "failure"},
        episode_metadata=annotation,
    )

    result = clean_original_dataset(source)

    cleaned_episode = _read_jsonl(
        Path(result["cleaned_dataset_dir"]) / "meta" / "episodes.jsonl"
    )[0]
    assert {key: cleaned_episode[key] for key in annotation} == annotation


def test_cleaner_manifest_and_report_explain_every_non_accepted_episode(tmp_path):
    source = _write_original_dataset(tmp_path, {0: "success", 1: "failure", 3: "success"})
    invalid_path = source / "data" / "episode_000003.jsonl"
    invalid_frame = _read_jsonl(invalid_path)[0]
    invalid_frame["action"] = [0.1] * 6
    invalid_path.write_text(json.dumps(invalid_frame) + "\n", encoding="utf-8")

    result = clean_original_dataset(source)

    cleaned = Path(result["cleaned_dataset_dir"])
    manifest = {
        row["episode_index"]: row
        for row in _read_jsonl(cleaned / "meta" / "cleaning_manifest.jsonl")
    }
    report = Path(result["report_path"]).read_text(encoding="utf-8")

    assert manifest[0]["decision"] == "accepted"
    assert manifest[1]["decision"] == "rejected"
    assert manifest[1]["reasons"] == ["human_outcome_failure"]
    assert manifest[2]["decision"] == "needs_review"
    assert manifest[2]["reasons"] == ["human_outcome_missing"]
    assert manifest[3]["decision"] == "rejected"
    assert "action_dim_mismatch" in manifest[3]["reasons"]
    assert "episode 1" in report
    assert "human_outcome_failure" in report
    assert "episode 2" in report
    assert "human_outcome_missing" in report


def test_clean_original_cli_prints_the_readable_report_location(tmp_path, capsys):
    source = _write_original_dataset(tmp_path, {0: "success", 1: "failure", 3: "success"})

    assert main(["clean-original", str(source)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["report_path"]).is_file()
    assert payload["accepted_episode_indices"] == [0, 3]


def test_cleaner_reports_unknown_action_schema_without_aborting_the_batch(tmp_path):
    source = _write_original_dataset(tmp_path, {0: "success", 1: "success", 3: "success"})
    episodes_path = source / "meta" / "episodes.jsonl"
    episodes = _read_jsonl(episodes_path)
    episodes[1]["action_schema"] = "unknown_schema"
    episodes_path.write_text(
        "".join(json.dumps(episode) + "\n" for episode in episodes),
        encoding="utf-8",
    )

    result = clean_original_dataset(source)

    manifest = {
        row["episode_index"]: row
        for row in _read_jsonl(Path(result["cleaned_dataset_dir"]) / "meta" / "cleaning_manifest.jsonl")
    }
    assert result["accepted_episode_indices"] == [0, 3]
    assert manifest[1]["decision"] == "rejected"
    assert manifest[1]["reasons"] == ["action_schema_unknown"]


def test_cleaner_trims_only_static_episode_boundaries_at_15hz(tmp_path):
    base = [0.0] * 6
    states = [base[:] for _ in range(15)]
    states.extend([[0.003 * step] + [0.0] * 5 for step in range(1, 31)])
    states.extend([[0.09] + [0.0] * 5 for _ in range(35)])
    source = _write_motion_episode(tmp_path, states=states)

    result = clean_original_dataset(source)

    cleaned = Path(result["cleaned_dataset_dir"])
    frames = _read_jsonl(cleaned / "data" / "episode_000000.jsonl")
    manifest = _read_jsonl(cleaned / "meta" / "cleaning_manifest.jsonl")[0]
    assert len(frames) == 47
    assert frames[0]["frame_index"] == 10
    assert frames[-1]["frame_index"] == 56
    assert manifest["source_frame_count"] == 80
    assert manifest["retained_frame_count"] == 47
    assert manifest["trimmed_leading_frames"] == 10
    assert manifest["trimmed_trailing_frames"] == 23


def test_cleaner_marks_human_success_without_state_motion_for_review(tmp_path):
    source = _write_motion_episode(tmp_path, states=[[0.0] * 6 for _ in range(45)])

    result = clean_original_dataset(source)

    manifest = _read_jsonl(
        Path(result["cleaned_dataset_dir"]) / "meta" / "cleaning_manifest.jsonl"
    )[0]
    assert result["accepted_episode_indices"] == []
    assert result["needs_review_episode_indices"] == [0]
    assert manifest["reasons"] == ["no_state_motion"]


def test_cleaning_defaults_match_the_15hz_capture_contract():
    config = CleaningConfig()

    assert config.target_fps == 15.0
    assert config.max_sync_delta_s == 0.07
    assert config.min_frame_count == 30
