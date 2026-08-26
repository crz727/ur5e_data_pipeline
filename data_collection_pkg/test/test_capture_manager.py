import json
import threading
import time
from pathlib import Path

from data_collection_pkg.dataset import task_annotations
from data_collection_pkg.visualization.capture_manager import CaptureManager, _timestamp_label


FIXED_TIMESTAMP = _timestamp_label(1785488195.0)


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_capture_manager_starts_hardware_qpos_collector_only(tmp_path):
    calls = []
    process = FakeProcess()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    manager = CaptureManager(root=tmp_path, popen=fake_popen)
    result = manager.start({
        "runtime_mode": "teleop",
        "task": "teleop_segment_01",
        "sample_rate_hz": 10.0,
        "required_cameras": "external,wrist",
    })

    command = calls[0][0]
    assert result["ok"] is True
    assert command[:4] == [
        "ros2",
        "launch",
        "data_collection_pkg",
        "data_collection_hardware_qpos.launch.py",
    ]
    assert "runtime_mode:=teleop" in command
    assert "dataset_stage:=original" in command
    assert "task:=teleop_segment_01" in command
    assert "gripper_state_topic:=/binary_gripper_state" in command
    assert "gripper_state_msg_type:=std_msgs.msg:Int8" in command
    assert "sampling_clock:=scene_camera_header" in command
    assert calls[0][1]["start_new_session"] is True
    assert not any("ur5e_http_api" in part for part in command)
    assert not any("pika_teleop" in part for part in command)


def test_capture_manager_allows_only_one_concurrent_start(tmp_path):
    calls = []
    entered_popen = threading.Event()
    release_popen = threading.Event()
    processes = []
    second_done = threading.Event()

    def blocking_popen(command, **kwargs):
        calls.append(command)
        entered_popen.set()
        assert release_popen.wait(timeout=2.0)
        process = FakeProcess()
        processes.append(process)
        return process

    manager = CaptureManager(root=tmp_path, popen=blocking_popen)
    results = []

    def start_capture():
        results.append(manager.start({"runtime_mode": "teleop", "task": "concurrent"}))

    first_thread = threading.Thread(target=start_capture)
    first_thread.start()
    assert entered_popen.wait(timeout=2.0)

    def start_second_capture():
        try:
            start_capture()
        finally:
            second_done.set()

    second_thread = threading.Thread(target=start_second_capture)
    second_thread.start()
    time.sleep(0.05)
    assert not second_done.is_set()
    release_popen.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert len(calls) == 1
    assert len(results) == 2
    assert sum(result["ok"] for result in results) == 1
    rejected = next(result for result in results if not result["ok"])
    assert rejected["running"] is True
    assert rejected["error"] == "capture already running"
    assert len(processes) == 1


def test_capture_manager_forwards_scene_camera_clock_overrides(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    manager.start({
        "runtime_mode": "teleop",
        "task": "camera_clock",
        "sampling_clock": "scene_camera_header",
        "sample_rate_hz": 30.0,
        "camera_sync_tolerance_s": 0.02,
        "state_max_sync_delta_s": 0.02,
        "gripper_sync_tolerance_s": 0.03,
        "scene_camera_settle_delay_s": 0.07,
    })

    command = calls[0]
    assert "sampling_clock:=scene_camera_header" in command
    assert "sample_rate_hz:=30.0" in command
    assert "camera_sync_tolerance_s:=0.02" in command
    assert "joint_state_sync_tolerance_s:=0.02" in command
    assert "gripper_sync_tolerance_s:=0.03" in command
    assert "scene_camera_settle_delay_s:=0.07" in command


def test_capture_manager_registers_and_launches_a_task_language_label(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs)) or FakeProcess(),
        now=lambda: 1785488195.0,
    )

    result = manager.start({
        "runtime_mode": "teleop",
        "task": "pick_place_batch_0807",
        "task_id": "pick_red_block_to_blue_tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
    })

    command = calls[0][0]
    labels = manager.task_labels()
    assert result["ok"] is True
    assert "task:=pick_place_batch_0807" in command
    assert "task_id:=pick-red-block-to-blue-tray" in command
    assert "language_instruction_en:=Pick up the red block and place it in the blue tray." in command
    assert "language_instruction_zh:=抓取红色方块并放入蓝色托盘。" in command
    assert labels == {
        "ok": True,
        "labels": [{
            "task_name": "pick_place_batch_0807",
            "task_id": "pick-red-block-to-blue-tray",
            "language_instruction_en": "Pick up the red block and place it in the blue tray.",
            "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
            "annotation_source": "capture_ui",
            "last_used_at": 1785488195.0,
        }],
    }
    assert (tmp_path / "_task_catalog.jsonl").is_file()


