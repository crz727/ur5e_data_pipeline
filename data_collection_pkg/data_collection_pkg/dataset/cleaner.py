"""Auditable offline cleaning for fixed-rate original qpos datasets."""

from __future__ import annotations

import copy
import html
import json
import math
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from data_collection_pkg.dataset.quality import QualityConfig, check_frame
from data_collection_pkg.dataset.schemas import get_schema


@dataclass(frozen=True)
class CleaningConfig:
    """Conservative, configurable quality gates for trainable demonstrations."""

    required_cameras: tuple[str, ...] = ("external", "wrist")
    max_sync_delta_s: float = 0.02
    target_fps: float = 30.0
    fps_tolerance_ratio: float = 0.3
    min_frame_count: int = 30
    min_duration_s: float = 2.0
    motion_window_frames: int = 8
    joint_motion_threshold_rad: float = 0.01
    gripper_motion_threshold: float = 0.02
    context_frames: int = 8

    def quality_config(self) -> QualityConfig:
        return QualityConfig.trainable(
            required_cameras=self.required_cameras,
            max_sync_delta_s=self.max_sync_delta_s,
            target_fps=self.target_fps,
            fps_tolerance_ratio=self.fps_tolerance_ratio,
            min_frame_count=self.min_frame_count,
            min_duration_s=self.min_duration_s,
        )


def clean_original_dataset(dataset_dir: Path, config: Optional[CleaningConfig] = None) -> dict:
    """Copy approved, valid original episodes into their sibling cleaned dataset."""
    source = _validate_original_dataset_dir(Path(dataset_dir))
    config = config or CleaningConfig()
    metadata_rows = _read_jsonl(source / "meta" / "episodes.jsonl")
    if not metadata_rows:
        raise ValueError("original dataset contains no episodes")
    annotations = _latest_annotations(source / "meta" / "episode_annotations.jsonl")
    decisions = [_evaluate_episode(source, row, annotations, config) for row in metadata_rows]
    destination = _cleaned_dataset_dir(source)
    staging_parent = destination.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".qpos_gripper-cleaning-", dir=staging_parent))
    try:
        _write_cleaned_dataset(staging, source, decisions, config)
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _summary(source, destination, decisions)


def _validate_original_dataset_dir(dataset_dir: Path) -> Path:
    source = dataset_dir.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"dataset directory does not exist: {source}")
    if source.name != "qpos_gripper" or source.parent.parent.name != "original":
        raise ValueError(
            "dataset_dir must be original/<runtime_mode>/qpos_gripper"
        )
    if not (source / "meta" / "episodes.jsonl").is_file():
        raise ValueError("original dataset is missing meta/episodes.jsonl")
    return source


def _cleaned_dataset_dir(source: Path) -> Path:
    return source.parent.parent.parent / "cleaned" / source.parent.name / source.name


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        stream = path.open("r", encoding="utf-8-sig")
    except FileNotFoundError:
        return rows
    with stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSON row must be an object at {path}:{line_number}")
            rows.append(value)
    return rows


def _latest_annotations(path: Path) -> dict[int, dict]:
    annotations = {}
    for row in _read_jsonl(path):
        episode_index = row.get("episode_index")
        if isinstance(episode_index, int):
            annotations[episode_index] = row
    return annotations


