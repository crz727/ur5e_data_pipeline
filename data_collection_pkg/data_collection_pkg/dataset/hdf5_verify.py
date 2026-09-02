"""Validation for project HDF5 v1 exports."""

import json
from pathlib import Path

import h5py

from data_collection_pkg.dataset.hdf5_schema import CAMERA_NAMES, REQUIRED_VECTOR_FEATURES, SCHEMA_NAME, SCHEMA_VERSION


def verify_hdf5_export(path: Path, expected_episode_count=None) -> dict:
    issues = []
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "issues": ["file_missing"], "episode_count": 0}
    try:
        with h5py.File(path, "r") as handle:
            if handle.attrs.get("schema") != SCHEMA_NAME:
                issues.append("invalid_schema")
            if int(handle.attrs.get("schema_version", -1)) != SCHEMA_VERSION:
                issues.append("invalid_schema_version")
            for key in ("meta/episode_index", "meta/episode_lengths", "meta/episode_ends", "meta/feature_manifest", "meta/tasks/task_id"):
                if key not in handle:
                    issues.append(f"missing_required_dataset:{key}")
            episodes = handle.get("episodes")
            episode_names = sorted(episodes.keys()) if episodes is not None else []
            if expected_episode_count is not None and len(episode_names) != int(expected_episode_count):
                issues.append("episode_count_mismatch")
            for name in episode_names:
                group = episodes[name]
                for key in ("observations/state", "actions", "timestamps", "frame_index", *(f"observations/images/{camera}" for camera in CAMERA_NAMES)):
                    if key not in group:
                        issues.append(f"missing_required_dataset:episodes/{name}/{key}")
                if "observations/state" in group and tuple(group["observations/state"].shape[1:]) != REQUIRED_VECTOR_FEATURES["observations/state"]:
                    issues.append(f"invalid_shape:episodes/{name}/observations/state")
                if "actions" in group and tuple(group["actions"].shape[1:]) != REQUIRED_VECTOR_FEATURES["actions"]:
                    issues.append(f"invalid_shape:episodes/{name}/actions")
                if "observations/state" in group and "actions" in group:
                    length = group["observations/state"].shape[0]
                    if group["actions"].shape[0] != length:
                        issues.append(f"length_mismatch:episodes/{name}")
            try:
                json.loads(handle["meta/feature_manifest"][()].decode() if isinstance(handle["meta/feature_manifest"][()], bytes) else handle["meta/feature_manifest"][()])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                issues.append("invalid_feature_manifest")
    except OSError as exc:
        issues.append(f"cannot_open:{exc}")
    return {"ok": not issues, "issues": issues, "episode_count": len(episode_names) if 'episode_names' in locals() else 0}
