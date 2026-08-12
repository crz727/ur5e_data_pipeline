"""Converters from JSONL debug datasets to official LeRobotDataset output."""

import json
import math
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from data_collection_pkg.dataset.lerobot_writer import LeRobotDatasetWriter
from data_collection_pkg.dataset.lerobot_verify import verify_lerobot_export
from data_collection_pkg.dataset.task_annotations import validate_vla_english_instruction


_DEFAULT_CAMERAS = (("top", "external"), ("wrist", "wrist"))
_IMAGE_NORMALIZATION = {
    "input": "uint8_rgb",
    "conversion": "float32_rgb_0_to_1",
    "normalization": "imagenet_rgb",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


def convert_jsonl_to_lerobot(
    dataset_dir: Path,
    *,
    output_dir: Path = None,
    output_root: Path = None,
    repo_id: str = None,
    fps: float = 30.0,
    robot_type: str = "ur5e",
    cameras: Sequence[str] = (),
    visual_storage: str = "video",
    video_codec: str = "h264",
    image_shape=None,
    dataset_cls=None,
    profile: str = "act",
) -> dict:
    """Convert one JSONL dataset directory to an official LeRobotDataset."""
    dataset_dir = Path(dataset_dir)
    output_dir = Path(output_dir or output_root) if (output_dir or output_root) else None
    if output_dir is None:
        raise ValueError("output_dir is required")
    if output_dir.exists():
        raise ValueError(
            f"output directory already exists: {output_dir}; choose a new path"
        )
    profile = _normalize_profile(profile)
    repo_id = str(repo_id or f"local/{output_dir.name}")
    preflight = preflight_jsonl_to_lerobot(dataset_dir, profile)
    episodes = preflight["eligible"]
    skipped = preflight["skipped"]
    schema_name = preflight["schema_name"]
    cameras = tuple(cameras) if cameras else _DEFAULT_CAMERAS

    if profile == "vla":
        episodes, integrity_skipped = _partition_data_integrity_episodes(
            dataset_dir,
            episodes,
            cameras,
        )
        skipped.extend(integrity_skipped)
    if profile == "vla" and not episodes:
        _write_vla_export_report(output_dir, dataset_dir, episodes, skipped)
        raise ValueError("VLA export has no eligible episodes with a valid English instruction")

    inferred_image_shape = image_shape or _infer_image_shape(dataset_dir, episodes, cameras)
    writer = LeRobotDatasetWriter(
        output_dir,
        schema_name,
        repo_id=repo_id,
        fps=fps,
        robot_type=robot_type,
        cameras=cameras,
        image_shape=inferred_image_shape,
        visual_storage=visual_storage,
        video_codec=video_codec,
        output_dir=output_dir,
        dataset_cls=dataset_cls,
    )
    # Expose the fake dataset in tests without touching the public writer API.
    if dataset_cls is not None:
        try:
            dataset_cls.created["dataset"] = writer.dataset
        except Exception:
            pass

    frame_count = 0
    completed_episodes = []
    active_episode = None
    camera_names = tuple(_camera_target_name(camera) for camera in cameras)
    try:
        for episode in episodes:
            active_episode = episode
            writer.start_episode(task=episode["task"])
            data_path = dataset_dir / episode["data_path"]
            with data_path.open("r", encoding="utf-8-sig") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    frame = json.loads(line)
                    _hydrate_external_images(frame, dataset_dir)
                    writer.add_frame(frame["observation"], frame["action"])
                    frame_count += 1
            writer.close_episode()
            completed_episodes.append(episode)
            active_episode = None
        writer.finalize()
        write_image_normalization_metadata(output_dir, camera_names)
        if profile == "vla":
            _write_episode_language_annotations(output_dir, episodes)
    except Exception as exc:
        if profile == "vla":
            completed_indices = {row["episode_index"] for row in completed_episodes}
            active_index = (
                active_episode["episode_index"] if active_episode is not None else None
            )
            for episode in episodes:
                episode_index = episode["episode_index"]
                if episode_index in completed_indices:
                    continue
                skipped.append({
                    "episode_index": episode_index,
                    "reason": (
                        "data_integrity_conversion_error"
                        if episode_index == active_index
                        else "conversion_aborted"
                    ),
                    "error": str(exc),
                })
            _write_vla_export_report(
                output_dir,
                dataset_dir,
                completed_episodes,
                skipped,
            )
        raise
    if profile == "vla":
        _write_vla_export_report(output_dir, dataset_dir, episodes, skipped)

    result = {
        "episode_count": len(episodes),
        "source_episode_count": len(episodes) + len(skipped),
        "skipped_count": len(skipped),
        "frame_count": frame_count,
        "schema_name": schema_name,
        "repo_id": repo_id,
        "output_dir": str(output_dir),
        "profile": profile,
    }
    if dataset_cls is None:
        result.update(verify_lerobot_export(
            output_dir,
            expected_episode_count=len(episodes),
            expected_cameras=camera_names,
            visual_storage=visual_storage,
            profile=profile,
            require_image_normalization=True,
        ))
        if not result["ok"]:
            raise RuntimeError("LeRobot export verification failed: " + ", ".join(result["issues"]))
    return result


def preflight_jsonl_to_lerobot(dataset_dir: Path, profile: str) -> dict:
    """Select profile-eligible episodes without creating an output dataset."""
    dataset_dir = Path(dataset_dir)
    profile = _normalize_profile(profile)
    _validate_cleaned_qpos_dataset(dataset_dir)
    episodes = _read_episodes(dataset_dir)
    if not episodes:
        raise ValueError("dataset metadata contains no episodes")
    schema_names = {row["action_schema"] for row in episodes}
    if len(schema_names) != 1:
        raise ValueError("LeRobot conversion expects one action_schema per dataset")
    schema_name = next(iter(schema_names))
    if schema_name != "qpos_gripper":
        raise ValueError("LeRobot conversion requires the qpos_gripper action schema")

    eligible = []
    skipped = []
    for row in episodes:
        episode_index = row["episode_index"]
        if profile == "vla":
            english = _normalized_text(row.get("language_instruction_en"))
            reason = validate_vla_english_instruction(english)
            if reason is not None:
                skipped.append({"episode_index": episode_index, "reason": reason})
                continue
            task = english
        else:
            task = (
                _normalized_text(row.get("task_id"))
                or _normalized_text(row.get("task"))
                or f"episode-{episode_index}"
            )
        eligible.append({**row, "task": task})
    return {
        "profile": profile,
        "schema_name": schema_name,
        "eligible": eligible,
        "skipped": skipped,
    }


def write_image_normalization_metadata(output_dir: Path, camera_names) -> Path:
    """Write the ImageNet preprocessing contract without changing measured stats."""
    path = Path(output_dir) / "meta" / "image_normalization.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **_IMAGE_NORMALIZATION,
        "applies_to": [f"observation.images.{name}" for name in camera_names],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _normalize_profile(profile: str) -> str:
    value = str(profile).strip().lower()
    if value not in {"act", "vla"}:
        raise ValueError("profile must be act or vla")
    return value


def _normalized_text(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _write_vla_export_report(
    output_dir: Path,
    dataset_dir: Path,
    eligible: list,
    skipped: list,
) -> Path:
    path = Path(output_dir) / "meta" / "vla_export_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": str(dataset_dir),
        "profile": "vla",
        "eligible_source_episode_indices": [row["episode_index"] for row in eligible],
        "source_to_output_episode_mapping": {
            str(row["episode_index"]): output_index
            for output_index, row in enumerate(eligible)
        },
        "skipped": skipped,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _partition_data_integrity_episodes(
    dataset_dir: Path,
    episodes: list,
    cameras: Sequence,
) -> tuple[list, list]:
    eligible = []
    skipped = []
    for episode in episodes:
        error = _episode_data_integrity_error(dataset_dir, episode, cameras)
        if error is None:
            eligible.append(episode)
        else:
            skipped.append({
                "episode_index": episode["episode_index"],
                "reason": "data_integrity_conversion_error",
                "error": error,
            })
    return eligible, skipped


def _episode_data_integrity_error(
    dataset_dir: Path,
    episode: Mapping,
    cameras: Sequence,
) -> str | None:
    data_path = dataset_dir / str(episode.get("data_path", ""))
    frame_count = 0
    try:
        with data_path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip():
                    continue
                frame_count += 1
                frame = json.loads(line)
                observation = frame.get("observation")
                if not isinstance(observation, Mapping):
                    return "frame observation must be an object"
                try:
                    state = np.asarray(observation.get("state"), dtype=np.float32)
                except (TypeError, ValueError):
                    return "observation.state must contain 7 values"
                if state.shape != (7,):
                    return "observation.state must contain 7 values"
                try:
                    action = np.asarray(frame.get("action"), dtype=np.float32)
                except (TypeError, ValueError):
                    return "qpos_gripper expects 7 values"
                if action.shape != (7,):
                    return "qpos_gripper expects 7 values"
                images = observation.get("images") or {}
                if not isinstance(images, Mapping):
                    return "observation.images must be an object"
                for camera in cameras:
                    source_name = _camera_source_name(camera)
                    if source_name not in images:
                        return f"missing required camera: {source_name}"
                    payload = images[source_name]
                    image_error = _image_payload_integrity_error(payload, dataset_dir)
                    if image_error is not None:
                        return f"{image_error}: {source_name}"
    except OSError as exc:
        return f"unable to read episode data: {exc}"
    except json.JSONDecodeError as exc:
        return f"invalid episode JSON: {exc}"
    if frame_count == 0:
        return "episode contains no frames"
    return None


def _image_payload_integrity_error(payload, dataset_dir: Path) -> str | None:
    if isinstance(payload, Mapping):
        data = payload.get("data", payload.get("array", payload.get("image")))
        if data is None:
            external_path = payload.get("data_path")
            if not external_path:
                return "image payload must contain data"
            try:
                data = (dataset_dir / str(external_path)).read_bytes()
            except OSError:
                return "image payload must contain data"
        codec = str(payload.get("codec", payload.get("format", ""))).lower()
        if codec in {"jpeg", "jpg", "png", "rgb8; jpeg compressed"}:
            if _encoded_image_shape(data, codec) is None:
                return "invalid image payload"
            return None
        try:
            array = np.asarray(data, dtype=np.uint8)
        except (TypeError, ValueError):
            return "invalid image payload"
        shape = _image_payload_shape(payload, dataset_dir)
        if array.ndim == 3 and array.shape[-1] == 3:
            return None
        if (
            array.ndim == 1
            and shape is not None
            and shape[-1] == 3
            and int(np.prod(shape)) == array.size
        ):
            return None
        return "invalid image payload"
    try:
        array = np.asarray(payload, dtype=np.uint8)
    except (TypeError, ValueError):
        return "invalid image payload"
    if array.ndim != 3 or array.shape[-1] != 3:
        return "invalid image payload"
    return None


def _write_episode_language_annotations(output_dir: Path, episodes: list) -> Path:
    path = Path(output_dir) / "meta" / "episode_language_annotations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for output_index, row in enumerate(episodes):
            stream.write(json.dumps({
                "output_episode_index": output_index,
                "source_episode_index": row["episode_index"],
                "task_id": _normalized_text(row.get("task_id")),
                "language_instruction_en": _normalized_text(row.get("language_instruction_en")),
                "language_instruction_zh": _normalized_text(row.get("language_instruction_zh")),
            }, ensure_ascii=False) + "\n")
    return path


def _validate_cleaned_qpos_dataset(dataset_dir: Path) -> None:
    if dataset_dir.name != "qpos_gripper" or dataset_dir.parent.parent.name != "cleaned":
        raise ValueError("LeRobot conversion requires cleaned/<mode>/qpos_gripper")
    if not (dataset_dir / "meta" / "episodes.jsonl").is_file():
        raise ValueError("cleaned dataset is missing meta/episodes.jsonl")


def _read_episodes(dataset_dir: Path) -> list:
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    rows = []
    with metadata_path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _infer_image_shape(dataset_dir: Path, episodes: list, cameras: Sequence):
    if not cameras:
        return None
    source_cameras = [_camera_source_name(camera) for camera in cameras]
    for episode in episodes:
        data_path = dataset_dir / episode["data_path"]
        with data_path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip():
                    continue
                frame = json.loads(line)
                images = (frame.get("observation") or {}).get("images") or {}
                for camera_name in source_cameras:
                    shape = _image_payload_shape(images.get(camera_name), dataset_dir)
                    if shape is not None:
                        return shape
    return None


def _camera_source_name(camera) -> str:
    if isinstance(camera, (tuple, list)) and len(camera) == 2:
        return str(camera[1])
    value = str(camera)
    return value.split("=", 1)[1] if "=" in value else value


def _camera_target_name(camera) -> str:
    if isinstance(camera, (tuple, list)) and len(camera) == 2:
        return str(camera[0])
    value = str(camera)
    return value.split("=", 1)[0] if "=" in value else value


def _image_payload_shape(image, dataset_dir: Path = None) -> tuple | None:
    if image is None:
        return None
    if isinstance(image, dict):
        height = image.get("height")
        width = image.get("width")
        if isinstance(height, int) and isinstance(width, int) and height > 0 and width > 0:
            return (height, width, 3)
        data = image.get("data", image.get("array", image.get("image")))
        if data is None and dataset_dir is not None and image.get("data_path"):
            try:
                data = (dataset_dir / str(image["data_path"])).read_bytes()
            except OSError:
                return None
        if data is None:
            return None
        encoded_shape = _encoded_image_shape(data, image.get("codec", image.get("format", "")))
        if encoded_shape is not None:
            return encoded_shape
        return _nested_or_flat_shape(data)
    return _nested_or_flat_shape(image)


def _nested_or_flat_shape(value) -> tuple | None:
    if not isinstance(value, list):
        return None
    if value and isinstance(value[0], list):
        height = len(value)
        width = len(value[0]) if value[0] else 0
        if width and isinstance(value[0][0], list):
            return (height, width, len(value[0][0]))
    if len(value) == 3:
        return (1, 1, 3)
    if len(value) % 3 == 0:
        pixels = len(value) // 3
        side = int(math.sqrt(pixels))
        if side * side == pixels:
            return (side, side, 3)
    return None


def _encoded_image_shape(data, codec) -> tuple | None:
    if str(codec).lower() not in {"jpeg", "jpg", "png", "rgb8; jpeg compressed"}:
        return None
    try:
        from PIL import Image
        raw = data if isinstance(data, bytes) else bytes(int(value) for value in data)
        with Image.open(BytesIO(raw)) as image:
            return (image.height, image.width, len(image.getbands()))
    except (ImportError, OSError, TypeError, ValueError):
        return None


def _hydrate_external_images(frame: dict, dataset_dir: Path) -> None:
    images = ((frame.get("observation") or {}).get("images") or {})
    if not isinstance(images, dict):
        return
    for payload in images.values():
        if not isinstance(payload, dict) or "data" in payload:
            continue
        data_path = payload.get("data_path")
        if not data_path:
            continue
        path = dataset_dir / str(data_path)
        if path.exists():
            payload["data"] = list(path.read_bytes())
