import json
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from data_collection_pkg.dataset import converter as converter_module
from data_collection_pkg.dataset.converter import convert_jsonl_to_lerobot
from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.lerobot_verify import verify_lerobot_export


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


def _write_profile_dataset(dataset_dir):
    (dataset_dir / "meta").mkdir(parents=True)
    (dataset_dir / "data").mkdir()
    episodes = [
        {
            "episode_index": 10,
            "task": "capture batch",
            "task_id": "pick_red_block",
            "language_instruction_en": "  Pick up   the red block. ",
            "language_instruction_zh": "抓取红色方块。",
        },
        {
            "episode_index": 11,
            "task": "capture batch",
            "task_id": "pick_blue_block",
            "language_instruction_en": "",
            "language_instruction_zh": "抓取蓝色方块。",
        },
        {
            "episode_index": 12,
            "task": "capture batch",
            "task_id": "place_green_block",
        },
    ]
    metadata_rows = []
    for offset, episode in enumerate(episodes):
        data_path = f"data/episode_{episode['episode_index']:06d}.jsonl"
        metadata_rows.append({
            **episode,
            "action_schema": "qpos_gripper",
            "frame_count": 1,
            "data_path": data_path,
            "dataset_stage": "cleaned",
        })
        (dataset_dir / data_path).write_text(
            json.dumps({
                "episode_index": episode["episode_index"],
                "frame_index": 0,
                "timestamp": offset / 15.0,
                "observation": {
                    "timestamp": offset / 15.0,
                    "state": [float(offset)] * 7,
                    "images": {
                        "external": {"data": [[[offset, 0, 0]]]},
                        "wrist": {"data": [[[0, offset, 0]]]},
                    },
                },
                "action": [float(offset + 1)] * 7,
            }) + "\n",
            encoding="utf-8",
        )
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in metadata_rows),
        encoding="utf-8",
    )


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
        "source_episode_count": 1,
        "skipped_count": 0,
        "frame_count": 1,
        "schema_name": "qpos_gripper",
        "repo_id": "local/teleop_pick",
        "output_dir": str(tmp_path / "official"),
        "profile": "act",
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


