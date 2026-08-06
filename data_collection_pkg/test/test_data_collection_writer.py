import json

import pytest

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter


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