def test_capture_manager_omits_empty_language_launch_arguments(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    result = manager.start({"runtime_mode": "teleop", "task": "act_only_batch"})

    assert result["ok"] is True
    assert "task:=act_only_batch" in calls[0]
    assert not any(item.startswith("task_id:=") for item in calls[0])
    assert not any(item.startswith("language_instruction_en:=") for item in calls[0])
    assert not any(item.startswith("language_instruction_zh:=") for item in calls[0])
    assert manager.task_labels() == {"ok": True, "labels": []}


def test_capture_manager_accepts_act_and_vla_as_capture_profiles(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    for runtime_mode in ("act", "vla"):
        result = manager.start({"runtime_mode": runtime_mode, "task": f"{runtime_mode}_batch"})
        assert result["ok"] is True
        assert result["runtime_mode"] == runtime_mode
        assert result["dataset_dir"] == str(
            Path(result["task_root"]) / "original" / runtime_mode / "qpos_gripper"
        )
        manager.stop()

    assert all("data_collection_hardware_qpos.launch.py" in command for command in calls)
    assert not any("policy" in item for command in calls for item in command)


def test_capture_manager_rejects_new_policy_capture_profile(tmp_path):
    manager = CaptureManager(root=tmp_path, popen=lambda *args, **kwargs: FakeProcess())

    result = manager.start({"runtime_mode": "policy", "task": "legacy_policy_batch"})

    assert result["ok"] is False
    assert "runtime_mode" in result["error"]


def test_capture_manager_rejects_conflicting_reuse_of_task_language_label(tmp_path):
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda *_args, **_kwargs: FakeProcess(),
    )
    payload = {
        "runtime_mode": "teleop",
        "task": "pick_place_batch_0807",
        "task_id": "pick_red_block_to_blue_tray",
        "language_instruction_en": "Pick up the red block and place it in the blue tray.",
        "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
    }
    manager.start(payload)
    manager.stop()

    result = manager.start({
        **payload,
        "language_instruction_en": "Put the red block into the blue tray.",
    })

    assert result["ok"] is False
    assert "conflicting English" in result["error"]


def test_vla_english_instruction_validation_rejects_missing_and_placeholder_text():
    assert task_annotations.validate_vla_english_instruction("") == "missing_english_instruction"
    assert task_annotations.validate_vla_english_instruction("抓取红色方块") == "missing_english_instruction"
    assert task_annotations.validate_vla_english_instruction("test_01") == "invalid_english_instruction"
    assert task_annotations.validate_vla_english_instruction("episode-003") == "invalid_english_instruction"
    assert task_annotations.validate_vla_english_instruction("Pick up the red block.") is None


def test_capture_manager_uses_15hz_and_separate_sync_tolerances_by_default(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    manager.start({"runtime_mode": "teleop", "task": "pick"})

    assert "sample_rate_hz:=15.0" in calls[0]
    assert "camera_sync_tolerance_s:=0.02" in calls[0]
    assert "joint_state_sync_tolerance_s:=0.02" in calls[0]
    assert "gripper_sync_tolerance_s:=0.03" in calls[0]


def test_capture_manager_formats_integer_rate_for_ros_double_parameter(tmp_path):
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
    )

    manager.start({
        "runtime_mode": "teleop",
        "task": "pick",
        "sample_rate_hz": 30,
        "camera_sync_tolerance_s": 0,
        "joint_state_sync_tolerance_s": 0,
        "gripper_sync_tolerance_s": 0,
    })

    assert "sample_rate_hz:=30.0" in calls[0]
    assert "camera_sync_tolerance_s:=0.0" in calls[0]
    assert "joint_state_sync_tolerance_s:=0.0" in calls[0]
    assert "gripper_sync_tolerance_s:=0.0" in calls[0]


def test_capture_manager_new_task_creates_current_task_folder(tmp_path):
    manager = CaptureManager(root=tmp_path, now=lambda: 1785488195.0)

    result = manager.new_task({"task": "pick red block"})

    assert result["ok"] is True
    assert result["task"] == "pick_red_block"
    assert result["task_root"] == str(tmp_path / f"pick_red_block_{FIXED_TIMESTAMP}")
    assert (tmp_path / f"pick_red_block_{FIXED_TIMESTAMP}").is_dir()
    assert manager.status()["task_root"] == result["task_root"]


def test_capture_manager_start_uses_current_task_folder_as_root(tmp_path):
    calls = []
    process = FakeProcess()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    manager = CaptureManager(root=tmp_path, popen=fake_popen, now=lambda: 1785488195.0)
    task_result = manager.new_task({"task": "pick_red_block"})
    start_result = manager.start({"runtime_mode": "teleop"})

    command = calls[0][0]
    assert start_result["task_root"] == task_result["task_root"]
    assert f"root:={task_result['task_root']}" in command
    assert start_result["dataset_dir"] == str(
        tmp_path / f"pick_red_block_{FIXED_TIMESTAMP}" / "original" / "teleop" / "qpos_gripper"
    )


def test_capture_manager_start_creates_task_folder_when_missing(tmp_path):
    calls = []

    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **kwargs: calls.append((command, kwargs)) or FakeProcess(),
        now=lambda: 1785488195.0,
    )

    result = manager.start({"runtime_mode": "http", "task": "http pick"})

    assert result["ok"] is True
    assert result["task_root"] == str(tmp_path / f"http_pick_{FIXED_TIMESTAMP}")
    assert f"root:={result['task_root']}" in calls[0][0]


