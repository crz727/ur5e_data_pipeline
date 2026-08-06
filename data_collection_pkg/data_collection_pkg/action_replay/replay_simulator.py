"""Dry-run replay simulation for saved JSONL datasets."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReplaySimulation:
    """Summary of a dry-run replay."""

    episode_index: int
    schema_name: str
    frame_count: int
    executed: bool
    events: list


def simulate_episode(dataset_dir: Path, *, episode_index: int = 0) -> ReplaySimulation:
    """Read an episode and emit replay events without touching hardware."""
    dataset_dir = Path(dataset_dir)
    metadata = _episode_metadata(dataset_dir, episode_index)
    data_path = dataset_dir / metadata["data_path"]
    events = []

    with data_path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            frame = json.loads(line)
            events.append({
                "topic": "/data_collection/replay/action",
                "timestamp": frame.get("timestamp"),
                "frame_index": frame.get("frame_index"),
                "action_schema": metadata["action_schema"],
                "source": metadata.get("source"),
                "runtime_mode": metadata.get("runtime_mode"),
                "action": frame.get("action"),
                "observation": frame.get("observation"),
            })

    return ReplaySimulation(
        episode_index=episode_index,
        schema_name=metadata["action_schema"],
        frame_count=len(events),
        executed=False,
        events=events,
    )


def _episode_metadata(dataset_dir: Path, episode_index: int) -> dict:
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    with metadata_path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row["episode_index"]) == int(episode_index):
                return row
    raise ValueError(f"episode {episode_index} not found")
