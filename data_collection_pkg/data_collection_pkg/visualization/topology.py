"""ROS2 topology and data-flow status helpers."""

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class TopicEndpoint:
    """One node endpoint on one topic."""

    topic: str
    node: str
    direction: str


@dataclass(frozen=True)
class TopologyGraph:
    """JSON-serializable topic graph."""

    topics: Mapping[str, Mapping[str, list]]
    edges: list

    def to_dict(self) -> dict:
        """Return a plain dictionary representation."""
        return {"topics": dict(self.topics), "edges": list(self.edges)}


def build_topology_graph(endpoints: Sequence[TopicEndpoint]) -> TopologyGraph:
    """Build publisher/subscriber edges grouped by topic."""
    topics = {}
    for endpoint in endpoints:
        topic = topics.setdefault(endpoint.topic, {"publishers": [], "subscribers": []})
        if endpoint.direction == "publisher":
            topic["publishers"].append(endpoint.node)
        elif endpoint.direction == "subscriber":
            topic["subscribers"].append(endpoint.node)
        else:
            raise ValueError("direction must be publisher or subscriber")

    for topic in topics.values():
        topic["publishers"].sort()
        topic["subscribers"].sort()

    edges = []
    for topic_name, topic in sorted(topics.items()):
        for publisher in topic["publishers"]:
            for subscriber in topic["subscribers"]:
                edges.append({"from": publisher, "to": subscriber, "topic": topic_name})

    return TopologyGraph(topics=topics, edges=edges)


def summarize_flow(samples: Mapping[str, Mapping[str, object]], *, now: float, active_age_s: float) -> dict:
    """Summarize which topics are active by latest sample timestamp."""
    topics = {}
    for topic, sample in samples.items():
        last_timestamp = float(sample["last_timestamp"])
        age = float(now) - last_timestamp
        topics[topic] = {
            "active": age <= float(active_age_s),
            "age_s": age,
            "last_timestamp": last_timestamp,
            "publisher": sample.get("publisher"),
            "subscriber_count": int(sample.get("subscriber_count", 0)),
        }
    return {"topics": topics}


class FlowHeartbeatMonitor:
    """Track latest message timestamps for selected ROS2 topics."""

    def __init__(self, topics: Sequence[str]) -> None:
        self.topics = tuple(str(topic) for topic in topics)
        self.samples = {}

    def mark_received(
        self,
        topic: str,
        *,
        timestamp: float,
        topic_type: Optional[str] = None,
    ) -> None:
        """Record that one topic delivered a message."""
        self.samples[str(topic)] = {
            "last_timestamp": float(timestamp),
            "topic_type": topic_type,
        }

    def summarize(self, graph: TopologyGraph, *, now: float, active_age_s: float) -> dict:
        """Return active/stale status enriched with graph endpoints."""
        topics = {}
        for topic in self._known_topics(graph):
            sample = self.samples.get(topic)
            endpoint = graph.topics.get(topic, {})
            publishers = list(endpoint.get("publishers", []))
            subscribers = list(endpoint.get("subscribers", []))
            if sample is None:
                topics[topic] = {
                    "seen": False,
                    "active": False,
                    "age_s": None,
                    "last_timestamp": None,
                    "topic_type": None,
                    "publishers": publishers,
                    "subscribers": subscribers,
                    "publisher_count": len(publishers),
                    "subscriber_count": len(subscribers),
                }
                continue
            last_timestamp = float(sample["last_timestamp"])
            age = float(now) - last_timestamp
            topics[topic] = {
                "seen": True,
                "active": age <= float(active_age_s),
                "age_s": age,
                "last_timestamp": last_timestamp,
                "topic_type": sample.get("topic_type"),
                "publishers": publishers,
                "subscribers": subscribers,
                "publisher_count": len(publishers),
                "subscriber_count": len(subscribers),
            }
        return {
            "generated_at": float(now),
            "active_age_s": float(active_age_s),
            "topics": topics,
        }

    def _known_topics(self, graph: TopologyGraph) -> list:
        return sorted(set(self.topics).union(graph.topics.keys()).union(self.samples.keys()))