def test_capture_manager_rejects_unknown_mode(tmp_path):
    manager = CaptureManager(root=tmp_path, popen=lambda *args, **kwargs: FakeProcess())

    result = manager.start({"runtime_mode": "drive_robot"})

    assert result["ok"] is False
    assert "runtime_mode" in result["error"]


def test_capture_manager_stop_terminates_running_collector(tmp_path):
    process = FakeProcess()
    manager = CaptureManager(root=tmp_path, popen=lambda *args, **kwargs: process)
    manager.start({"runtime_mode": "http", "task": "http_segment_01"})

    result = manager.stop()

    assert result["ok"] is True
    assert process.terminated is True
    assert manager.status()["running"] is False


def test_capture_manager_close_stops_collector_and_is_idempotent(tmp_path):
    process = FakeProcess()
    manager = CaptureManager(root=tmp_path, popen=lambda *args, **kwargs: process)

    manager.start({"runtime_mode": "teleop", "task": "shutdown"})
    manager.close()
    manager.close()

    assert process.terminated is True
    assert manager.status()["running"] is False


def test_capture_manager_refuses_cleaning_while_capture_is_running(tmp_path):
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda *args, **kwargs: FakeProcess(),
    )
    manager.start({"runtime_mode": "teleop", "task": "pick"})

    result = manager.clean({"dataset_dir": str(tmp_path / "original" / "teleop" / "qpos_gripper")})

    assert result["ok"] is False
    assert result["error"] == "stop capture before cleaning"


def test_capture_manager_forwards_cleaning_quality_overrides(tmp_path, monkeypatch):
    captured = {}

    def fake_clean(dataset_dir, config):
        captured["dataset_dir"] = dataset_dir
        captured["config"] = config
        return {"ok": True}

    monkeypatch.setattr(
        "data_collection_pkg.visualization.capture_manager.clean_original_dataset", fake_clean
    )
    manager = CaptureManager(root=tmp_path)

    result = manager.clean({
        "dataset_dir": str(tmp_path / "original"),
        "target_fps": 25.0,
        "max_sync_delta_s": 0.015,
        "fps_tolerance_ratio": 0.1,
    })

    assert result == {"ok": True}
    assert captured["dataset_dir"] == tmp_path / "original"
    assert captured["config"].target_fps == 25.0
    assert captured["config"].max_sync_delta_s == 0.015
    assert captured["config"].fps_tolerance_ratio == 0.1


