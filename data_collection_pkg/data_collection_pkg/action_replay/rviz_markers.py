"""JSON-serializable RViz marker payload builders for replay visualization."""

from typing import Iterable, Tuple

from data_collection_pkg.action_replay.replay_topics import REPLAY_TOPICS


def build_path_marker(
    *,
    points: Iterable[Tuple[float, float, float]],
    frame_id: str,
    marker_id: int = 0,
    warning: bool = False,
) -> dict:
    """Build a line-strip marker payload for replay path visualization."""
    color = (
        {"r": 1.0, "g": 0.2, "b": 0.1, "a": 1.0}
        if warning
        else {"r": 0.1, "g": 0.7, "b": 1.0, "a": 1.0}
    )
    return {
        "topic": REPLAY_TOPICS["marker"],
        "frame_id": str(frame_id),
        "marker_id": int(marker_id),
        "type": "line_strip",
        "points": [
            {"x": float(x), "y": float(y), "z": float(z)}
            for x, y, z in points
        ],
        "color": color,
    }