def _evaluate_episode(
    source: Path,
    episode: Mapping[str, Any],
    annotations: Mapping[int, Mapping[str, Any]],
    config: CleaningConfig,
) -> dict:
    episode_index = episode.get("episode_index")
    if not isinstance(episode_index, int):
        raise ValueError("episode metadata has no integer episode_index")
    reasons: list[str] = []
    image_paths: set[Path] = set()
    image_paths_by_frame: list[set[Path]] = []
    data_path = _source_relative_path(source, episode.get("data_path"), reasons, "episode_data_path")
    frames = []
    if data_path is None or not data_path.is_file():
        reasons.append("episode_data_missing")
    else:
        try:
            frames = _read_jsonl(data_path)
        except ValueError as exc:
            reasons.append(f"episode_data_invalid:{exc}")

    quality_config = config.quality_config()
    schema_name = str(episode.get("action_schema", ""))
    try:
        get_schema(schema_name)
    except KeyError:
        reasons.append("action_schema_unknown")
        schema_name = ""
    timestamps: list[float] = []
    previous_observation_timestamp = None
    previous_frame_timestamp = None
    previous_action = None
    for line_number, frame in enumerate(frames):
        observation = frame.get("observation")
        action = frame.get("action")
        if not isinstance(observation, Mapping):
            reasons.append("observation_invalid")
            continue
        hydrated, frame_image_paths, image_reasons = _hydrate_images(source, observation)
        image_paths.update(frame_image_paths)
        image_paths_by_frame.append(frame_image_paths)
        reasons.extend(image_reasons)
        if schema_name:
            result = check_frame(
                observation=hydrated,
                action=action,
                schema_name=schema_name,
                config=quality_config,
                previous_timestamp=previous_observation_timestamp,
                previous_action=previous_action,
            )
            reasons.extend(result.drop_reasons)
        observation_timestamp = hydrated.get("timestamp")
        if _finite_number(observation_timestamp):
            timestamps.append(float(observation_timestamp))
            previous_observation_timestamp = float(observation_timestamp)
        frame_timestamp = frame.get("timestamp")
        if _frame_dt_out_of_range(previous_frame_timestamp, frame_timestamp, quality_config):
            reasons.append("frame_dt_out_of_range")
        if _finite_number(frame_timestamp):
            previous_frame_timestamp = float(frame_timestamp)
        previous_action = action

    metadata_frame_count = episode.get("frame_count")
    if isinstance(metadata_frame_count, int) and metadata_frame_count != len(frames):
        reasons.append("frame_count_mismatch")
    if len(frames) < config.min_frame_count:
        reasons.append("frame_count_below_min")
    duration = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
    if duration < config.min_duration_s:
        reasons.append("duration_below_min")

    retained_range = _retained_frame_range(frames, config)
    source_frame_count = len(frames)
    if retained_range is None:
        retained_frames = []
        retained_image_paths: set[Path] = set()
        trimmed_leading_frames = 0
        trimmed_trailing_frames = 0
    else:
        retained_start, retained_end = retained_range
        retained_frames = frames[retained_start:retained_end]
        retained_image_paths = set().union(*image_paths_by_frame[retained_start:retained_end])
        trimmed_leading_frames = retained_start
        trimmed_trailing_frames = len(frames) - retained_end

    annotation = annotations.get(episode_index)
    outcome = None if annotation is None else str(annotation.get("outcome", "")).lower()
    technical_reasons = _unique(reasons)
    if technical_reasons:
        decision = "rejected"
        all_reasons = technical_reasons
    elif outcome == "failure":
        decision = "rejected"
        all_reasons = ["human_outcome_failure"]
    elif outcome == "success" and retained_range is None:
        decision = "needs_review"
        all_reasons = ["no_state_motion"]
    elif outcome == "success":
        decision = "accepted"
        all_reasons = []
    elif annotation is None:
        decision = "needs_review"
        all_reasons = ["human_outcome_missing"]
    else:
        decision = "needs_review"
        all_reasons = ["human_outcome_invalid"]
    return {
        "episode_index": episode_index,
        "episode": dict(episode),
        "decision": decision,
        "outcome": outcome,
        "frame_count": len(frames),
        "duration_s": duration,
        "reasons": all_reasons,
        "image_paths": sorted(image_paths),
        "retained_image_paths": sorted(retained_image_paths),
        "retained_frames": retained_frames,
        "source_frame_count": source_frame_count,
        "retained_frame_count": len(retained_frames),
        "trimmed_leading_frames": trimmed_leading_frames,
        "trimmed_trailing_frames": trimmed_trailing_frames,
        "data_path": data_path,
        "annotation": None if annotation is None else dict(annotation),
    }


