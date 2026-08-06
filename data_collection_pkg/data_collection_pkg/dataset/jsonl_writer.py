"""JSONL debug and audit writer for ROS2-collected episodes."""

import json
import math
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from data_collection_pkg.dataset.schemas import ActionSchema, dataset_relative_dir, get_schema


@dataclass(frozen=True)
class Episode:
    """Open episode handle."""

    index: int
    path: Path


class JsonlDatasetWriter:
    """Write one classified dataset directory in JSONL form."""

    def __init__(
        self,
        root: Path,
        schema_name: str,
        *,
        task: str,
        source: str,
        runtime_mode: Optional[str] = None,
        dataset_stage: Optional[str] = None,
        converted_from: Optional[str] = None,
        image_storage_format: str = "jpeg",
        jpeg_quality: int = 75,
    ) -> None:
        self.root = Path(root)
        self.schema: ActionSchema = get_schema(schema_name)
        self.task = str(task)
        self.source = str(source)
        self.runtime_mode = str(runtime_mode or source or self.schema.runtime_mode)
        self.dataset_stage = None if dataset_stage is None else str(dataset_stage)
        self.converted_from = converted_from
        self.image_storage_format = str(image_storage_format or "raw").lower()
        self.jpeg_quality = int(jpeg_quality)
        self.dataset_dir = self.root / dataset_relative_dir(
            self.schema,
            dataset_stage=self.dataset_stage if self.schema.name == "qpos_gripper" else None,
            runtime_mode=self.runtime_mode,
        )
        self.meta_dir = self.dataset_dir / "meta"
        self.data_dir = self.dataset_dir / "data"
        self.videos_dir = self.dataset_dir / "videos"
        self._episode: Optional[Episode] = None
        self._frame_count = 0
        self._frame_stream = None

    def start_episode(self) -> Episode:
        """Create a new episode JSONL file."""
        if self._episode is not None:
            raise RuntimeError("close_episode must be called before starting a new episode")
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        episode_index = self._next_episode_index()
        path = self.data_dir / f"episode_{episode_index:06d}.jsonl"
        self._frame_stream = path.open("w", encoding="utf-8")
        self._episode = Episode(index=episode_index, path=path)
        self._frame_count = 0
        return self._episode

    def add_frame(
        self,
        observation: Mapping[str, Any],
        action: Any,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Append one frame to the active episode."""
        if self._episode is None or self._frame_stream is None:
            raise RuntimeError("start_episode must be called before add_frame")
        frame_metadata = self._metadata()
        if metadata:
            frame_metadata.update(dict(metadata))
        frame = {
            "episode_index": self._episode.index,
            "frame_index": self._frame_count,
            "timestamp": self._timestamp(observation),
            "observation": self._observation(
                observation,
                episode_index=self._episode.index,
                frame_index=self._frame_count,
            ),
            "action": self._action(action),
            "metadata": frame_metadata,
        }
        self._frame_stream.write(json.dumps(_json_safe(frame), ensure_ascii=False) + "\n")
        self._frame_count += 1

    def close_episode(self) -> None:
        """Close the active episode and append metadata."""
        if self._episode is None or self._frame_stream is None:
            raise RuntimeError("start_episode must be called before close_episode")
        self._frame_stream.close()
        metadata = {
            **self._metadata(),
            "episode_index": self._episode.index,
            "task": self.task,
            "observation_schema": self.schema.observation_schema,
            "frame_count": self._frame_count,
            "data_path": str(self._episode.path.relative_to(self.dataset_dir)),
        }
        with (self.meta_dir / "episodes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        self._episode = None
        self._frame_stream = None
        self._frame_count = 0

    def _metadata(self) -> dict:
        return {
            "category": (
                self.dataset_stage
                if self.schema.name == "qpos_gripper" and self.dataset_stage is not None
                else self.schema.category
            ),
            "dataset_stage": self.dataset_stage or self.schema.category,
            "runtime_mode": self.runtime_mode,
            "action_schema": self.schema.name,
            "source": self.source,
            "converted_from": self.converted_from,
        }

    def _next_episode_index(self) -> int:
        existing = sorted(self.data_dir.glob("episode_*.jsonl"))
        if not existing:
            return 0
        return int(existing[-1].stem.removeprefix("episode_")) + 1

    def _timestamp(self, observation: Mapping[str, Any]) -> float:
        timestamp = float(observation["timestamp"])
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        return timestamp

    def _observation(
        self,
        observation: Mapping[str, Any],
        *,
        episode_index: int,
        frame_index: int,
    ) -> dict:
        result = dict(observation)
        if "state" not in result:
            qpos = self._finite_vector(result.get("qpos") or result.get("positions"), "qpos", 6)
            gripper = float(result.get("gripper", result.get("gripper_position")))
            if not math.isfinite(gripper):
                raise ValueError("gripper must be finite")
            result["state"] = qpos + [gripper]
        result["state"] = self._finite_vector(result["state"], "state", 7)
        result["images"] = self._externalized_images(
            result.get("images") or {},
            episode_index=episode_index,
            frame_index=frame_index,
        )
        return result

    def _externalized_images(self, images: Any, *, episode_index: int, frame_index: int) -> Any:
        if not isinstance(images, Mapping):
            return images
        result = {}
        for camera_name, payload in images.items():
            if not isinstance(payload, Mapping):
                result[camera_name] = payload
                continue
            image = dict(payload)
            data = image.pop("data", None)
            raw_bytes = _raw_image_bytes(data)
            if raw_bytes is None:
                if data is not None:
                    image["data"] = data
                result[camera_name] = image
                continue
            encoded = self._encode_image_bytes(image, raw_bytes)
            suffix = {
                "jpeg": ".jpg",
                "png": ".png",
            }.get(encoded["codec"], ".bin")
            rel_path = (
                Path("images")
                / f"episode_{episode_index:06d}"
                / _safe_path_name(str(camera_name))
                / f"frame_{frame_index:06d}{suffix}"
            )
            abs_path = self.dataset_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(encoded["data"])
            image.update({
                "storage": "external",
                "codec": encoded["codec"],
                "data_path": str(rel_path).replace("\\", "/"),
                "byte_length": len(encoded["data"]),
                "raw_byte_length": len(raw_bytes),
            })
            result[camera_name] = image
        return result

    def _encode_image_bytes(self, image: Mapping[str, Any], raw_bytes: bytes) -> dict:
        compressed_codec = _compressed_codec(image)
        if compressed_codec is not None:
            return {"codec": compressed_codec, "data": raw_bytes}
        if self.image_storage_format != "jpeg":
            return {"codec": "raw", "data": raw_bytes}
        jpeg = _jpeg_bytes(
            raw_bytes,
            height=int(image.get("height", 0) or 0),
            width=int(image.get("width", 0) or 0),
            encoding=str(image.get("encoding", "")),
            quality=self.jpeg_quality,
        )
        if jpeg is None:
            return {"codec": "raw", "data": raw_bytes}
        return {"codec": "jpeg", "data": jpeg}

    def _action(self, action: Any) -> Any:
        if self.schema.action_dim is None:
            if not isinstance(action, Mapping):
                raise ValueError(f"{self.schema.name} action must be a mapping")
            return dict(action)
        values = self._finite_vector(action, self.schema.name, self.schema.action_dim)
        return values

    @staticmethod
    def _finite_vector(value: Any, name: str, size: int) -> list:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{name} expects {size} values")
        values = [float(item) for item in value]
        if len(values) != size:
            raise ValueError(f"{name} expects {size} values")
        if not all(math.isfinite(item) for item in values):
            raise ValueError(f"{name} must contain finite numbers")
        return values


def _json_safe(value: Any) -> Any:
    """Convert common array-like payloads into JSON-compatible values."""
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    return value


def _raw_image_bytes(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        try:
            ints = [int(item) for item in value]
        except (TypeError, ValueError):
            return None
        if all(0 <= item <= 255 for item in ints):
            return bytes(ints)
    return None


def _safe_path_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in value)


def _compressed_codec(image: Mapping[str, Any]) -> Optional[str]:
    """Return the encoded image codec when the payload is compressed."""
    transport = str(image.get("transport", "")).lower()
    if transport != "compressed":
        return None
    codec = str(image.get("codec") or image.get("format") or "").lower()
    if "jpeg" in codec or "jpg" in codec:
        return "jpeg"
    if "png" in codec:
        return "png"
    return None


def _jpeg_bytes(raw_bytes: bytes, *, height: int, width: int, encoding: str, quality: int) -> Optional[bytes]:
    if height <= 0 or width <= 0:
        return None
    normalized = encoding.lower()
    channels = 3 if normalized in ("rgb8", "bgr8") else 1 if normalized in ("mono8", "8uc1") else None
    if channels is None or len(raw_bytes) < height * width * channels:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        data = raw_bytes[:height * width * channels]
        if channels == 3:
            image = Image.frombytes("RGB", (width, height), data)
            if normalized == "bgr8":
                r, g, b = image.split()
                image = Image.merge("RGB", (b, g, r))
        else:
            image = Image.frombytes("L", (width, height), data)
        stream = BytesIO()
        image.save(stream, format="JPEG", quality=max(1, min(95, int(quality))))
        return stream.getvalue()
    except Exception:
        return None
