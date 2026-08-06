"""Launch official LeRobot dataset visualization through Rerun."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from data_collection_pkg.dataset.converter import convert_jsonl_to_lerobot
from data_collection_pkg.dataset.schemas import dataset_relative_dir


@dataclass(frozen=True)
class LeRobotVizConfig:
    """Configuration for one official LeRobot dataset visualization run."""

    dataset_dir: Path
    repo_id: str
    dataset_kind: str = "auto"
    output_root: Optional[Path] = None
    episode_index: int = 0
    fps: float = 12.5
    robot_type: str = "ur5e"
    cameras: Sequence[str] = ()
    executable: str = "lerobot-dataset-viz"


@dataclass(frozen=True)
class LeRobotVizResult:
    """Summary of the launched visualization command."""

    ok: bool
    dataset_kind: str
    root: Path
    repo_id: str
    episode_index: int
    argv: list
    converted: bool
    message: str = ""


def run_lerobot_viz(
    config: LeRobotVizConfig,
    *,
    runner: Optional[Callable[[list], int]] = None,
    converter: Optional[Callable[..., dict]] = None,
) -> LeRobotVizResult:
    """Open an official LeRobot dataset visualization."""
    dataset_dir = Path(config.dataset_dir)
    _validate_common(config, dataset_dir)
    dataset_kind = _resolve_dataset_kind(dataset_dir, config.dataset_kind)
    root = dataset_dir
    converted = False

    if dataset_kind == "jsonl":
        if config.output_root is None:
            raise ValueError("output_root is required when visualizing a JSONL dataset")
        converter_fn = converter or convert_jsonl_to_lerobot
        summary = converter_fn(
            dataset_dir,
            output_root=Path(config.output_root),
            repo_id=config.repo_id,
            fps=config.fps,
            robot_type=config.robot_type,
            cameras=tuple(config.cameras),
        )
        root = Path(config.output_root) / dataset_relative_dir(str(summary["schema_name"]))
        converted = True

    argv = _viz_argv(
        executable=config.executable,
        repo_id=config.repo_id,
        root=root,
        episode_index=config.episode_index,
    )
    runner_fn = runner or _run_process
    return_code = runner_fn(argv)
    return LeRobotVizResult(
        ok=return_code == 0,
        dataset_kind=dataset_kind,
        root=root,
        repo_id=config.repo_id,
        episode_index=int(config.episode_index),
        argv=argv,
        converted=converted,
        message=f"lerobot-dataset-viz exited with code {return_code}",
    )


def _validate_common(config: LeRobotVizConfig, dataset_dir: Path) -> None:
    if config.dataset_kind not in {"auto", "jsonl", "lerobot"}:
        raise ValueError("dataset_kind must be auto, jsonl, or lerobot")
    if not dataset_dir.exists():
        raise FileNotFoundError(f"dataset_dir does not exist: {dataset_dir}")
    if int(config.episode_index) < 0:
        raise ValueError("episode_index must be non-negative")
    if not str(config.repo_id).strip():
        raise ValueError("repo_id is required")


def _resolve_dataset_kind(dataset_dir: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    if (dataset_dir / "meta" / "episodes.jsonl").exists():
        return "jsonl"
    return "lerobot"


def _viz_argv(*, executable: str, repo_id: str, root: Path, episode_index: int) -> list:
    return [
        executable,
        "--repo-id",
        str(repo_id),
        "--root",
        str(root),
        "--episode-index",
        str(int(episode_index)),
        "--mode",
        "local",
    ]


def _run_process(argv: list) -> int:
    try:
        return subprocess.Popen(argv).wait()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "lerobot-dataset-viz was not found; install LeRobot with "
            "`pip install -r requirements-lerobot.txt`."
        ) from exc
