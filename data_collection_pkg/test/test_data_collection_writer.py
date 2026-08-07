import json

import pytest

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.task_annotations import parse_capture_task_annotation


def _observation(timestamp=1.0):
    return {
        "timestamp": timestamp,
        "state": [0.0, -1.0, 1.0, -1.5, -1.2, 0.1, 0.4],
        "qpos": [0.0, -1.0, 1.0, -1.5, -1.2, 0.1],
        "qvel": [0.0] * 6,
        "effort": [0.0] * 6,
        "gripper": 0.4,
        "images": {},
        "safety": {"software_estop": False, "protective_stop": False},
    }


def test_writer_persists_defensive_copied_episode_task_annotation(tmp_path):
    annotation = {
        "task_name": "pick_place_batch_0807",
        "task_id": "pick_red_block_to_blue_tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
        "annotation_source": "capture_ui",
    }
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick_place_batch_0807",
        source="teleop",
        episode_metadata=annotation,
    )
    annotation["task_id"] = "mutated_task_id"
    writer.start_episode()
    writer.add_frame(_observation(), [0.0] * 7)
    writer.close_episode()

    episode = json.loads((writer.meta_dir / "episodes.jsonl").read_text(encoding="utf-8"))
    frame = json.loads((writer.data_dir / "episode_000000.jsonl").read_text(encoding="utf-8"))

    assert episode["task"] == "pick_place_batch_0807"
    assert episode["task_name"] == "pick_place_batch_0807"
    assert episode["task_id"] == "pick_red_block_to_blue_tray"
    assert episode["language_instruction_en"] == "Pick up the red block and place it in the blue tray."
    assert episode["language_instruction_zh"] == "抓取红色方块并放入蓝色托盘。"
    assert episode["annotation_source"] == "capture_ui"
    assert episode["source"] == "teleop"
    assert "language_instruction_en" not in frame["metadata"]
    assert "language_instruction_zh" not in frame["metadata"]


def test_capture_task_annotation_normalizes_and_validates_capture_inputs():
    annotation = parse_capture_task_annotation(
        task_name="pick_place_batch_0807",
        task_id="PICK-RED-BLOCK-TO-BLUE-TRAY",
        english=" Pick up the red block\n and place it in the blue tray. ",
        chinese=" 抓取红色方块并放入蓝色托盘。 ",
    )

    assert annotation == {
        "task_name": "pick_place_batch_0807",
        "task_id": "pick-red-block-to-blue-tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
        "annotation_source": "capture_ui",
    }


def test_capture_task_annotation_keeps_empty_language_fields_for_act_capture():
    annotation = parse_capture_task_annotation(
        task_name="pick_place_batch_0807",
        task_id="pick-red-block-to-blue-tray",
        english="",
        chinese="",
    )

    assert annotation["language_instruction_en"] == ""
    assert annotation["language_instruction_zh"] == ""


def test_capture_task_annotation_rejects_invalid_supplied_task_id():
    with pytest.raises(ValueError, match="task_id"):
        parse_capture_task_annotation(
            task_name="pick_place_batch_0807",
            task_id="pick/red-block",
            english="Pick up the red block.",
            chinese="",
        )


def test_writer_stores_original_qpos_schema_under_runtime_mode_directory(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
        converted_from="model/action",
    )
    episode = writer.start_episode()
    writer.add_frame(_observation(), [0.1, -1.1, 1.1, -1.4, -1.1, 0.2, 0.8])
    writer.close_episode()

    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"

    assert episode.index == 0
    assert frame_path.exists()
    assert metadata_path.exists()

    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    assert frame["observation"]["state"] == [0.0, -1.0, 1.0, -1.5, -1.2, 0.1, 0.4]
    assert frame["action"] == [0.1, -1.1, 1.1, -1.4, -1.1, 0.2, 0.8]
    assert frame["metadata"]["source"] == "teleop"
    assert frame["metadata"]["dataset_stage"] == "original"

    metadata = json.loads(metadata_path.read_text(encoding="utf-8").strip())
    assert metadata["category"] == "original"
    assert metadata["runtime_mode"] == "teleop"
    assert metadata["dataset_stage"] == "original"
    assert metadata["action_schema"] == "qpos_gripper"
    assert metadata["source"] == "teleop"
    assert metadata["converted_from"] == "model/action"


def test_writer_rejects_wrong_action_dimension(tmp_path):
    writer = JsonlDatasetWriter(tmp_path, "qpos_gripper", task="pick", source="teleop")
    writer.start_episode()

    with pytest.raises(ValueError, match="qpos_gripper expects 7 values"):
        writer.add_frame(_observation(), [0.0] * 6)


def test_writer_externalizes_raw_image_payloads(tmp_path):
    observation = _observation()
    observation["images"] = {
        "external": {
            "timestamp": 1.0,
            "height": 2,
            "width": 2,
            "encoding": "rgb8",
            "step": 6,
            "data": [0, 1, 2, 3, 4, 5],
        }
    }
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(observation, [0.0] * 7)
    writer.close_episode()

    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    image = frame["observation"]["images"]["external"]

    assert "data" not in image
    assert image["data_path"] == "images/episode_000000/external/frame_000000.bin"
    assert image["byte_length"] == 6
    assert (dataset_dir / image["data_path"]).read_bytes() == bytes([0, 1, 2, 3, 4, 5])


def test_writer_compresses_rgb8_images_to_jpeg_when_enabled(tmp_path):
    observation = _observation()
    observation["images"] = {
        "external": {
            "timestamp": 1.0,
            "height": 2,
            "width": 2,
            "encoding": "rgb8",
            "step": 6,
            "data": [255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255],
        }
    }
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
        image_storage_format="jpeg",
        jpeg_quality=80,
    )
    writer.start_episode()
    writer.add_frame(observation, [0.0] * 7)
    writer.close_episode()

    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    image = frame["observation"]["images"]["external"]

    assert image["codec"] == "jpeg"
    assert image["data_path"].endswith(".jpg")
    assert (dataset_dir / image["data_path"]).read_bytes().startswith(b"\xff\xd8")


def test_writer_stores_compressed_jpeg_bytes_without_reencoding(tmp_path):
    jpeg = b"\xff\xd8already-compressed\xff\xd9"
    observation = _observation()
    observation["images"] = {
        "external": {
            "timestamp": 1.0,
            "transport": "compressed",
            "codec": "jpeg",
            "format": "jpeg",
            "data": jpeg,
        }
    }
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(observation, [0.0] * 7)
    writer.close_episode()

    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = json.loads(frame_path.read_text(encoding="utf-8").strip())
    image = frame["observation"]["images"]["external"]

    assert image["codec"] == "jpeg"
    assert image["data_path"].endswith(".jpg")
    assert (dataset_dir / image["data_path"]).read_bytes() == jpeg
