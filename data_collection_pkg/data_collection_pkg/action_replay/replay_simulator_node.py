"""ROS2 entry point for dry-run dataset replay."""

import json
from pathlib import Path

from data_collection_pkg.action_replay.replay_simulator import ReplaySimulation, simulate_episode
from data_collection_pkg.action_replay.replay_topics import REPLAY_TOPICS


def replay_simulator_node_main(args=None):
    """Start the replay simulator node adapter."""
    import rclpy
    from std_msgs.msg import String

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("data_collection_replay_simulator")
        _declare_parameters(node)
        dataset_dir = _parameter_value(node, "dataset_dir", "")
        episode_index = int(_parameter_value(node, "episode_index", 0))
        rate_hz = float(_parameter_value(node, "rate_hz", 10.0))
        replay = _load_replay(node, dataset_dir, episode_index)
        if replay is None:
            rclpy.spin(node)
            return

        publisher = ReplayPublisher(
            node=node,
            replay=replay,
            string_msg_type=String,
            rate_hz=rate_hz,
        )
        publisher.start()
        node.get_logger().info(
            "data_collection replay simulator started "
            f"dataset_dir={dataset_dir} episode_index={episode_index}"
        )
        rclpy.spin(node)
    finally:
        rclpy.shutdown()


class ReplayPublisher:
    """Publish replay events to ROS2 topics."""

    def __init__(self, *, node, replay: ReplaySimulation, string_msg_type, rate_hz: float) -> None:
        self.node = node
        self.replay = replay
        self.string_msg_type = string_msg_type
        self.rate_hz = float(rate_hz)
        self.index = 0
        self.action_publisher = node.create_publisher(
            string_msg_type,
            REPLAY_TOPICS["action"],
            10,
        )
        self.observation_publisher = node.create_publisher(
            string_msg_type,
            REPLAY_TOPICS["observation"],
            10,
        )
        self.status_publisher = node.create_publisher(
            string_msg_type,
            REPLAY_TOPICS["status"],
            10,
        )
        self.timer = None

    def start(self) -> None:
        """Start timer-based replay publishing."""
        self._publish_status("started")
        period = 1.0 / self.rate_hz if self.rate_hz > 0 else 0.1
        self.timer = self.node.create_timer(period, self.publish_next)

    def publish_next(self) -> None:
        """Publish the next replay frame."""
        if self.index >= len(self.replay.events):
            self._publish_status("done")
            if self.timer is not None:
                self.timer.cancel()
            return
        event = dict(self.replay.events[self.index])
        observation = event.pop("observation", None)
        self.action_publisher.publish(self.string_msg_type(data=json.dumps(event)))
        if observation is not None:
            self.observation_publisher.publish(
                self.string_msg_type(data=json.dumps({
                    "timestamp": event.get("timestamp"),
                    "frame_index": event.get("frame_index"),
                    "observation": observation,
                }))
            )
        self.index += 1
        self._publish_status("running")

    def _publish_status(self, status: str) -> None:
        self.status_publisher.publish(self.string_msg_type(data=json.dumps({
            "status": status,
            "episode_index": self.replay.episode_index,
            "schema_name": self.replay.schema_name,
            "frame_count": self.replay.frame_count,
            "published_frames": self.index,
            "executed": False,
        })))


def _declare_parameters(node) -> None:
    node.declare_parameter("dataset_dir", "")
    node.declare_parameter("episode_index", 0)
    node.declare_parameter("rate_hz", 10.0)


def _parameter_value(node, name: str, default):
    parameter = node.get_parameter(name)
    value = getattr(parameter, "value", None)
    return default if value is None else value


def _load_replay(node, dataset_dir, episode_index: int):
    if not dataset_dir:
        node.get_logger().warning("dataset_dir is empty; replay simulator is idle")
        return None
    try:
        return simulate_episode(Path(dataset_dir), episode_index=episode_index)
    except Exception as exc:
        node.get_logger().error(f"failed to load replay dataset: {exc}")
        return None
