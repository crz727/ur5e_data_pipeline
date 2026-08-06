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

    result = verify_lerobot_export(tmp_path, expected_episode_count=1, expected_cameras=("pano", "wrist"))

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
