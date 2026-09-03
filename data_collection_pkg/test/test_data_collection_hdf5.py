import json

import h5py
import numpy as np
from PIL import Image

from data_collection_pkg.dataset.hdf5_converter import convert_jsonl_to_hdf5
from data_collection_pkg.dataset.hdf5_verify import verify_hdf5_export


def _write_cleaned_dataset(tmp_path, *, optional=True):
    dataset = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    (dataset / "data").mkdir(parents=True)
    (dataset / "images" / "episode_000000" / "external").mkdir(parents=True)
    (dataset / "images" / "episode_000000" / "wrist").mkdir(parents=True)
    rows = []
    for frame_index in range(2):
        for camera in ("external", "wrist"):
            image = Image.new("RGB", (2, 2), (frame_index * 20, 30, 40))
            image.save(dataset / "images" / "episode_000000" / camera / f"frame_{frame_index:06d}.png")
        observation = {
            "timestamp": 10.0 + frame_index / 15.0,
            "state": [float(frame_index)] * 7,
            "images": {
                camera: {
                    "storage": "external",
                    "codec": "png",
                    "data_path": f"images/episode_000000/{camera}/frame_{frame_index:06d}.png",
                }
                for camera in ("external", "wrist")
            },
        }
        if optional:
            observation.update({
                "ee_pose": [0.1] * 7,
                "qvel": [0.2] * 6,
                "effort": [0.3] * 6,
            })
        rows.append({
            "episode_index": 0,
            "frame_index": frame_index,
            "timestamp": observation["timestamp"],
            "observation": observation,
            "action": [0.4] * 7,
        })
    data_path = dataset / "data" / "episode_000000.jsonl"
    data_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    (dataset / "meta").mkdir()
    (dataset / "meta" / "episodes.jsonl").write_text(json.dumps({
        "episode_index": 0,
        "task": "pick red block",
        "task_id": "pick-red-block",
        "language_instruction_en": "Pick up the red block.",
        "language_instruction_zh": "抓取红色方块。",
        "action_schema": "qpos_gripper",
        "frame_count": 2,
        "data_path": "data/episode_000000.jsonl",
    }) + "\n", encoding="utf-8")
    return dataset


def test_hdf5_export_streams_rgb_and_preserves_optional_observations(tmp_path):
    dataset = _write_cleaned_dataset(tmp_path)
    output = tmp_path / "exports" / "dataset.hdf5"

    result = convert_jsonl_to_hdf5(dataset, output)

    assert result["ok"] is True
    assert result["episode_count"] == 1
    with h5py.File(output, "r") as handle:
        episode = handle["episodes/episode_000000"]
        assert episode["observations/state"].shape == (2, 7)
        assert episode["actions"].shape == (2, 7)
        assert episode["observations/images/top"].shape == (2, 2, 2, 3)
        assert episode["observations/ee_pose"].shape == (2, 7)
        assert episode["observations/joint_velocity"].shape == (2, 6)
        assert episode["observations/effort"].shape == (2, 6)
        assert episode.attrs["language_instruction_en"] == "Pick up the red block."


def test_hdf5_verifier_accepts_export_and_rejects_missing_required_dataset(tmp_path):
    dataset = _write_cleaned_dataset(tmp_path)
    output = tmp_path / "dataset.hdf5"
    convert_jsonl_to_hdf5(dataset, output)

    verified = verify_hdf5_export(output, expected_episode_count=1)
    assert verified["ok"] is True
    assert verified["issues"] == []

    with h5py.File(output, "a") as handle:
        del handle["episodes/episode_000000/actions"]
    invalid = verify_hdf5_export(output, expected_episode_count=1)
    assert invalid["ok"] is False
    assert "missing_required_dataset:episodes/episode_000000/actions" in invalid["issues"]
