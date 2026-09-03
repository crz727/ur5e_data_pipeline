"""Streaming conversion from cleaned JSONL datasets to project HDF5 v1."""

import json
import math
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np
from PIL import Image

from data_collection_pkg.dataset.hdf5_schema import (
    CAMERA_NAMES,
    OPTIONAL_VECTOR_FEATURES,
    REQUIRED_VECTOR_FEATURES,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    feature_manifest,
)


def convert_jsonl_to_hdf5(dataset_dir: Path, output_path: Path) -> dict:
    """Convert a cleaned qpos_gripper dataset to one HDF5 file."""
    dataset_dir = Path(dataset_dir).expanduser()
    output_path = Path(output_path).expanduser()
    if output_path.exists():
        raise ValueError(f"output file already exists: {output_path}; choose a new path")
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    if not metadata_path.is_file():
        raise ValueError("cleaned dataset must contain meta/episodes.jsonl")
    episodes = _read_jsonl(metadata_path)
    if not episodes:
        raise ValueError("dataset metadata contains no episodes")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    episode_lengths = []
    episode_ends = []
    episode_indices = []
    task_rows = []
    feature_presence = {key: None for key in OPTIONAL_VECTOR_FEATURES}
    frame_total = 0
    try:
        with h5py.File(output_path, "w") as handle:
            handle.attrs["schema"] = SCHEMA_NAME
            handle.attrs["schema_version"] = SCHEMA_VERSION
            handle.attrs["dataset_stage"] = "cleaned"
            meta = handle.create_group("meta")
            episodes_group = handle.create_group("episodes")
            for episode in episodes:
                index = _episode_index(episode)
                data_path = _safe_data_path(dataset_dir, episode.get("data_path"))
                rows = _read_jsonl(data_path)
                if not rows:
                    raise ValueError(f"episode {index} contains no frames")
                name = f"episode_{index:06d}"
                group = episodes_group.create_group(name)
                written = _write_episode(
                    group, rows, dataset_dir, index, feature_presence, episode
                )
                episode_indices.append(index)
                episode_lengths.append(written)
                frame_total += written
                episode_ends.append(frame_total)
                task_rows.append(episode)
            string_dtype = h5py.string_dtype(encoding="utf-8")
            meta.create_dataset("episode_index", data=np.asarray(episode_indices, dtype=np.int64))
            meta.create_dataset("episode_lengths", data=np.asarray(episode_lengths, dtype=np.int64))
            meta.create_dataset("episode_ends", data=np.asarray(episode_ends, dtype=np.int64))
            meta.create_dataset("feature_manifest", data=json.dumps(feature_manifest(), ensure_ascii=False), dtype=string_dtype)
            _write_tasks(meta, task_rows, string_dtype)
            summary_path = dataset_dir / "meta" / "cleaning_summary.json"
            if summary_path.is_file():
                meta.create_dataset("cleaning_summary", data=summary_path.read_text(encoding="utf-8"), dtype=string_dtype)
            handle.flush()
    except Exception:
        if output_path.exists():
            output_path.unlink()
        raise
    return {
        "ok": True,
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "output_path": str(output_path),
        "episode_count": len(episodes),
        "frame_count": frame_total,
    }


