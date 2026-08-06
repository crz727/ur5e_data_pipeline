from data_collection_pkg.action_replay.replay_simulator import simulate_episode
from data_collection_pkg.dataset.jsonl_writer import JsonlDatasetWriter


def _observation(timestamp):
    return {
        "timestamp": timestamp,
        "state": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "images": {},
        "safety": {},
    }


def test_replay_simulator_emits_dry_run_events_without_http(tmp_path):
    writer = JsonlDatasetWriter(tmp_path, "qpos_gripper", task="pick", source="teleop")
    writer.start_episode()
    writer.add_frame(_observation(1.0), [0.0] * 7)
    writer.add_frame(_observation(1.1), [0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    writer.close_episode()

    simulation = simulate_episode(tmp_path / "trainable" / "policy" / "qpos_gripper", episode_index=0)

    assert simulation.executed is False
    assert simulation.schema_name == "qpos_gripper"
    assert len(simulation.events) == 2
    assert simulation.events[0]["topic"] == "/data_collection/replay/action"
    assert "endpoint" not in simulation.events[0]
    assert simulation.events[1]["action"] == [0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
