"""Structural verification for official LeRobot exports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from data_collection_pkg.dataset.task_annotations import validate_vla_english_instruction


def verify_lerobot_export(
    output_dir: Path,
    *,
    expected_episode_count: int,
    expected_cameras: Sequence[str],
    visual_storage: str = "video",
    profile: str = "act",
    require_image_normalization: bool = False,
) -> dict:
    """Check required official artifacts without rewriting any of them."""
    output_dir = Path(output_dir)
    visual_storage = str(visual_storage).strip().lower()
    if visual_storage not in {"image", "video"}:
        raise ValueError("visual_storage must be image or video")
    profile = str(profile).strip().lower()
    if profile not in {"act", "vla"}:
        raise ValueError("profile must be act or vla")
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
    if require_image_normalization:
        normalization = _read(
            meta / "image_normalization.json",
            issues,
            "missing_image_normalization",
        )
        expected_normalization = {
            "input": "uint8_rgb",
            "conversion": "float32_rgb_0_to_1",
            "normalization": "imagenet_rgb",
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
            "applies_to": [f"observation.images.{camera}" for camera in expected_cameras],
        }
        if normalization is not None and normalization != expected_normalization:
            issues.append("invalid_image_normalization")
    if profile == "vla":
        report = _read(meta / "vla_export_report.json", issues, "missing_vla_export_report")
        annotations = _read_jsonl(
            meta / "episode_language_annotations.jsonl",
            issues,
            "missing_episode_language_annotations",
        )
        eligible = _valid_vla_report(report, int(expected_episode_count))
        if report is not None and eligible is None:
            issues.append("invalid_vla_export_report")
        if annotations is not None:
            if len(annotations) != int(expected_episode_count):
                issues.append("episode_language_annotation_count_mismatch")
            elif not _valid_language_annotations(annotations, eligible):
                issues.append("invalid_episode_language_annotations")
    result = {
        "ok": not issues,
        "output_dir": str(output_dir),
        "expected_episode_count": int(expected_episode_count),
        "expected_cameras": list(expected_cameras),
        "visual_storage": visual_storage,
        "profile": profile,
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


def _read_jsonl(path: Path, issues: list[str], code: str):
    if not path.is_file() or path.stat().st_size == 0:
        issues.append(code)
        return None
    rows = []
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        issues.append(f"invalid_{path.name}")
        return None
    return rows


def _valid_vla_report(report, expected_episode_count: int) -> list[int] | None:
    if not isinstance(report, Mapping):
        return None
    eligible = report.get("eligible_source_episode_indices")
    mapping = report.get("source_to_output_episode_mapping")
    skipped = report.get("skipped")
    exported_at = report.get("exported_at")
    if not isinstance(report.get("source"), str) or not report["source"].strip():
        return None
    if report.get("profile") != "vla":
        return None
    if (
        not isinstance(eligible, list)
        or len(eligible) != expected_episode_count
        or any(not isinstance(index, int) or isinstance(index, bool) for index in eligible)
        or len(set(eligible)) != len(eligible)
    ):
        return None
    if mapping != {str(source_index): output_index for output_index, source_index in enumerate(eligible)}:
        return None
    if not isinstance(skipped, list) or any(
        not isinstance(item, Mapping)
        or not isinstance(item.get("episode_index"), int)
        or isinstance(item.get("episode_index"), bool)
        or not isinstance(item.get("reason"), str)
        or not item["reason"].strip()
        for item in skipped
    ):
        return None
    if any(item["episode_index"] in set(eligible) for item in skipped):
        return None
    if not isinstance(exported_at, str) or not exported_at.strip():
        return None
    try:
        datetime.fromisoformat(exported_at)
    except ValueError:
        return None
    return eligible


def _valid_language_annotations(annotations: list, eligible: list[int] | None) -> bool:
    for output_index, annotation in enumerate(annotations):
        if not isinstance(annotation, Mapping):
            return False
        if annotation.get("output_episode_index") != output_index:
            return False
        source_index = annotation.get("source_episode_index")
        if not isinstance(source_index, int) or isinstance(source_index, bool):
            return False
        if eligible is not None and source_index != eligible[output_index]:
            return False
        if not isinstance(annotation.get("task_id"), str):
            return False
        english = annotation.get("language_instruction_en")
        if not isinstance(english, str) or validate_vla_english_instruction(english) is not None:
            return False
        if not isinstance(annotation.get("language_instruction_zh"), str):
            return False
    return True


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
