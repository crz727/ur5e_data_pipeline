from data_collection_pkg.action_replay.replay_topics import REPLAY_TOPICS
from data_collection_pkg.action_replay.rviz_markers import build_path_marker


def test_replay_topics_are_under_data_collection_namespace():
    assert REPLAY_TOPICS["action"] == "/data_collection/replay/action"
    assert REPLAY_TOPICS["marker"] == "/data_collection/replay/marker"


def test_rviz_marker_builder_returns_visualization_payload():
    marker = build_path_marker(
        points=[(0.1, 0.2, 0.3), (0.2, 0.2, 0.4)],
        frame_id="base",
        marker_id=7,
        warning=False,
    )

    assert marker["topic"] == "/data_collection/replay/marker"
    assert marker["frame_id"] == "base"
    assert marker["type"] == "line_strip"
    assert marker["points"] == [
        {"x": 0.1, "y": 0.2, "z": 0.3},
        {"x": 0.2, "y": 0.2, "z": 0.4},
    ]
