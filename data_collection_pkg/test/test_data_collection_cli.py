import json

from data_collection_pkg.cli import main


def test_cli_lists_schemas_with_http_only_as_debug(capsys):
    code = main(["list-schemas"])

    output = capsys.readouterr().out
    assert code == 0
    assert "qpos_gripper" in output
    assert "http_api_action\tdebug\tdebug/http_api/action" in output


def test_cli_write_quality_and_simulate_replay(tmp_path, capsys):
    actions = tmp_path / "actions.jsonl"
    observations = tmp_path / "observations.jsonl"
    actions.write_text(json.dumps([0.0] * 7) + "\n", encoding="utf-8")
    observations.write_text(
        json.dumps({
            "timestamp": 1.0,
            "state": [0.0] * 7,
            "images": {},
            "safety": {},
        }) + "\n",
        encoding="utf-8",
    )

    assert main([
        "write-jsonl",
        "--root",
        str(tmp_path),
        "--schema",
        "qpos_gripper",
        "--task",
        "offline",
        "--source",
        "teleop",
        "--actions",
        str(actions),
        "--observations",
        str(observations),
    ]) == 0

    dataset_dir = tmp_path / "trainable" / "policy" / "qpos_gripper"
    assert main(["quality-check", str(dataset_dir)]) == 0
    assert '"ok": true' in capsys.readouterr().out

    assert main(["simulate-replay", str(dataset_dir), "--episode", "0"]) == 0
    assert "/data_collection/replay/action" in capsys.readouterr().out


def test_cli_convert_jsonl_to_lerobot_invokes_converter(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_convert(dataset_dir, **kwargs):
        calls.append((dataset_dir, kwargs))
        return {
            "episode_count": 1,
            "skipped_count": 2,
            "frame_count": 2,
            "schema_name": "teleop_servo_l_pose",
            "repo_id": kwargs["repo_id"],
            "profile": kwargs["profile"],
        }

    monkeypatch.setattr("data_collection_pkg.cli.convert_jsonl_to_lerobot", fake_convert)

    code = main([
        "convert-jsonl-to-lerobot",
        str(tmp_path / "trainable" / "teleop" / "servo_l_pose"),
        "--output-dir",
        str(tmp_path / "official"),
        "--repo-id",
        "local/teleop",
        "--fps",
        "10",
        "--camera",
        "top=external",
        "--camera",
        "wrist",
        "--profile",
        "vla",
    ])

    assert code == 0
    assert calls[0][1]["repo_id"] == "local/teleop"
    assert calls[0][1]["fps"] == 10.0
    assert calls[0][1]["cameras"] == (("top", "external"), ("wrist", "wrist"))
    assert calls[0][1]["profile"] == "vla"
    assert calls[0][1]["visual_storage"] == "video"
    assert calls[0][1]["video_codec"] == "h264"
    output = json.loads(capsys.readouterr().out)
    assert output["frame_count"] == 2
    assert output["profile"] == "vla"
    assert output["skipped_count"] == 2


def test_cli_accepts_independent_repo_id_and_camera_mapping(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_convert(dataset_dir, **kwargs):
        calls.append((dataset_dir, kwargs))
        return {"output_dir": str(kwargs["output_dir"]), "repo_id": kwargs["repo_id"]}

    monkeypatch.setattr("data_collection_pkg.cli.convert_jsonl_to_lerobot", fake_convert)

    assert main([
        "convert-jsonl-to-lerobot",
        str(tmp_path / "cleaned" / "teleop" / "qpos_gripper"),
        "--output-dir", str(tmp_path / "exported"),
        "--repo-id", "lab/another-name",
        "--camera", "pano=external",
    ]) == 0

    assert calls[0][1]["output_dir"] == tmp_path / "exported"
    assert calls[0][1]["repo_id"] == "lab/another-name"
    assert calls[0][1]["fps"] == 15.0
    assert calls[0][1]["cameras"] == (("pano", "external"),)
    assert calls[0][1]["visual_storage"] == "video"
    assert calls[0][1]["profile"] == "act"


def test_cli_lerobot_viz_invokes_launcher(tmp_path, monkeypatch, capsys):
    dataset_dir = tmp_path / "official"
    dataset_dir.mkdir()
    calls = []

    def fake_run(config):
        calls.append(config)
        return type("Result", (), {
            "ok": True,
            "dataset_kind": "lerobot",
            "root": dataset_dir,
            "repo_id": "local/ur5e_teleop",
            "episode_index": 3,
            "converted": False,
            "argv": ["lerobot-dataset-viz"],
            "message": "ok",
        })()

    monkeypatch.setattr("data_collection_pkg.cli.run_lerobot_viz", fake_run)

    assert main([
        "lerobot-viz",
        "--dataset-dir",
        str(dataset_dir),
        "--dataset-kind",
        "lerobot",
        "--repo-id",
        "local/ur5e_teleop",
        "--episode-index",
        "3",
    ]) == 0

    output = capsys.readouterr().out
    assert '"ok": true' in output
    assert calls[0].dataset_dir == dataset_dir
    assert calls[0].dataset_kind == "lerobot"
    assert calls[0].repo_id == "local/ur5e_teleop"
    assert calls[0].episode_index == 3


def test_cli_quality_check_accepts_trainable_profile_options(tmp_path, capsys):
    actions = tmp_path / "actions.jsonl"
    observations = tmp_path / "observations.jsonl"
    png_2x2 = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAAC"
    actions.write_text(json.dumps([0.0] * 7) + "\n", encoding="utf-8")
    observations.write_text(
        json.dumps({
            "timestamp": 1.0,
            "state": [0.0] * 7,
            "images": {
                "external": {"timestamp": 1.0, "data": png_2x2},
                "wrist": {"timestamp": 1.0, "data": png_2x2},
            },
            "safety": {
                "software_estop": False,
                "protective_stop": False,
                "gello_intervention": False,
            },
        })
        + "\n",
        encoding="utf-8",
    )

    assert main([
        "write-jsonl",
        "--root",
        str(tmp_path),
        "--schema",
        "qpos_gripper",
        "--task",
        "offline",
        "--source",
        "teleop",
        "--actions",
        str(actions),
        "--observations",
        str(observations),
    ]) == 0
    capsys.readouterr()

    code = main([
        "quality-check",
        str(tmp_path / "trainable" / "policy" / "qpos_gripper"),
        "--profile",
        "trainable",
        "--required-camera",
        "external",
        "--required-camera",
        "wrist",
        "--max-sync-delta-s",
        "0.05",
        "--min-frame-count",
        "1",
    ])

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["profile"] == "trainable"
    assert {item["name"] for item in output["checks"]} >= {
        "required_cameras_present",
        "camera_frame_sync_delta",
        "image_decodable",
        "episode_min_frame_count",
    }
