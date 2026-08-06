"""Structural verification for official LeRobot exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def verify_lerobot_export(
    output_dir: Path,
    *,
    expected_episode_count: int,
    expected_cameras: Sequence[str],
    visual_storage: str = "video",
) -> dict:
    """Check required official artifacts without rewriting any of them."""
    output_dir = Path(output_dir)
    visual_storage = str(visual_storage).strip().lower()
    if visual_storage not in {"image", "video"}:
        raise ValueError("visual_storage must be image or video")
    issues: list[str] = []
    meta = output_dir / "meta"
    info = _read(meta / "info.json", issues, "missing_meta_info")
    _require_file(meta / "stats.json", issues, "missing_meta_stats")
    if not (meta / "tasks.jsonl").is_file() and not (meta / "tasks.parquet").is_file():
        issues.append("missing_meta_tasks")
    episodes = meta / "episodes"
    if not episodes.is_dir() or not any(path.is_file() for path in episodes.rglob("*")):
        issues.append("missing_meta_episodes")
    if not any(path.is_file() and path.suffix == ".parquet" for path in (output_dir / "data").rglob("*")):
        issues.append("missing_data_files")
    for camera in expected_cameras:
        if visual_storage == "video":
            if not _has_video_data(output_dir, camera):
                issues.append(f"missing_videos:{camera}")
        elif not _has_image_data(output_dir, camera):
            issues.append(f"missing_images:{camera}")
    if isinstance(info, dict):
        total_episodes = info.get("total_episodes")
        if isinstance(total_episodes, int) and total_episodes != int(expected_episode_count):
            issues.append(f"episode_count_mismatch:{total_episodes}!={int(expected_episode_count)}")
    result = {
        "ok": not issues,
        "output_dir": str(output_dir),
        "expected_episode_count": int(expected_episode_count),
        "expected_cameras": list(expected_cameras),
        "visual_storage": visual_storage,
        "issues": issues,
    }
    if meta.is_dir():
        report_path = meta / "data_collection_export_report.json"
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["verification_report_path"] = str(report_path)
    return result


def _require_file(path: Path, issues: list[str], code: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        issues.append(code)


def _read(path: Path, issues: list[str], code: str):
    if not path.is_file() or path.stat().st_size == 0:
        issues.append(code)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append(f"invalid_{path.name}")
        return None


def _has_image_data(output_dir: Path, camera: str) -> bool:
    """Accept legacy image files and LeRobot v3 image bytes in Parquet."""
    image_root = output_dir / "images" / f"observation.images.{camera}"
    if image_root.is_dir() and any(path.is_file() for path in image_root.rglob("*")):
        return True

    column_name = f"observation.images.{camera}"
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return False

    for path in (output_dir / "data").rglob("*.parquet"):
        try:
            parquet = pq.ParquetFile(path)
            if column_name not in parquet.schema_arrow.names:
                continue
            values = parquet.read(columns=[column_name]).column(column_name).to_pylist()
        except Exception:
            continue
        if any(isinstance(value, dict) and value.get("bytes") for value in values):
            return True
    return False


def _has_video_data(output_dir: Path, camera: str) -> bool:
    video_root = output_dir / "videos" / f"observation.images.{camera}"
    return video_root.is_dir() and any(
        path.is_file() and path.suffix.lower() == ".mp4"
        for path in video_root.rglob("*")
    )