def test_act_profile_exports_every_episode_with_task_id_and_default_camera_mapping(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "act"
    _write_profile_dataset(dataset_dir)

    summary = convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=output_dir,
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary["profile"] == "act"
    assert summary["episode_count"] == 3
    assert summary["skipped_count"] == 0
    assert FakeLeRobotDataset.created["fps"] == 15
    assert FakeLeRobotDataset.created["robot_type"] == "ur5e"
    assert FakeLeRobotDataset.created["features"]["observation.state"]["shape"] == (7,)
    assert FakeLeRobotDataset.created["features"]["action"]["shape"] == (7,)
    assert [frame["task"] for frame in FakeLeRobotDataset.created["dataset"].frames] == [
        "pick_red_block",
        "pick_blue_block",
        "place_green_block",
    ]
    assert "observation.images.top" in FakeLeRobotDataset.created["features"]
    assert "observation.images.wrist" in FakeLeRobotDataset.created["features"]
    normalization = json.loads((output_dir / "meta" / "image_normalization.json").read_text())
    assert normalization == {
        "input": "uint8_rgb",
        "conversion": "float32_rgb_0_to_1",
        "normalization": "imagenet_rgb",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "applies_to": ["observation.images.top", "observation.images.wrist"],
    }


def test_vla_profile_exports_only_valid_english_and_writes_audit_metadata(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "vla"
    _write_profile_dataset(dataset_dir)

    preflight = converter_module.preflight_jsonl_to_lerobot(dataset_dir, "vla")
    assert [row["episode_index"] for row in preflight["eligible"]] == [10]
    assert preflight["eligible"][0]["task"] == "Pick up the red block."
    assert preflight["skipped"] == [
        {"episode_index": 11, "reason": "missing_english_instruction"},
        {"episode_index": 12, "reason": "missing_english_instruction"},
    ]

    summary = convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=output_dir,
        profile="vla",
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary["profile"] == "vla"
    assert summary["episode_count"] == 1
    assert summary["skipped_count"] == 2
    assert [frame["task"] for frame in FakeLeRobotDataset.created["dataset"].frames] == [
        "Pick up the red block."
    ]
    report = json.loads((output_dir / "meta" / "vla_export_report.json").read_text())
    assert report["source"] == str(dataset_dir)
    assert report["profile"] == "vla"
    assert report["eligible_source_episode_indices"] == [10]
    assert report["source_to_output_episode_mapping"] == {"10": 0}
    assert report["skipped"] == preflight["skipped"]
    assert report["exported_at"]
    annotations = _read_jsonl(output_dir / "meta" / "episode_language_annotations.jsonl")
    assert annotations == [{
        "output_episode_index": 0,
        "source_episode_index": 10,
        "task_id": "pick_red_block",
        "language_instruction_en": "Pick up the red block.",
        "language_instruction_zh": "抓取红色方块。",
    }]
    assert (output_dir / "meta" / "image_normalization.json").is_file()


def test_vla_profile_with_no_eligible_episode_writes_report_without_dataset(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "vla"
    _write_profile_dataset(dataset_dir)
    rows = _read_jsonl(dataset_dir / "meta" / "episodes.jsonl")
    rows[0]["language_instruction_en"] = "episode-010"
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    FakeLeRobotDataset.created = None

    with pytest.raises(ValueError, match="no eligible episodes"):
        convert_jsonl_to_lerobot(
            dataset_dir,
            output_dir=output_dir,
            profile="vla",
            dataset_cls=FakeLeRobotDataset,
        )

    report = json.loads((output_dir / "meta" / "vla_export_report.json").read_text())
    assert report["eligible_source_episode_indices"] == []
    assert report["skipped"] == [
        {"episode_index": 10, "reason": "invalid_english_instruction"},
        {"episode_index": 11, "reason": "missing_english_instruction"},
        {"episode_index": 12, "reason": "missing_english_instruction"},
    ]
    assert FakeLeRobotDataset.created is None
    assert not (output_dir / "data").exists()


def test_vla_profile_audits_and_skips_valid_language_episode_with_corrupt_frames(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "vla"
    _write_profile_dataset(dataset_dir)
    rows = _read_jsonl(dataset_dir / "meta" / "episodes.jsonl")
    corrupt = {
        "episode_index": 13,
        "task": "capture batch",
        "task_id": "move_yellow_block",
        "language_instruction_en": "Move the yellow block.",
        "language_instruction_zh": "移动黄色方块。",
        "action_schema": "qpos_gripper",
        "frame_count": 1,
        "data_path": "data/episode_000013.jsonl",
        "dataset_stage": "cleaned",
    }
    rows.insert(1, corrupt)
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    (dataset_dir / corrupt["data_path"]).write_text(json.dumps({
        "episode_index": 13,
        "frame_index": 0,
        "observation": {
            "state": [0.0] * 6,
            "images": {
                "external": {"data": [[[0, 0, 0]]]},
                "wrist": {"data": [[[0, 0, 0]]]},
            },
        },
        "action": [0.0] * 7,
    }) + "\n", encoding="utf-8")

    summary = convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=output_dir,
        profile="vla",
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary["episode_count"] == 1
    assert summary["source_episode_count"] == 4
    assert summary["skipped_count"] == 3
    report = json.loads((output_dir / "meta" / "vla_export_report.json").read_text())
    assert report["skipped"] == [
        {"episode_index": 11, "reason": "missing_english_instruction"},
        {"episode_index": 12, "reason": "missing_english_instruction"},
        {
            "episode_index": 13,
            "reason": "data_integrity_conversion_error",
            "error": "observation.state must contain 7 values",
        },
    ]
    assert [frame["task"] for frame in FakeLeRobotDataset.created["dataset"].frames] == [
        "Pick up the red block."
    ]


def test_vla_profile_accounts_for_all_sources_when_first_image_payload_is_malformed(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "vla"
    _write_profile_dataset(dataset_dir)
    rows = _read_jsonl(dataset_dir / "meta" / "episodes.jsonl")[:2]
    rows[1].update({
        "episode_index": 20,
        "task_id": "pick_blue_block",
        "language_instruction_en": "Pick up the blue block.",
        "language_instruction_zh": "抓取蓝色方块。",
    })
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    first_frame_path = dataset_dir / rows[0]["data_path"]
    first_frame = _read_jsonl(first_frame_path)[0]
    first_frame["observation"]["images"]["external"] = "not-an-image"
    first_frame_path.write_text(json.dumps(first_frame) + "\n", encoding="utf-8")

    summary = convert_jsonl_to_lerobot(
        dataset_dir,
        output_dir=output_dir,
        profile="vla",
        dataset_cls=FakeLeRobotDataset,
    )

    assert summary["episode_count"] == 1
    assert summary["source_episode_count"] == 2
    assert summary["skipped_count"] == 1
    report = json.loads((output_dir / "meta" / "vla_export_report.json").read_text())
    assert report["eligible_source_episode_indices"] == [20]
    assert report["source_to_output_episode_mapping"] == {"20": 0}
    assert report["skipped"] == [{
        "episode_index": 10,
        "reason": "data_integrity_conversion_error",
        "error": "invalid image payload: external",
    }]
    annotations = _read_jsonl(output_dir / "meta" / "episode_language_annotations.jsonl")
    assert [row["source_episode_index"] for row in annotations] == [20]

    meta = output_dir / "meta"
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    (output_dir / "data" / "chunk-000").mkdir(parents=True)
    (meta / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (meta / "stats.json").write_text("{}", encoding="utf-8")
    (meta / "tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (meta / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(b"episodes")
    (output_dir / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"data")
    for camera in ("top", "wrist"):
        camera_dir = output_dir / "videos" / f"observation.images.{camera}" / "chunk-000"
        camera_dir.mkdir(parents=True)
        (camera_dir / "file-000.mp4").write_bytes(b"video")

    verification = verify_lerobot_export(
        output_dir,
        expected_episode_count=1,
        expected_cameras=("top", "wrist"),
        profile="vla",
        require_image_normalization=True,
    )
    assert verification["ok"] is True
    assert verification["issues"] == []


def test_image_normalization_metadata_does_not_rewrite_measured_stats(tmp_path):
    meta = tmp_path / "meta"
    meta.mkdir()
    stats = '{"observation.state": {"mean": [9.0]}}\n'
    (meta / "stats.json").write_text(stats, encoding="utf-8")

    path = converter_module.write_image_normalization_metadata(tmp_path, ("top", "wrist"))

    assert path == meta / "image_normalization.json"
    assert (meta / "stats.json").read_text(encoding="utf-8") == stats


def test_converter_rejects_existing_output_directory_before_creating_lerobot_dataset(tmp_path):
    dataset_dir = tmp_path / "cleaned" / "policy" / "qpos_gripper"
    output_dir = tmp_path / "lerobot"
    _write_profile_dataset(dataset_dir)
    output_dir.mkdir()
    FakeLeRobotDataset.created = None

    with pytest.raises(ValueError, match="output directory already exists"):
        convert_jsonl_to_lerobot(
            dataset_dir,
            output_dir=output_dir,
            profile="act",
            dataset_cls=FakeLeRobotDataset,
        )

    assert FakeLeRobotDataset.created is None