def _write_episode(group, rows, dataset_dir, episode_index, feature_presence, metadata):
    observations = group.create_group("observations")
    images_group = observations.create_group("images")
    vector_datasets = {}
    scalar_datasets = {}
    for key, shape in REQUIRED_VECTOR_FEATURES.items():
        vector_datasets[key] = None
    for key in OPTIONAL_VECTOR_FEATURES:
        vector_datasets[key] = None
    for key in ("timestamps", "frame_index"):
        scalar_datasets[key] = None
    image_datasets = {name: None for name in CAMERA_NAMES}
    episode_optional_presence = {key: None for key in OPTIONAL_VECTOR_FEATURES}
    for row_number, row in enumerate(rows):
        observation = row.get("observation")
        if not isinstance(observation, Mapping):
            raise ValueError(f"episode {episode_index} frame {row_number}: observation must be an object")
        timestamp = row.get("timestamp", observation.get("timestamp"))
        if not _finite(timestamp):
            raise ValueError(f"episode {episode_index} frame {row_number}: timestamp must be finite")
        frame_index = row.get("frame_index", row_number)
        if not isinstance(frame_index, (int, np.integer)):
            raise ValueError(f"episode {episode_index} frame {row_number}: frame_index must be an integer")
        values = {
            "observations/state": observation.get("state"),
            "actions": row.get("action"),
            "observations/ee_pose": observation.get("ee_pose"),
            "observations/joint_velocity": observation.get("joint_velocity", observation.get("qvel")),
            "observations/effort": observation.get("effort"),
        }
        for key, shape in REQUIRED_VECTOR_FEATURES.items():
            vector_datasets[key] = _append_vector(vector_datasets[key], observations if key.startswith("observations/") else group, key.split("/", 1)[-1], values[key], shape, episode_index, row_number)
        for key, shape in OPTIONAL_VECTOR_FEATURES.items():
            present = values[key] is not None
            if episode_optional_presence[key] is None:
                episode_optional_presence[key] = present
            elif episode_optional_presence[key] != present:
                raise ValueError(f"episode {episode_index}: optional feature {key} is only present in some frames")
            if present:
                vector_datasets[key] = _append_vector(vector_datasets[key], observations, key.split("/", 1)[-1], values[key], shape, episode_index, row_number)
        scalar_datasets["timestamps"] = _append_scalar(scalar_datasets["timestamps"], group, "timestamps", float(timestamp), "float64")
        scalar_datasets["frame_index"] = _append_scalar(scalar_datasets["frame_index"], group, "frame_index", int(frame_index), "int64")
        images = observation.get("images")
        if not isinstance(images, Mapping):
            raise ValueError(f"episode {episode_index} frame {row_number}: images must be an object")
        for camera in CAMERA_NAMES:
            payload = images.get("external" if camera == "top" else "wrist")
            image = _decode_image(dataset_dir, payload, episode_index, row_number, camera)
            image_datasets[camera] = _append_image(image_datasets[camera], images_group, camera, image, episode_index, row_number)
    for key, present in episode_optional_presence.items():
        if feature_presence[key] is None:
            feature_presence[key] = present
        elif feature_presence[key] != present:
            raise ValueError(f"optional feature {key} is only present in some episodes")
    for key, dataset in vector_datasets.items():
        if dataset is not None:
            dataset.attrs["dtype"] = "float32"
    group.attrs["episode_index"] = episode_index
    for key in ("task", "task_id", "language_instruction_en", "language_instruction_zh", "runtime_mode", "source"):
        if metadata.get(key) is not None:
            group.attrs[key] = str(metadata[key])
    return len(rows)


def _append_vector(dataset, parent, name, value, shape, episode_index, row_number):
    array = np.asarray(value, dtype=np.float32)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"episode {episode_index} frame {row_number}: {name} must have shape {shape} and finite values")
    if dataset is None:
        dataset = parent.create_dataset(name, shape=(0, *shape), maxshape=(None, *shape), dtype="float32", chunks=(1, *shape), compression="gzip")
    dataset.resize((dataset.shape[0] + 1, *shape))
    dataset[-1] = array
    return dataset


def _append_scalar(dataset, parent, name, value, dtype):
    if dataset is None:
        dataset = parent.create_dataset(name, shape=(0,), maxshape=(None,), dtype=dtype, chunks=(256,), compression="gzip")
    dataset.resize((dataset.shape[0] + 1,))
    dataset[-1] = value
    return dataset


def _append_image(dataset, parent, name, image, episode_index, row_number):
    array = np.asarray(image, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"episode {episode_index} frame {row_number}: {name} image must be RGB")
    if dataset is None:
        h, w, channels = array.shape
        dataset = parent.create_dataset(name, shape=(0, h, w, channels), maxshape=(None, h, w, channels), dtype="uint8", chunks=(1, h, w, channels), compression="gzip")
    elif dataset.shape[1:] != array.shape:
        raise ValueError(f"episode {episode_index} frame {row_number}: {name} image shape changed")
    dataset.resize((dataset.shape[0] + 1, *array.shape))
    dataset[-1] = array
    return dataset


def _decode_image(dataset_dir, payload, episode_index, row_number, camera):
    if not isinstance(payload, Mapping):
        raise ValueError(f"episode {episode_index} frame {row_number}: missing {camera} image")
    data_path = payload.get("data_path")
    if not isinstance(data_path, str) or not data_path.strip():
        raise ValueError(f"episode {episode_index} frame {row_number}: {camera} image data_path missing")
    path = _safe_data_path(dataset_dir, data_path)
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except (OSError, ValueError) as exc:
        raise ValueError(f"episode {episode_index} frame {row_number}: cannot decode {camera} image: {exc}") from exc


def _write_tasks(meta, rows, string_dtype):
    tasks = meta.create_group("tasks")
    fields = ("task_id", "language_instruction_en", "language_instruction_zh")
    for field in fields:
        tasks.create_dataset(field, data=[str(row.get(field, "")) for row in rows], dtype=string_dtype)


def _safe_data_path(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("data_path must be a non-empty string")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("data_path points outside dataset") from exc
    if not path.is_file():
        raise ValueError(f"data file does not exist: {value}")
    return path


def _read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _episode_index(row):
    try:
        value = int(row["episode_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("episode metadata requires an integer episode_index") from exc
    if value < 0:
        raise ValueError("episode_index must be non-negative")
    return value


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
