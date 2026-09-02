"""Command line helpers for the ROS2-only data collection package."""

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from data_collection_pkg.action_replay.replay_simulator import simulate_episode
from data_collection_pkg.dataset.cleaner import CleaningConfig, clean_original_dataset
from data_collection_pkg.dataset.converter import convert_jsonl_to_lerobot
from data_collection_pkg.dataset.hdf5_converter import convert_jsonl_to_hdf5
from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.dataset.lerobot_viz import LeRobotVizConfig, run_lerobot_viz
from data_collection_pkg.dataset.quality import QualityConfig, check_dataset
from data_collection_pkg.dataset.schemas import SCHEMAS, dataset_relative_dir, get_schema


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data_collection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-schemas", help="Print registered schemas")

    init = subparsers.add_parser("init", help="Create one dataset directory")
    init.add_argument("--root", required=True)
    init.add_argument("--schema", required=True)

    write = subparsers.add_parser("write-jsonl", help="Write one offline JSONL episode")
    write.add_argument("--root", required=True)
    write.add_argument("--schema", required=True)
    write.add_argument("--task", required=True)
    write.add_argument("--source", required=True)
    write.add_argument("--runtime-mode")
    write.add_argument("--converted-from")
    write.add_argument("--actions", required=True)
    write.add_argument("--observations", required=True)

    quality = subparsers.add_parser("quality-check", help="Validate one dataset directory")
    quality.add_argument("dataset_dir")
    quality.add_argument("--profile", choices=("basic", "trainable", "replay"), default="basic")
    quality.add_argument("--required-camera", action="append", default=[])
    quality.add_argument("--max-message-age-s", type=float)
    quality.add_argument("--max-sync-delta-s", type=float)
    quality.add_argument("--target-fps", type=float)
    quality.add_argument("--fps-tolerance-ratio", type=float, default=0.2)
    quality.add_argument("--fps-tolerance-s", type=float)
    quality.add_argument("--min-frame-count", type=int)
    quality.add_argument("--min-duration-s", type=float)
    quality.add_argument("--require-ee-pose", action="store_true")
    quality.add_argument("--no-decode-images", action="store_true")
    quality.add_argument("--require-safety-fields", action="store_true")

    clean = subparsers.add_parser(
        "clean-original",
        help="Create a sibling cleaned dataset from an original qpos_gripper dataset",
    )
    clean.add_argument("dataset_dir")
    clean.add_argument("--target-fps", type=float, default=15.0)
    clean.add_argument("--max-sync-delta-s", type=float, default=0.02)
    clean.add_argument("--fps-tolerance-ratio", type=float, default=0.5)

    replay = subparsers.add_parser("simulate-replay", help="Dry-run replay simulation")
    replay.add_argument("dataset_dir")
    replay.add_argument("--episode", type=int, default=0)

    convert = subparsers.add_parser(
        "convert-jsonl-to-lerobot",
        help="Convert one cleaned qpos dataset directory to official LeRobotDataset output",
    )
    convert.add_argument("dataset_dir")
    output_group = convert.add_mutually_exclusive_group(required=True)
    output_group.add_argument("--output-dir")
    output_group.add_argument("--output-root", dest="output_dir", help=argparse.SUPPRESS)
    convert.add_argument("--repo-id")
    convert.add_argument("--profile", choices=("act", "vla"), default="act")
    convert.add_argument("--fps", type=float, default=15.0)
    convert.add_argument("--robot-type", default="ur5e")
    convert.add_argument("--camera", action="append", default=[])
    convert.add_argument("--visual-storage", choices=("video", "image"), default="video")
    convert.add_argument("--video-codec", default="h264")

    generic_convert = subparsers.add_parser(
        "convert", help="Convert a cleaned dataset to ACT, VLA, or project HDF5 v1"
    )
    generic_convert.add_argument("dataset_dir")
    generic_convert.add_argument("--format", choices=("act", "vla", "hdf5"), required=True)
    generic_convert.add_argument("--output-path", required=True)
    generic_convert.add_argument("--repo-id")
    generic_convert.add_argument("--fps", type=float, default=15.0)
    generic_convert.add_argument("--robot-type", default="ur5e")
    generic_convert.add_argument("--camera", action="append", default=[])
    generic_convert.add_argument("--visual-storage", choices=("video", "image"), default="video")
    generic_convert.add_argument("--video-codec", default="h264")

    viz = subparsers.add_parser(
        "lerobot-viz",
        help="Open official LeRobot/Rerun visualization for a dataset",
    )
    viz.add_argument("--dataset-dir", required=True)
    viz.add_argument("--dataset-kind", choices=("auto", "jsonl", "lerobot"), default="auto")
    viz.add_argument("--output-root")
    viz.add_argument("--repo-id", required=True)
    viz.add_argument("--episode-index", type=int, default=0)
    viz.add_argument("--fps", type=float, default=12.5)
    viz.add_argument("--robot-type", default="ur5e")
    viz.add_argument("--camera", action="append", default=[])
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the data collection CLI."""
    args = _build_parser().parse_args(argv)

    if args.command == "list-schemas":
        for name in sorted(SCHEMAS):
            schema = SCHEMAS[name]
            print(f"{name}\t{schema.category}\t{dataset_relative_dir(schema)}")
        return 0

    if args.command == "init":
        schema = get_schema(args.schema)
        dataset_dir = Path(args.root) / dataset_relative_dir(schema)
        for child in ("meta", "data", "videos"):
            (dataset_dir / child).mkdir(parents=True, exist_ok=True)
        print(f"initialized {dataset_dir}")
        return 0

    if args.command == "write-jsonl":
        writer = JsonlDatasetWriter(
            Path(args.root),
            args.schema,
            task=args.task,
            source=args.source,
            runtime_mode=args.runtime_mode,
            converted_from=args.converted_from,
        )
        writer.start_episode()
        for observation, action in zip(_read_jsonl(Path(args.observations)), _read_jsonl(Path(args.actions))):
            writer.add_frame(observation, action)
        writer.close_episode()
        print(json.dumps({"ok": True, "dataset_dir": str(writer.dataset_dir)}, ensure_ascii=False))
        return 0

    if args.command == "quality-check":
        report = check_dataset(Path(args.dataset_dir), config=_quality_config_from_args(args))
        print(json.dumps({
            "ok": report.ok,
            "profile": report.profile,
            "episode_count": report.episode_count,
            "frame_count": report.frame_count,
            "checks": report.checks,
            "issues": report.issues,
        }, ensure_ascii=False))
        return 0 if report.ok else 2

    if args.command == "clean-original":
        result = clean_original_dataset(Path(args.dataset_dir), config=CleaningConfig(
            target_fps=args.target_fps,
            max_sync_delta_s=args.max_sync_delta_s,
            fps_tolerance_ratio=args.fps_tolerance_ratio,
        ))
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.command == "simulate-replay":
        simulation = simulate_episode(Path(args.dataset_dir), episode_index=args.episode)
        print(json.dumps({
            "episode_index": simulation.episode_index,
            "schema_name": simulation.schema_name,
            "frame_count": simulation.frame_count,
            "executed": simulation.executed,
            "events": simulation.events,
        }, ensure_ascii=False))
        return 0

    if args.command == "convert-jsonl-to-lerobot":
        summary = convert_jsonl_to_lerobot(
            Path(args.dataset_dir),
            output_dir=Path(args.output_dir),
            repo_id=args.repo_id,
            profile=args.profile,
            fps=args.fps,
            robot_type=args.robot_type,
            cameras=tuple(_camera_mapping(value) for value in args.camera),
            visual_storage=args.visual_storage,
            video_codec=args.video_codec,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if args.command == "convert":
        dataset_dir = Path(args.dataset_dir)
        if args.format == "hdf5":
            summary = convert_jsonl_to_hdf5(dataset_dir, Path(args.output_path))
        else:
            summary = convert_jsonl_to_lerobot(
                dataset_dir,
                output_dir=Path(args.output_path),
                repo_id=args.repo_id,
                profile=args.format,
                fps=args.fps,
                robot_type=args.robot_type,
                cameras=tuple(_camera_mapping(value) for value in args.camera),
                visual_storage=args.visual_storage,
                video_codec=args.video_codec,
            )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if args.command == "lerobot-viz":
        result = run_lerobot_viz(LeRobotVizConfig(
            dataset_dir=Path(args.dataset_dir),
            dataset_kind=args.dataset_kind,
            output_root=Path(args.output_root) if args.output_root else None,
            repo_id=args.repo_id,
            episode_index=args.episode_index,
            fps=args.fps,
            robot_type=args.robot_type,
            cameras=tuple(args.camera),
        ))
        print(json.dumps({
            "ok": result.ok,
            "dataset_kind": result.dataset_kind,
            "root": str(result.root),
            "repo_id": result.repo_id,
            "episode_index": result.episode_index,
            "converted": result.converted,
            "argv": result.argv,
            "message": result.message,
        }, ensure_ascii=False))
        return 0 if result.ok else 2

    raise AssertionError("unreachable command branch")


def _read_jsonl(path: Path) -> list:
    items = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict) and "action" in value:
                value = value["action"]
            items.append(value)
    return items


def _camera_mapping(value: str) -> tuple[str, str]:
    target, separator, source = str(value).partition("=")
    return (target, source) if separator else (target, target)


def _quality_config_from_args(args: argparse.Namespace) -> QualityConfig:
    kwargs = {
        "required_cameras": tuple(args.required_camera),
        "max_message_age_s": args.max_message_age_s,
        "max_sync_delta_s": args.max_sync_delta_s,
        "target_fps": args.target_fps,
        "fps_tolerance_ratio": args.fps_tolerance_ratio,
        "fps_tolerance_s": args.fps_tolerance_s,
        "min_frame_count": args.min_frame_count,
        "min_duration_s": args.min_duration_s,
        "require_ee_pose": args.require_ee_pose,
        "decode_images": False if args.no_decode_images else None,
        "require_safety_fields": True if args.require_safety_fields else None,
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}
    if args.profile == "trainable":
        return QualityConfig.trainable(**kwargs)
    if args.profile == "replay":
        return QualityConfig.replay(**kwargs)
    return QualityConfig.basic(**kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
