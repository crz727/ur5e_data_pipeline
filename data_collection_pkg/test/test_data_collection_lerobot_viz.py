import json
from pathlib import Path

import pytest

from data_collection_pkg.dataset.lerobot_viz import LeRobotVizConfig, run_lerobot_viz


def test_lerobot_viz_launches_existing_lerobot_dataset_without_conversion(tmp_path):
    calls = []
    root = tmp_path / "official"
    root.mkdir()

    def runner(argv):
        calls.append(argv)
        return 0

    def converter(**_kwargs):
        raise AssertionError("converter must not be called for existing LeRobot datasets")

    result = run_lerobot_viz(
        LeRobotVizConfig(
            dataset_dir=root,
            dataset_kind="lerobot",
            repo_id="local/ur5e_teleop",
            episode_index=2,
        ),
        runner=runner,
        converter=converter,
    )

    assert result.ok is True
    assert result.dataset_kind == "lerobot"
    assert result.root == root
    assert calls == [[
        "lerobot-dataset-viz",
        "--repo-id",
        "local/ur5e_teleop",
        "--root",
        str(root),
        "--episode-index",
        "2",
        "--mode",
        "local",
    ]]


def _write_jsonl_dataset(dataset_dir: Path, *, schema="teleop_servo_l_pose"):
    (dataset_dir / "meta").mkdir(parents=True)
    (dataset_dir / "data").mkdir()
    (dataset_dir / "meta" / "episodes.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "task": "pick",
            "action_schema": schema,
            "frame_count": 1,
            "data_path": "data/episode_000000.jsonl",
        }) + "\n",
        encoding="utf-8",
    )
    (dataset_dir / "data" / "episode_000000.jsonl").write_text(
        json.dumps({
            "episode_index": 0,
            "frame_index": 0,
            "timestamp": 1.0,
            "observation": {"timestamp": 1.0, "state": [0.0] * 7},
            "action": [0.0] * 7,
        }) + "\n",
        encoding="utf-8",
    )


def test_lerobot_viz_converts_jsonl_dataset_before_launch(tmp_path):
    dataset_dir = tmp_path / "trainable" / "teleop" / "servo_l_pose"
    output_root = tmp_path / "official"
    _write_jsonl_dataset(dataset_dir)
    conversions = []
    calls = []

    def converter(*args, **kwargs):
        conversions.append((args, kwargs))
        return {"episode_count": 1, "frame_count": 1, "schema_name": "teleop_servo_l_pose"}

    def runner(argv):
        calls.append(argv)
        return 0

    result = run_lerobot_viz(
        LeRobotVizConfig(
            dataset_dir=dataset_dir,
            dataset_kind="jsonl",
            output_root=output_root,
            repo_id="local/ur5e_teleop",
            episode_index=0,
            fps=10.0,
            robot_type="ur5e",
            cameras=("external", "wrist"),
        ),
        converter=converter,
        runner=runner,
    )

    assert result.ok is True
    assert result.converted is True
    official_root = output_root / "trainable" / "teleop" / "servo_l_pose"
    assert result.root == official_root
    assert conversions[0][0] == (dataset_dir,)
    assert conversions[0][1]["output_root"] == output_root
    assert conversions[0][1]["repo_id"] == "local/ur5e_teleop"
    assert conversions[0][1]["fps"] == 10.0
    assert conversions[0][1]["robot_type"] == "ur5e"
    assert conversions[0][1]["cameras"] == ("external", "wrist")
    assert "--root" in calls[0]
    assert str(official_root) in calls[0]


def test_lerobot_viz_requires_output_root_for_jsonl(tmp_path):
    dataset_dir = tmp_path / "trainable" / "teleop" / "servo_l_pose"
    _write_jsonl_dataset(dataset_dir)

    with pytest.raises(ValueError, match="output_root is required"):
        run_lerobot_viz(
            LeRobotVizConfig(
                dataset_dir=dataset_dir,
                dataset_kind="jsonl",
                repo_id="local/ur5e_teleop",
            ),
            runner=lambda _argv: 0,
        )


def test_lerobot_viz_rejects_missing_dataset_dir(tmp_path):
    with pytest.raises(FileNotFoundError, match="dataset_dir does not exist"):
        run_lerobot_viz(
            LeRobotVizConfig(
                dataset_dir=tmp_path / "missing",
                dataset_kind="lerobot",
                repo_id="local/ur5e_teleop",
            ),
            runner=lambda _argv: 0,
        )