def _retained_frame_range(frames: list[Mapping[str, Any]], config: CleaningConfig) -> tuple[int, int] | None:
    """Return one contiguous active range with context, or None when no motion exists."""
    states = [_frame_state(frame) for frame in frames]
    if any(state is None for state in states):
        return None
    window = max(1, int(config.motion_window_frames))
    if len(states) <= window:
        return None
    active_indices = []
    for index in range(window, len(states)):
        before = states[index - window]
        current = states[index]
        joint_delta = max(abs(current[joint] - before[joint]) for joint in range(6))
        gripper_delta = abs(current[6] - before[6])
        if (joint_delta >= config.joint_motion_threshold_rad or
                gripper_delta >= config.gripper_motion_threshold):
            active_indices.append(index)
    if not active_indices:
        return None
    first = max(0, active_indices[0] - int(config.context_frames))
    last = min(len(states), active_indices[-1] + int(config.context_frames) + 1)
    return first, last


def _frame_state(frame: Mapping[str, Any]) -> list[float] | None:
    observation = frame.get("observation")
    if not isinstance(observation, Mapping):
        return None
    state = observation.get("state")
    if not isinstance(state, (list, tuple)) or len(state) != 7:
        return None
    try:
        values = [float(value) for value in state]
    except (TypeError, ValueError):
        return None
    return values if all(math.isfinite(value) for value in values) else None


def _hydrate_images(source: Path, observation: Mapping[str, Any]) -> tuple[dict, set[Path], list[str]]:
    hydrated = copy.deepcopy(dict(observation))
    image_paths: set[Path] = set()
    reasons: list[str] = []
    images = hydrated.get("images")
    if not isinstance(images, dict):
        return hydrated, image_paths, reasons
    for camera, payload in images.items():
        if not isinstance(payload, dict) or not payload.get("data_path"):
            continue
        image_path = _source_relative_path(source, payload.get("data_path"), reasons, f"image_path:{camera}")
        if image_path is None or not image_path.is_file():
            reasons.append(f"image_file_missing:{camera}")
            continue
        payload["data"] = image_path.read_bytes()
        image_paths.add(image_path)
    return hydrated, image_paths, reasons


def _source_relative_path(source: Path, value: Any, reasons: list[str], reason_prefix: str) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        reasons.append(f"{reason_prefix}_missing")
        return None
    candidate = (source / value).resolve()
    try:
        candidate.relative_to(source)
    except ValueError:
        reasons.append(f"{reason_prefix}_outside_dataset")
        return None
    return candidate


def _frame_dt_out_of_range(previous_timestamp: Any, timestamp: Any, config: QualityConfig) -> bool:
    if previous_timestamp is None or config.target_fps is None:
        return False
    if not _finite_number(previous_timestamp) or not _finite_number(timestamp):
        return False
    expected_dt = 1.0 / float(config.target_fps)
    tolerance = config.fps_tolerance_s
    if tolerance is None:
        tolerance = expected_dt * float(config.fps_tolerance_ratio)
    return abs((float(timestamp) - float(previous_timestamp)) - expected_dt) > float(tolerance)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _write_cleaned_dataset(destination: Path, source: Path, decisions: list[dict], config: CleaningConfig) -> None:
    meta_dir = destination / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    accepted = [item for item in decisions if item["decision"] == "accepted"]
    with (meta_dir / "episodes.jsonl").open("w", encoding="utf-8") as stream:
        for item in accepted:
            episode = dict(item["episode"])
            episode["category"] = "cleaned"
            episode["dataset_stage"] = "cleaned"
            episode["frame_count"] = item["retained_frame_count"]
            stream.write(json.dumps(episode, ensure_ascii=False) + "\n")
            _write_jsonl(destination / episode["data_path"], item["retained_frames"])
            for image_path in item["retained_image_paths"]:
                _copy_file(image_path, source, destination)
    annotations = [item["annotation"] for item in accepted if item["annotation"] is not None]
    if annotations:
        with (meta_dir / "episode_annotations.jsonl").open("w", encoding="utf-8") as stream:
            for annotation in annotations:
                stream.write(json.dumps(annotation, ensure_ascii=False) + "\n")
    manifest = [_manifest_row(source, item) for item in decisions]
    _write_jsonl(meta_dir / "cleaning_manifest.jsonl", manifest)
    summary = _summary(source, destination, decisions)
    summary["config"] = {
        "required_cameras": list(config.required_cameras),
        "max_sync_delta_s": config.max_sync_delta_s,
        "target_fps": config.target_fps,
        "fps_tolerance_ratio": config.fps_tolerance_ratio,
        "min_frame_count": config.min_frame_count,
        "min_duration_s": config.min_duration_s,
        "motion_window_frames": config.motion_window_frames,
        "joint_motion_threshold_rad": config.joint_motion_threshold_rad,
        "gripper_motion_threshold": config.gripper_motion_threshold,
        "context_frames": config.context_frames,
    }
    (meta_dir / "cleaning_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (meta_dir / "cleaning_report.html").write_text(
        _html_report(summary, manifest), encoding="utf-8"
    )