def test_capture_manager_uses_15hz_cleaning_tolerance_defaults(tmp_path, monkeypatch):
    captured = {}

    def fake_clean(_dataset_dir, config):
        captured["config"] = config
        return {"ok": True}

    monkeypatch.setattr(
        "data_collection_pkg.visualization.capture_manager.clean_original_dataset", fake_clean
    )

    result = CaptureManager(root=tmp_path).clean({"dataset_dir": str(tmp_path / "original")})

    assert result == {"ok": True}
    assert captured["config"].target_fps == 15.0
    assert captured["config"].fps_tolerance_ratio == 0.5


def test_capture_manager_exports_lerobot_in_background(tmp_path):
    started = threading.Event()
    release = threading.Event()
    converter_kwargs = {}

    def fake_converter(dataset_dir, **kwargs):
        converter_kwargs.update(kwargs)
        started.set()
        assert release.wait(timeout=1.0)
        return {"output_dir": str(kwargs["output_dir"]), "frame_count": 1}

    manager = CaptureManager(root=tmp_path, converter=fake_converter)
    result = manager.start_lerobot_export({
        "cleaned_dataset_dir": str(tmp_path / "cleaned" / "teleop" / "qpos_gripper"),
        "output_dir": str(tmp_path / "lerobot"),
    })

    assert result["ok"] is True
    assert result["status"] in {"queued", "running"}
    assert started.wait(timeout=1.0)
    assert manager.lerobot_export_status()["status"] == "running"
    release.set()
    for _ in range(100):
        if manager.lerobot_export_status()["status"] == "done":
            break
        time.sleep(0.01)
    assert manager.lerobot_export_status()["status"] == "done"
    assert manager.lerobot_export_status()["result"]["frame_count"] == 1
    assert converter_kwargs["visual_storage"] == "video"
    assert converter_kwargs["video_codec"] == "h264"


def test_capture_manager_forwards_normalized_vla_profile_and_rejects_invalid_profile(tmp_path):
    converter_calls = []

    def fake_converter(dataset_dir, **kwargs):
        converter_calls.append((dataset_dir, kwargs))
        return {"output_dir": str(kwargs["output_dir"]), "frame_count": 1}

    manager = CaptureManager(root=tmp_path, converter=fake_converter)
    result = manager.export_lerobot({
        "cleaned_dataset_dir": str(tmp_path / "cleaned"),
        "output_dir": str(tmp_path / "lerobot"),
        "profile": " VLA ",
    })
    invalid_result = manager.export_lerobot({
        "cleaned_dataset_dir": str(tmp_path / "cleaned"),
        "output_dir": str(tmp_path / "lerobot"),
        "profile": "unsupported",
    })

    assert result["ok"] is True
    assert converter_calls == [(
        tmp_path / "cleaned",
        {
            "output_dir": tmp_path / "lerobot",
            "repo_id": None,
            "fps": 15.0,
            "cameras": ("external", "wrist"),
            "visual_storage": "video",
            "video_codec": "h264",
            "profile": "vla",
        },
    )]
    assert invalid_result == {"ok": False, "error": "profile must be act or vla"}


def test_capture_manager_rejects_existing_lerobot_output_before_converter(tmp_path):
    converter_called = False

    def fake_converter(*_args, **_kwargs):
        nonlocal converter_called
        converter_called = True
        return {"output_dir": "unexpected"}

    output_dir = tmp_path / "lerobot"
    output_dir.mkdir()
    manager = CaptureManager(root=tmp_path, converter=fake_converter)

    result = manager.export_lerobot({
        "cleaned_dataset_dir": str(tmp_path / "cleaned"),
        "output_dir": str(output_dir),
        "profile": "act",
    })

    assert result == {
        "ok": False,
        "error": f"output directory already exists: {output_dir}; choose a new path",
    }
    assert converter_called is False


