import json

import pyarrow as pa
import pyarrow.parquet as pq

from data_collection_pkg.dataset.lerobot_verify import verify_lerobot_export


def test_export_verifier_reports_missing_official_artifacts(tmp_path):
    result = verify_lerobot_export(
        tmp_path,
        expected_episode_count=1,
        expected_cameras=("pano", "wrist"),
    )

    assert result["ok"] is False
    assert "missing_meta_info" in result["issues"]
    assert "missing_meta_stats" in result["issues"]
    assert "missing_data_files" in result["issues"]
    assert "missing_videos:pano" in result["issues"]


def test_export_verifier_accepts_complete_official_artifact_tree(tmp_path):
    meta = tmp_path / "meta"
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    (tmp_path / "data" / "chunk-000").mkdir(parents=True)
    (tmp_path / "videos" / "observation.images.pano" / "chunk-000").mkdir(parents=True)
    (tmp_path / "videos" / "observation.images.wrist" / "chunk-000").mkdir(parents=True)
    (meta / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (meta / "stats.json").write_text("{}", encoding="utf-8")
    (meta / "tasks.jsonl").write_text(json.dumps({"task_index": 0}) + "\n", encoding="utf-8")
    (meta / "episodes" / "chunk-000" ).joinpath("file-000.parquet").write_bytes(b"parquet")
    (tmp_path / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"parquet")
    for camera in ("pano", "wrist"):
        (tmp_path / "videos" / f"observation.images.{camera}" / "chunk-000" / "file-000.mp4").write_bytes(b"video")
    (meta / "image_normalization.json").write_text(json.dumps({
        "input": "uint8_rgb",
        "conversion": "float32_rgb_0_to_1",
        "normalization": "imagenet_rgb",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "applies_to": ["observation.images.pano", "observation.images.wrist"],
    }), encoding="utf-8")

    result = verify_lerobot_export(
        tmp_path,
        expected_episode_count=1,
        expected_cameras=("pano", "wrist"),
        require_image_normalization=True,
    )

    assert result["ok"] is True
    assert result["issues"] == []


def test_export_verifier_rejects_images_embedded_in_parquet_for_video_mode(tmp_path):
    meta = tmp_path / "meta"
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    data = tmp_path / "data" / "chunk-000"
    data.mkdir(parents=True)
    (meta / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (meta / "stats.json").write_text("{}", encoding="utf-8")
    (meta / "tasks.parquet").write_bytes(b"tasks")
    (meta / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(b"episodes")
    pq.write_table(
        pa.table({
            "observation.images.pano": [{"bytes": b"pano", "path": "frame-000000.png"}],
            "observation.images.wrist": [{"bytes": b"wrist", "path": "frame-000000.png"}],
        }),
        data / "file-000.parquet",
    )

    result = verify_lerobot_export(tmp_path, expected_episode_count=1, expected_cameras=("pano", "wrist"))

    assert result["ok"] is False
    assert "missing_videos:pano" in result["issues"]
    assert "missing_videos:wrist" in result["issues"]


def test_export_verifier_requires_exact_normalization_and_vla_metadata(tmp_path):
    meta = tmp_path / "meta"
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    (tmp_path / "data" / "chunk-000").mkdir(parents=True)
    for camera in ("top", "wrist"):
        (tmp_path / "videos" / f"observation.images.{camera}" / "chunk-000").mkdir(parents=True)
        (tmp_path / "videos" / f"observation.images.{camera}" / "chunk-000" / "file-000.mp4").write_bytes(b"video")
    (meta / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (meta / "stats.json").write_text("{}", encoding="utf-8")
    (meta / "tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (meta / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(b"episodes")
    (tmp_path / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"data")
    (meta / "image_normalization.json").write_text(json.dumps({
        "input": "uint8_rgb",
        "conversion": "float32_rgb_0_to_1",
        "normalization": "imagenet_rgb",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 999],
        "applies_to": ["observation.images.top", "observation.images.wrist"],
    }), encoding="utf-8")

    result = verify_lerobot_export(
        tmp_path,
        expected_episode_count=1,
        expected_cameras=("top", "wrist"),
        profile="vla",
        require_image_normalization=True,
    )

    assert result["ok"] is False
    assert "invalid_image_normalization" in result["issues"]
    assert "missing_vla_export_report" in result["issues"]
    assert "missing_episode_language_annotations" in result["issues"]


def test_export_verifier_rejects_count_correct_but_malformed_vla_metadata(tmp_path):
    meta = tmp_path / "meta"
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    (tmp_path / "data" / "chunk-000").mkdir(parents=True)
    for camera in ("top", "wrist"):
        camera_dir = tmp_path / "videos" / f"observation.images.{camera}" / "chunk-000"
        camera_dir.mkdir(parents=True)
        (camera_dir / "file-000.mp4").write_bytes(b"video")
    (meta / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (meta / "stats.json").write_text("{}", encoding="utf-8")
    (meta / "tasks.jsonl").write_text("{}\n", encoding="utf-8")
    (meta / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(b"episodes")
    (tmp_path / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"data")
    (meta / "image_normalization.json").write_text(json.dumps({
        "input": "uint8_rgb",
        "conversion": "float32_rgb_0_to_1",
        "normalization": "imagenet_rgb",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "applies_to": ["observation.images.top", "observation.images.wrist"],
    }), encoding="utf-8")
    (meta / "vla_export_report.json").write_text(json.dumps({
        "source": "",
        "profile": "vla",
        "eligible_source_episode_indices": [10],
        "source_to_output_episode_mapping": {"999": 0},
        "skipped": "none",
        "exported_at": "",
    }), encoding="utf-8")
    (meta / "episode_language_annotations.jsonl").write_text("{}\n", encoding="utf-8")

    result = verify_lerobot_export(
        tmp_path,
        expected_episode_count=1,
        expected_cameras=("top", "wrist"),
        profile="vla",
        require_image_normalization=True,
    )

    assert result["ok"] is False
    assert "invalid_vla_export_report" in result["issues"]
    assert "invalid_episode_language_annotations" in result["issues"]

    (meta / "vla_export_report.json").write_text(json.dumps({
        "source": "/cleaned/policy/qpos_gripper",
        "profile": "vla",
        "eligible_source_episode_indices": [10],
        "source_to_output_episode_mapping": {"10": 0},
        "skipped": [{"episode_index": 11, "reason": "missing_english_instruction"}],
        "exported_at": "2026-08-07T12:00:00+00:00",
    }), encoding="utf-8")
    (meta / "episode_language_annotations.jsonl").write_text(json.dumps({
        "output_episode_index": 0,
        "source_episode_index": 10,
        "task_id": "pick_red_block",
        "language_instruction_en": "Pick up the red block.",
        "language_instruction_zh": "抓取红色方块。",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    valid = verify_lerobot_export(
        tmp_path,
        expected_episode_count=1,
        expected_cameras=("top", "wrist"),
        profile="vla",
        require_image_normalization=True,
    )

    assert valid["ok"] is True
    assert valid["issues"] == []