def _copy_file(source_file: Path, source_root: Path, destination_root: Path) -> None:
    relative = source_file.relative_to(source_root)
    destination_file = destination_root / relative
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, destination_file)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _manifest_row(source: Path, item: Mapping[str, Any]) -> dict:
    return {
        "schema_version": 1,
        "source_dataset_dir": str(source),
        "episode_index": item["episode_index"],
        "decision": item["decision"],
        "outcome": item["outcome"],
        "frame_count": item["source_frame_count"],
        "source_frame_count": item["source_frame_count"],
        "retained_frame_count": item["retained_frame_count"],
        "trimmed_leading_frames": item["trimmed_leading_frames"],
        "trimmed_trailing_frames": item["trimmed_trailing_frames"],
        "duration_s": item["duration_s"],
        "reasons": item["reasons"],
    }


def _summary(source: Path, destination: Path, decisions: list[dict]) -> dict:
    accepted = [item["episode_index"] for item in decisions if item["decision"] == "accepted"]
    rejected = [item["episode_index"] for item in decisions if item["decision"] == "rejected"]
    review = [item["episode_index"] for item in decisions if item["decision"] == "needs_review"]
    return {
        "ok": True,
        "source_dataset_dir": str(source),
        "cleaned_dataset_dir": str(destination),
        "report_path": str(destination / "meta" / "cleaning_report.html"),
        "created_at": time.time(),
        "episode_count": len(decisions),
        "accepted_episode_indices": accepted,
        "rejected_episode_indices": rejected,
        "needs_review_episode_indices": review,
    }


def _html_report(summary: Mapping[str, Any], manifest: list[Mapping[str, Any]]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>episode {item['episode_index']}</td>"
        f"<td>{html.escape(str(item['outcome'] or 'unannotated'))}</td>"
        f"<td>{html.escape(str(item['decision']))}</td>"
        f"<td>{item['source_frame_count']} -> {item['retained_frame_count']}</td>"
        f"<td>{item['trimmed_leading_frames']} / {item['trimmed_trailing_frames']}</td>"
        f"<td>{html.escape(', '.join(item['reasons']) or 'accepted')}</td>"
        "</tr>"
        for item in manifest
    )
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Dataset Cleaning Report</title>
<style>body{{font-family:sans-serif;margin:32px;color:#172033}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #cbd5e1;padding:8px;text-align:left}}th{{background:#eaf0f7}}.counts{{display:flex;gap:24px}}.count{{padding:12px 18px;background:#f4f7fb}}</style>
</head><body><h1>Dataset Cleaning Report</h1>
<p>Source: {html.escape(str(summary['source_dataset_dir']))}</p>
<p>Cleaned output: {html.escape(str(summary['cleaned_dataset_dir']))}</p>
<div class=\"counts\"><div class=\"count\">Accepted: {len(summary['accepted_episode_indices'])}</div><div class=\"count\">Rejected: {len(summary['rejected_episode_indices'])}</div><div class=\"count\">Needs review: {len(summary['needs_review_episode_indices'])}</div></div>
<h2>Episode Decisions</h2><table><thead><tr><th>Episode</th><th>Human outcome</th><th>Decision</th><th>Frames (source -> retained)</th><th>Trim (leading / trailing)</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
