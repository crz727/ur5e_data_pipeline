import json
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from data_collection_pkg.dataset.converter import convert_jsonl_to_lerobot
from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter


class FakeLeRobotDataset:
    created = None

    def __init__(self):
        self.frames = []
        self.saved = 0
        self.finalized = False

    @classmethod
    def create(cls, **kwargs):
        cls.created = kwargs
        return cls()

    def add_frame(self, frame):
        self.frames.append(frame)

    def save_episode(self):
        self.saved += 1

    def finalize(self):
        self.finalized = True


def _write_qpos_dataset(dataset_dir, *, stage):
    (dataset_dir / "meta").mkdir(parents=True)
    (dataset_dir / "data").mkdir()
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "task": "pick red block",
            "action_schema": "qpos_gripper",
            "frame_count": 1,
            "data_path": "data/episode_000000.jsonl",
            "dataset_stage": stage,
        }) + "\n",
        encoding="utf-8",
    )
    (dataset_dir / "data" / "episode_000000.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "frame_index": 0,
            "timestamp": 1.0,
            "observation": {
                "timestamp": 1.0,
                "state": [0.0] * 7,
                "images": {
                    "external": {"data": [[[0, 0, 0]]]},
                    "wrist": {"data": [[[1, 1, 1]]]},
                },
            },
            "action": [0.0] * 7,
        }) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_converter_requires_cleaned_qpos_input_and_uses_direct_output_dir(tmp_path):
    original = tmp_path / "original" / "teleop" / "qpos_gripper"
    cleaned = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    _write_qpos_dataset(original, stage="original")
    _write_qpos_dataset(cleaned, stage="cleaned")

    with pytest.raises(ValueError, match="cleaned"):
        convert_jsonl_to_lerobot(
            original,
            output_dir=tmp_path / "must_not_export",
            dataset_cls=FakeLeRobotDataset,
        )

    summary = convert_jsonl_to_lerobot(
        cleaned,
        output_dir=tmp_path / "arbitrary_export_name",
        repo_id="lab/unrelated-logical-name",
        cameras=(("pano", "external"), ("wrist", "wrist")),
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary["output_dir"] == str(tmp_path / "arbitrary_export_name")
    assert FakeLeRobotDataset.created["root"] == tmp_path / "arbitrary_export_name"
    assert FakeLeRobotDataset.created["repo_id"] == "lab/unrelated-logical-name"
    assert "observation.images.pano" in FakeLeRobotDataset.created["features"]
    frame = FakeLeRobotDataset.created["dataset"].frames[0]
    assert "observation.images.pano" in frame
    assert "observation.images.external" not in frame


def test_convert_jsonl_dataset_to_official_lerobot_writer(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    _write_qpos_dataset(dataset_dir, stage="cleaned")

    summary = convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=tmp_path / "official",
        repo_id="local/teleop_pick",
        cameras=("wrist",),
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary == {
        "episode_count": 1,
        "frame_count": 1,
        "schema_name": "qpos_gripper",
        "repo_id": "local/teleop_pick",
        "output_dir": str(tmp_path / "official"),
    }
    assert FakeLeRobotDataset.created["root"] == tmp_path / "official"
    frame = FakeLeRobotDataset.created["dataset"].frames[0]
    assert "timestamp" not in frame
    assert np.allclose(frame["action"], np.zeros(7))
    assert "observation.images.wrist" in frame


def test_convert_infers_square_raw_image_shape(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    _write_qpos_dataset(dataset_dir, stage="cleaned")
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = _read_jsonl(frame_path)[0]
    frame["observation"]["images"] = {
        "external": {"format": "raw", "data": [0] * 192},
        "wrist": {"format": "raw", "data": [1] * 192},
    }
    frame_path.write_text(json.dumps(frame) + "\n", encoding="utf-8")

    convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=tmp_path / "official",
        repo_id="local/teleop_pick",
        cameras=("external", "wrist"),
        dataset_cls=FakeLeRobotDataset,
    )

    features = FakeLeRobotDataset.created["features"]
    frame = FakeLeRobotDataset.created["dataset"].frames[0]

    assert features["observation.images.external"]["shape"] == (8, 8, 3)
    assert features["observation.images.wrist"]["shape"] == (8, 8, 3)
    assert frame["observation.images.external"].shape == (8, 8, 3)
    assert frame["observation.images.wrist"].shape == (8, 8, 3)


def test_convert_infers_compressed_jpeg_dimensions(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    _write_qpos_dataset(dataset_dir, stage="cleaned")
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color=(10, 20, 30)).save(buffer, format="JPEG")
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = _read_jsonl(frame_path)[0]
    payload = {"codec": "jpeg", "height": 0, "width": 0, "data": list(buffer.getvalue())}
    frame["observation"]["images"] = {"external": payload, "wrist": payload}
    frame_path.write_text(json.dumps(frame) + "\n", encoding="utf-8")

    convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=tmp_path / "official",
        cameras=("external", "wrist"),
        dataset_cls=FakeLeRobotDataset,
    )

    assert FakeLeRobotDataset.created["features"]["observation.images.external"]["shape"] == (2, 3, 3)


def test_convert_infers_and_decodes_external_compressed_jpeg(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    _write_qpos_dataset(dataset_dir, stage="cleaned")
    buffer = BytesIO()
    Image.new("RGB", (5, 4), color=(10, 20, 30)).save(buffer, format="JPEG")
    image_path = dataset_dir / "images" / "episode_000000" / "external" / "frame_000000.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(buffer.getvalue())
    frame_path = dataset_dir / "data" / "episode_000000.jsonl"
    frame = _read_jsonl(frame_path)[0]
    external = {
        "codec": "jpeg",
        "height": 0,
        "width": 0,
        "byte_length": len(buffer.getvalue()),
        "data_path": str(image_path.relative_to(dataset_dir)),
    }
    frame["observation"]["images"] = {"external": external, "wrist": external}
    frame_path.write_text(json.dumps(frame) + "\n", encoding="utf-8")

    convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=tmp_path / "official",
        cameras=("external", "wrist"),
        dataset_cls=FakeLeRobotDataset,
    )

    features = FakeLeRobotDataset.created["features"]
    written = FakeLeRobotDataset.created["dataset"].frames[0]
    assert features["observation.images.external"]["shape"] == (4, 5, 3)
    assert written["observation.images.external"].shape == (4, 5, 3)


def test_convert_rejects_mixed_schema_metadata(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    (dataset_dir / "meta").mkdir(parents=True)
    (dataset_dir / "data").mkdir()
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "task": "a",
            "action_schema": "qpos_gripper",
            "data_path": "data/episode_000000.jsonl",
        }) + "\n"
        + json.dumps({
            "episode_index": 1,
            "task": "b",
            "action_schema": "teleop_servo_l_pose",
            "data_path": "data/episode_000001.jsonl",
        }) + "\n",
        encoding="utf-8",
    )

    try:
        convert_jsonl_to_lerobot(
            dataset_dir,
            output_root=tmp_path / "official",
            repo_id="local/mixed",
            dataset_cls=FakeLeRobotDataset,
        )
    except ValueError as exc:
        assert "one action_schema" in str(exc)
    else:
        raise AssertionError("expected mixed schema metadata to fail")
