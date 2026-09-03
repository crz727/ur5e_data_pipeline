"""Official LeRobotDataset backend for ROS2-collected trainable datasets."""

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from data_collection_pkg.dataset.jsonl_writer import Episode
from data_collection_pkg.dataset.schemas import ActionSchema, dataset_relative_dir, get_schema


class LeRobotDatasetWriter:
    """Write fixed-size trainable episodes through the official LeRobotDataset API."""

    def __init__(
        self,
        root: Path,
        schema_name: str,
        *,
        repo_id: str,
        fps: float = 15.0,
        robot_type: str = "ur5e",
        cameras: Sequence[str] = (),
        image_shape: Optional[Sequence[int]] = None,
        visual_storage: str = "video",
        video_codec: str = "h264",
        include_ee_pose: bool = False,
        output_dir: Optional[Path] = None,
        dataset_cls=None,
    ) -> None:
        self.root = Path(root)
        self.schema: ActionSchema = get_schema(schema_name)
        if not self.schema.lerobot_compatible:
            raise ValueError(f"{schema_name} does not support LeRobotDataset")
        self.repo_id = str(repo_id)
        self.fps = float(fps)
        self.robot_type = str(robot_type)
        self.camera_mapping = _camera_mapping(cameras)
        self.cameras = tuple(target for target, _ in self.camera_mapping)
        self.image_shape = tuple(image_shape) if image_shape is not None else None
        self.visual_storage = str(visual_storage).strip().lower()
        if self.visual_storage not in {"image", "video"}:
            raise ValueError("visual_storage must be image or video")
        self.video_codec = str(video_codec).strip()
        if self.visual_storage == "video" and not self.video_codec:
            raise ValueError("video_codec must be non-empty for video storage")
        if self.visual_storage == "video" and not self.fps.is_integer():
            raise ValueError("LeRobot video export requires an integer fps")
        self.dataset_fps = int(self.fps) if self.visual_storage == "video" else self.fps
        self.include_ee_pose = bool(include_ee_pose)
        self.dataset_dir = Path(output_dir) if output_dir is not None else self.root / dataset_relative_dir(self.schema)
        self.dataset_cls = dataset_cls or _load_lerobot_dataset()
        create_kwargs = {
            "repo_id": self.repo_id,
            "root": self.dataset_dir,
            "fps": self.dataset_fps,
            "robot_type": self.robot_type,
            "features": self._features(),
            "use_videos": self.visual_storage == "video",
        }
        if self.visual_storage == "video":
            create_kwargs["vcodec"] = self.video_codec
        self.dataset = self.dataset_cls.create(
            **create_kwargs,
        )
        self._episode_index = -1
        self._episode_task: Optional[str] = None

    def start_episode(self, *, task: str) -> Episode:
        """Start a LeRobot episode."""
        self._episode_task = str(task).strip()
        if not self._episode_task:
            self._episode_task = None
            raise ValueError("LeRobot episode task must be non-empty")
        self._episode_index += 1
        return Episode(index=self._episode_index, path=self.dataset_dir)

    def add_frame(self, observation: Mapping[str, Any], action: Any) -> None:
        """Append one frame to the official dataset."""
        if self._episode_task is None:
            raise RuntimeError("start_episode must be called before add_frame")
        frame = {
            "observation.state": np.asarray(observation["state"], dtype=np.float32),
            "action": np.asarray(action, dtype=np.float32),
            "task": self._episode_task,
        }
        if frame["observation.state"].shape != (7,):
            raise ValueError("observation.state must contain 7 values")
        if frame["action"].shape != (self.schema.action_dim,):
            raise ValueError(f"{self.schema.name} expects {self.schema.action_dim} values")
        if self.include_ee_pose and "ee_pose" in observation:
            frame["observation.ee_pose"] = np.asarray(observation["ee_pose"], dtype=np.float32)
            if frame["observation.ee_pose"].shape != (7,):
                raise ValueError("observation.ee_pose must contain 7 values")
        images = observation.get("images") or {}
        for target_name, source_name in self.camera_mapping:
            if source_name not in images:
                raise ValueError(f"missing required camera: {source_name}")
            frame[f"observation.images.{target_name}"] = self._image_array(images[source_name])
        self.dataset.add_frame(frame)

    def close_episode(self) -> None:
        """Save the current episode."""
        # The exporter runs inside a ROS/Flask worker thread. Avoid forking a
        # ProcessPoolExecutor from that multithreaded process while encoding
        # the two camera streams; serial encoding is slower but deterministic.
        self.dataset.save_episode(parallel_encoding=False)
        self._episode_task = None

    def finalize(self) -> None:
        """Finalize the dataset when the official API supports it."""
        finalize = getattr(self.dataset, "finalize", None)
        if callable(finalize):
            finalize()

    def _features(self) -> Mapping[str, Any]:
        return {
            "observation.state": {
                "dtype": "float32",
                "shape": (7,),
                "names": (
                    "qpos_0",
                    "qpos_1",
                    "qpos_2",
                    "qpos_3",
                    "qpos_4",
                    "qpos_5",
                    "gripper",
                ),
            },
            "action": {
                "dtype": "float32",
                "shape": (self.schema.action_dim,),
                "names": self.schema.action_fields,
            },
            **self._ee_pose_features(),
            **self._image_features(),
        }

    def _ee_pose_features(self) -> Mapping[str, Any]:
        if not self.include_ee_pose:
            return {}
        return {
            "observation.ee_pose": {
                "dtype": "float32",
                "shape": (7,),
                "names": ("x", "y", "z", "qx", "qy", "qz", "qw"),
            },
        }

    def _image_features(self) -> Mapping[str, Any]:
        if not self.cameras:
            return {}
        shape = tuple(self.image_shape or (0, 0, 3))
        return {
            f"observation.images.{camera_name}": {
                "dtype": self.visual_storage,
                "shape": shape,
                "names": ("height", "width", "channel"),
            }
            for camera_name in self.cameras
        }

    def _image_array(self, image: Any) -> np.ndarray:
        if isinstance(image, np.ndarray):
            return image.astype(np.uint8, copy=False)
        if isinstance(image, Mapping):
            data = image.get("data", image.get("array", image.get("image")))
            if data is None:
                raise ValueError("image payload must contain data")
            if str(image.get("codec", "")).lower() in ("jpeg", "jpg", "png"):
                decoded = _decode_encoded_image(data)
                if decoded is not None:
                    return decoded
            array = np.asarray(data, dtype=np.uint8)
            if array.ndim == 1 and array.size == 3:
                return array.reshape((1, 1, 3))
            if array.ndim == 1 and self.image_shape and int(np.prod(self.image_shape)) == array.size:
                return array.reshape(self.image_shape)
            return array
        return np.asarray(image, dtype=np.uint8)


def _load_lerobot_dataset():
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except Exception as exc:
        raise ImportError(
            "LeRobotDataset backend requires the official LeRobot package; "
            "install it with `pip install lerobot` in this environment."
        ) from exc
    return LeRobotDataset


def _decode_encoded_image(data: Any):
    try:
        from PIL import Image
        from io import BytesIO
    except Exception:
        return None
    try:
        if isinstance(data, bytes):
            raw = data
        elif isinstance(data, bytearray):
            raw = bytes(data)
        else:
            raw = bytes(int(item) for item in data)
        image = Image.open(BytesIO(raw)).convert("RGB")
        return np.asarray(image, dtype=np.uint8)
    except Exception:
        return None


def _camera_mapping(cameras: Sequence) -> tuple[tuple[str, str], ...]:
    mapping = []
    for item in cameras:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            target, source = item
        else:
            value = str(item)
            target, source = value.split("=", 1) if "=" in value else (value, value)
        target_name = str(target).strip()
        source_name = str(source).strip()
        if not target_name or not source_name:
            raise ValueError("camera mapping names must be non-empty")
        mapping.append((target_name, source_name))
    if len({target for target, _ in mapping}) != len(mapping):
        raise ValueError("camera target names must be unique")
    return tuple(mapping)