def test_capture_manager_background_export_forwards_vla_profile(tmp_path):
    started = threading.Event()
    release = threading.Event()
    converter_kwargs = {}

    def fake_converter(_dataset_dir, **kwargs):
        converter_kwargs.update(kwargs)
        started.set()
        assert release.wait(timeout=1.0)
        return {"output_dir": str(kwargs["output_dir"]), "frame_count": 1}

    manager = CaptureManager(root=tmp_path, converter=fake_converter)
    result = manager.start_lerobot_export({
        "cleaned_dataset_dir": str(tmp_path / "cleaned"),
        "output_dir": str(tmp_path / "lerobot"),
        "profile": "vla",
    })

    try:
        assert result["ok"] is True
        assert started.wait(timeout=1.0)
        assert converter_kwargs["profile"] == "vla"
    finally:
        release.set()
    for _ in range(100):
        if manager.lerobot_export_status()["status"] == "done":
            break
        time.sleep(0.01)
    assert manager.lerobot_export_status()["status"] == "done"


def test_capture_manager_marks_unexpected_background_export_errors_failed(tmp_path):
    started = threading.Event()

    def failing_converter(_dataset_dir, **_kwargs):
        started.set()
        raise KeyError("source frame field")

    manager = CaptureManager(root=tmp_path, converter=failing_converter)
    result = manager.start_lerobot_export({
        "cleaned_dataset_dir": str(tmp_path / "cleaned"),
        "output_dir": str(tmp_path / "lerobot"),
    })

    assert result["ok"] is True
    assert started.wait(timeout=1.0)
    for _ in range(100):
        if manager.lerobot_export_status()["status"] == "failed":
            break
        time.sleep(0.01)
    status = manager.lerobot_export_status()
    assert status["status"] == "failed"
    assert "source frame field" in status["error"]


def test_capture_manager_preflights_vla_export_without_creating_output(tmp_path):
    cleaned_dataset_dir = tmp_path / "cleaned" / "teleop" / "qpos_gripper"
    metadata_path = cleaned_dataset_dir / "meta" / "episodes.jsonl"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        "\n".join([
            json.dumps({
                "episode_index": 10,
                "task": "capture batch",
                "action_schema": "qpos_gripper",
                "frame_count": 1,
                "data_path": "data/episode_000010.jsonl",
                "dataset_stage": "cleaned",
                "language_instruction_en": "Pick up the red block.",
            }),
            json.dumps({
                "episode_index": 11,
                "task": "capture batch",
                "action_schema": "qpos_gripper",
                "frame_count": 1,
                "data_path": "data/episode_000011.jsonl",
                "dataset_stage": "cleaned",
                "language_instruction_en": "",
                "language_instruction_zh": "抓取蓝色方块。",
            }),
        ]) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "lerobot-export"
    manager = CaptureManager(root=tmp_path)

    result = manager.preflight_lerobot_export({
        "cleaned_dataset_dir": f"  {cleaned_dataset_dir}  ",
        "output_dir": f"  {output_dir}  ",
        "profile": "vla",
    })

    assert result["ok"] is True
    assert result["profile"] == "vla"
    assert [episode["episode_index"] for episode in result["eligible"]] == [10]
    assert result["skipped"] == [{
        "episode_index": 11,
        "reason": "missing_english_instruction",
    }]
    assert result["planned_report_path"] == str(output_dir / "meta" / "vla_export_report.json")
    assert not output_dir.exists()
    assert manager._export_thread is None


