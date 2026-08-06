import threading
import time

from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter
from data_collection_pkg.visualization.replay_controller import DashboardReplayController
from data_collection_pkg.visualization.web_dashboard import DashboardStateStore


def _observation(timestamp, qpos):
    return {
        "timestamp": timestamp,
        "state": qpos + [0.5],
        "qpos": qpos,
        "qvel": [0.0] * 6,
        "effort": [0.0] * 6,
        "gripper": 0.5,
        "images": {},
        "safety": {},
    }


def test_dashboard_replay_preserves_recorded_joint_names_for_robot_model(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    observation = _observation(1.0, [0.0] * 6)
    observation["joint_names"] = [
        "shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint",
        "wrist_1_joint", "wrist_2_joint", "wrist_3_joint",
    ]
    writer.add_frame(observation, [0.0] * 7)
    writer.close_episode()
    store = DashboardStateStore()

    DashboardReplayController(store, sleeper=lambda _seconds: None).start(
        tmp_path / "original" / "teleop" / "qpos_gripper",
        episode_index=0,
        rate_hz=10.0,
        background=False,
    )

    assert store.snapshot()["telemetry"]["latest"]["joint_names"] == observation["joint_names"]


def test_dashboard_replay_uses_verified_legacy_joint_order_when_recording_has_none(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.close_episode()
    store = DashboardStateStore()

    DashboardReplayController(store, sleeper=lambda _seconds: None).start(
        tmp_path / "original" / "teleop" / "qpos_gripper",
        episode_index=0,
        rate_hz=10.0,
        background=False,
    )

    assert store.snapshot()["telemetry"]["latest"]["joint_names"] == [
        "shoulder_pan_joint", "wrist_2_joint", "wrist_3_joint",
        "wrist_1_joint", "elbow_joint", "shoulder_lift_joint",
    ]


def test_dashboard_replay_controller_lists_and_replays_selected_episode(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.add_frame(_observation(1.1, [0.2] * 6), [0.2] * 7)
    writer.close_episode()
    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    store = DashboardStateStore()
    controller = DashboardReplayController(store, sleeper=lambda _seconds: None)

    episodes = controller.list_episodes(dataset_dir)
    result = controller.start(dataset_dir, episode_index=0, rate_hz=10.0, background=False)

    assert episodes == [{"episode_index": 0, "frame_count": 2, "task": "pick"}]
    assert result["ok"] is True
    state = store.snapshot()["telemetry"]
    assert state["mode"] == "replay"
    assert state["latest"]["qpos"] == [0.2] * 6
    assert store.snapshot()["replay_status"]["status"] == "done"


def test_replay_start_reports_conflict_without_locking_when_running(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.close_episode()
    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    gate = threading.Event()
    controller = DashboardReplayController(
        DashboardStateStore(), sleeper=lambda _seconds: gate.wait(2.0)
    )
    controller.start(dataset_dir, episode_index=0, rate_hz=10.0)
    deadline = time.time() + 1.0
    while controller.status().get("published_frames") != 1 and time.time() < deadline:
        time.sleep(0.01)

    result_holder = []
    request = threading.Thread(
        target=lambda: result_holder.append(
            controller.start(dataset_dir, episode_index=0, rate_hz=10.0)
        )
    )
    request.daemon = True
    request.start()
    request.join(timeout=1.0)
    gate.set()

    assert not request.is_alive()
    assert result_holder[0]["ok"] is False
    assert "replay already running" in result_holder[0]["error"]


def test_replay_resume_rejects_an_episode_that_has_already_finished(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.close_episode()
    controller = DashboardReplayController(DashboardStateStore(), sleeper=lambda _seconds: None)
    controller.start(
        tmp_path / "original" / "teleop" / "qpos_gripper",
        episode_index=0,
        rate_hz=10.0,
        background=False,
    )

    result = controller.resume()

    assert result["ok"] is False
    assert result["status"] == "done"
    assert result["error"] == "replay is not paused"


def test_replay_seek_clamps_and_immediately_applies_selected_frame(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.add_frame(_observation(1.1, [0.1] * 6), [0.1] * 7)
    writer.add_frame(_observation(1.2, [0.2] * 6), [0.2] * 7)
    writer.close_episode()
    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    gate = threading.Event()
    store = DashboardStateStore()
    controller = DashboardReplayController(store, sleeper=lambda _seconds: gate.wait(2.0))

    controller.start(dataset_dir, episode_index=0, rate_hz=10.0)
    deadline = time.time() + 1.0
    while controller.status().get("published_frames") != 1 and time.time() < deadline:
        time.sleep(0.01)
    controller.pause()

    result = controller.seek(99)

    assert result["ok"] is True
    assert result["status"] == "paused"
    assert result["frame_index"] == 2
    assert result["published_frames"] == 3
    assert result["timestamp"] == 1.2
    assert store.snapshot()["telemetry"]["latest"]["qpos"] == [0.2] * 6
    controller.stop()
    gate.set()
    controller._thread.join(timeout=1.0)


def test_replay_seek_rebuilds_history_from_only_the_selected_episode_prefix(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.add_frame(_observation(1.1, [0.1] * 6), [0.1] * 7)
    writer.add_frame(_observation(1.2, [0.2] * 6), [0.2] * 7)
    writer.add_frame(_observation(1.3, [0.3] * 6), [0.3] * 7)
    writer.close_episode()
    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    gate = threading.Event()
    store = DashboardStateStore()
    store.update_telemetry({"qpos": [9.0] * 6}, timestamp=999.0)
    controller = DashboardReplayController(store, sleeper=lambda _seconds: gate.wait(2.0))

    controller.start(dataset_dir, episode_index=0, rate_hz=10.0)
    deadline = time.time() + 1.0
    while controller.status().get("published_frames") != 1 and time.time() < deadline:
        time.sleep(0.01)
    controller.pause()
    result = controller.seek(2)
    history = store.snapshot()["telemetry"]["history"]

    assert result["ok"] is True
    assert [sample["timestamp"] for sample in history] == [1.0, 1.1, 1.2]
    assert [sample["qpos"] for sample in history] == [
        [0.0] * 6, [0.1] * 6, [0.2] * 6,
    ]
    controller.stop()
    gate.set()
    controller._thread.join(timeout=1.0)


def test_stop_after_completed_replay_restores_live_telemetry(tmp_path):
    writer = JsonlDatasetWriter(
        tmp_path, "qpos_gripper", task="pick", source="teleop",
        runtime_mode="teleop", dataset_stage="original",
    )
    writer.start_episode()
    writer.add_frame(_observation(1.0, [0.0] * 6), [0.0] * 7)
    writer.close_episode()
    store = DashboardStateStore()
    controller = DashboardReplayController(store, sleeper=lambda _seconds: None)

    controller.start(
        tmp_path / "original" / "teleop" / "qpos_gripper",
        episode_index=0,
        rate_hz=10.0,
        background=False,
    )
    result = controller.stop()
    store.update_telemetry({"qpos": [0.9] * 6}, timestamp=2.0)
    telemetry = store.snapshot()["telemetry"]

    assert result["status"] == "stopped"
    assert telemetry["mode"] == "live"
    assert telemetry["latest"]["qpos"] == [0.9] * 6


def test_terminal_done_after_stop_signal_restores_live_telemetry():
    store = DashboardStateStore()
    controller = DashboardReplayController(store)
    store.replace_telemetry_history([({"qpos": [0.0] * 6}, 1.0)], mode="replay")

    controller._stop.set()
    controller._set_status("done")
    store.update_telemetry({"qpos": [0.9] * 6}, timestamp=2.0)
    telemetry = store.snapshot()["telemetry"]

    assert controller.status()["status"] == "stopped"
    assert telemetry["mode"] == "live"
    assert telemetry["latest"]["qpos"] == [0.9] * 6


def test_replay_thread_exposes_unexpected_errors(tmp_path):
    class BrokenStore(DashboardStateStore):
        def update_image(self, *args, **kwargs):
            raise RuntimeError("image cache failed")

    writer = JsonlDatasetWriter(
        tmp_path,
        "qpos_gripper",
        task="pick",
        source="teleop",
        runtime_mode="teleop",
        dataset_stage="original",
    )
    writer.start_episode()
    observation = _observation(1.0, [0.0] * 6)
    observation["images"] = {
        "external": {"data_path": "images/episode_000000/external/frame_000000.jpg"}
    }
    writer.add_frame(observation, [0.0] * 7)
    writer.close_episode()
    dataset_dir = tmp_path / "original" / "teleop" / "qpos_gripper"
    image_path = dataset_dir / "images" / "episode_000000" / "external" / "frame_000000.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"jpeg")
    store = BrokenStore()
    controller = DashboardReplayController(store, sleeper=lambda _seconds: None)

    controller.start(dataset_dir, episode_index=0, rate_hz=10.0)
    controller._thread.join(timeout=2.0)

    status = controller.status()
    assert status["status"] == "error"
    assert "image cache failed" in status["error"]
