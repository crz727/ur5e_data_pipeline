"""Converters from JSONL debug datasets to official LeRobotDataset output."""

import json
import math
from io import BytesIO
from pathlib import Path
from typing import Sequence

from data_collection_pkg.dataset.lerobot_writer import LeRobotDatasetWriter
from data_collection_pkg.dataset.lerobot_verify import verify_lerobot_export


def convert_jsonl_to_lerobot(
    dataset_dir: Path,
    *,
    output_dir: Path = None,
    output_root: Path = None,
    repo_id: str = None,
    fps: float = 15.0,
    robot_type: str = "ur5e",
    cameras: Sequence[str] = (),
    visual_storage: str = "video",
    video_codec: str = "h264",
    image_shape=None,
    dataset_cls=None,
) -> dict:
    """Convert one JSONL dataset directory to an official LeRobotDataset."""
    dataset_dir = Path(dataset_dir)
    _validate_cleaned_qpos_dataset(dataset_dir)
    output_dir = Path(output_dir or output_root) if (output_dir or output_root) else None
    if output_dir is None:
        raise ValueError("output_dir is required")
    repo_id = str(repo_id or f"local/{output_dir.name}")
    episodes = _read_episodes(dataset_dir)
    if not episodes:
        raise ValueError("dataset metadata contains no episodes")
    schema_names = {row["action_schema"] for row in episodes}
    if len(schema_names) != 1:
        raise ValueError("LeRobot conversion expects one action_schema per dataset")
    schema_name = next(iter(schema_names))
    task = str(episodes[0].get("task", ""))
    inferred_image_shape = image_shape or _infer_image_shape(dataset_dir, episodes, cameras)
    writer = LeRobotDatasetWriter(
        output_dir,
        schema_name,
        task=task,
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
    for episode in episodes:
        writer.start_episode()
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
    writer.finalize()

    result = {
        "episode_count": len(episodes),
        "frame_count": frame_count,
        "schema_name": schema_name,
        "repo_id": repo_id,
        "output_dir": str(output_dir),
    }
    if dataset_cls is None:
        result.update(verify_lerobot_export(
            output_dir,
            expected_episode_count=len(episodes),
            expected_cameras=tuple(_camera_target_name(camera) for camera in cameras),
            visual_storage=visual_storage,
        ))
        if not result["ok"]:
            raise RuntimeError("LeRobot export verification failed: " + ", ".join(result["issues"]))
    return result


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