def test_capture_manager_annotates_only_episodes_added_by_completed_capture(tmp_path):
    process = FakeProcess()
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda *args, **kwargs: process,
        now=lambda: 1785488195.0,
    )
    dataset_dir = (
        tmp_path / f"pick_{FIXED_TIMESTAMP}" / "original" / "teleop" / "qpos_gripper"
    )
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps({"episode_index": 0}) + "\n", encoding="utf-8")

    manager.start({"runtime_mode": "teleop", "task": "pick"})
    with metadata_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"episode_index": 1}) + "\n")
        stream.write(json.dumps({"episode_index": 2}) + "\n")
    manager.stop()

    result = manager.annotate({"outcome": "success"})

    rows = [
        json.loads(line)
        for line in Path(result["annotation_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert result["ok"] is True
    assert result["episode_indices"] == [1, 2]
    assert [(row["episode_index"], row["outcome"]) for row in rows] == [
        (1, "success"),
        (2, "success"),
    ]
    assert all(row["review_status"] == "reviewed" for row in rows)


def test_capture_manager_preserves_stopped_annotation_when_next_capture_starts(tmp_path):
    processes = []

    def fake_popen(*_args, **_kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    manager = CaptureManager(
        root=tmp_path,
        popen=fake_popen,
        now=lambda: 1785488195.0,
    )
    first = manager.start({"runtime_mode": "teleop", "task": "pick"})
    first_metadata = Path(first["dataset_dir"]) / "meta" / "episodes.jsonl"
    first_metadata.parent.mkdir(parents=True)
    first_metadata.write_text(json.dumps({"episode_index": 0}) + "\n", encoding="utf-8")
    manager.stop()

    manager.start({"runtime_mode": "teleop", "task": "pick"})
    result = manager.annotate({"outcome": "success"})

    rows = [
        json.loads(line)
        for line in Path(result["annotation_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert len(processes) == 2
    assert result["ok"] is True
    assert result["dataset_dir"] == first["dataset_dir"]
    assert [(row["episode_index"], row["outcome"]) for row in rows] == [(0, "success")]


def test_capture_manager_snapshots_episode_indices_before_starting_collector(tmp_path):
    dataset_dir = (
        tmp_path / f"pick_{FIXED_TIMESTAMP}" / "original" / "teleop" / "qpos_gripper"
    )
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps({"episode_index": 0}) + "\n", encoding="utf-8")

    def fake_popen(*_args, **_kwargs):
        with metadata_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"episode_index": 1}) + "\n")
        return FakeProcess()

    manager = CaptureManager(root=tmp_path, popen=fake_popen, now=lambda: 1785488195.0)
    manager.start({"runtime_mode": "teleop", "task": "pick"})
    manager.stop()

    result = manager.annotate({"outcome": "failure"})

    assert result["episode_indices"] == [1]


def test_capture_manager_rejects_annotation_before_new_episode_is_stopped(tmp_path):
    process = FakeProcess()
    manager = CaptureManager(root=tmp_path, popen=lambda *args, **kwargs: process)

    manager.start({"runtime_mode": "teleop", "task": "pick"})
    while_running = manager.annotate({"outcome": "success"})
    manager.stop()
    no_episode = manager.annotate({"outcome": "success"})
    invalid_outcome = manager.annotate({"outcome": "unknown"})

    assert while_running["ok"] is False
    assert no_episode["ok"] is False
    assert invalid_outcome["ok"] is False


def test_capture_manager_continues_existing_task_root_in_a_different_capture_mode(tmp_path):
    dataset_dir = tmp_path / "old_task" / "original" / "teleop" / "qpos_gripper"
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps({
        "episode_index": 4,
        "task": "pick_block",
        "task_id": "pick_block",
        "language_instruction_en": "Pick up the block.",
    }) + "\n", encoding="utf-8")
    calls = []
    manager = CaptureManager(
        root=tmp_path,
        popen=lambda command, **_kwargs: calls.append(command) or FakeProcess(),
    )

    selected = manager.select_existing_dataset({"dataset_dir": str(dataset_dir)})
    assert manager.status()["dataset_dir"] == str(dataset_dir)
    started = manager.start({"runtime_mode": "teleop"})
    manager.stop()
    continued = manager.start({"runtime_mode": "http"})
    manager.stop()

    assert selected["ok"] is True
    assert selected["task"] == "pick_block"
    assert started["dataset_dir"] == str(dataset_dir)
    assert "root:=" + str(tmp_path / "old_task") in calls[0]
    assert continued["ok"] is True
    assert continued["task_root"] == str(tmp_path / "old_task")
    assert continued["dataset_dir"] == str(
        tmp_path / "old_task" / "original" / "http" / "qpos_gripper"
    )
    assert "root:=" + str(tmp_path / "old_task") in calls[1]
    assert "runtime_mode:=http" in calls[1]
    assert manager.status()["dataset_dir"] == continued["dataset_dir"]
    manager.new_task({"task": "new_task"})
    assert manager.start({"runtime_mode": "http"})["ok"] is True
