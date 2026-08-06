"""Timestamp-based sample synchronization helpers for ROS2 capture."""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class Sample:
    """One timestamped topic sample."""

    topic: str
    timestamp: float
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class SyncedFrame:
    """Synchronized samples for one target timestamp."""

    ok: bool
    timestamp: float
    samples: Mapping[str, Sample]
    drop_reasons: list


class TopicSynchronizer:
    """Keep recent samples and assemble frames around a target timestamp."""

    def __init__(
        self,
        *,
        required_topics: Sequence[str],
        optional_topics: Sequence[str] = (),
        tolerance_s: float,
        topic_tolerances: Mapping[str, float] = None,
        max_samples_per_topic: int = 64,
    ) -> None:
        self.required_topics = tuple(required_topics)
        self.optional_topics = tuple(optional_topics)
        self.tolerance_s = float(tolerance_s)
        self.topic_tolerances = {
            str(topic): float(tolerance)
            for topic, tolerance in (topic_tolerances or {}).items()
        }
        self.max_samples_per_topic = int(max_samples_per_topic)
        self._samples: Dict[str, list] = {}

    def add_sample(self, sample: Sample) -> None:
        """Store one sample in timestamp order."""
        topic_samples = self._samples.setdefault(sample.topic, [])
        topic_samples.append(sample)
        topic_samples.sort(key=lambda item: item.timestamp)
        if len(topic_samples) > self.max_samples_per_topic:
            del topic_samples[:-self.max_samples_per_topic]

    def synchronize_at(self, timestamp: float) -> SyncedFrame:
        """Return a synchronized frame or drop reasons for missing/stale topics."""
        target = float(timestamp)
        selected = {}
        drop_reasons = []

        for topic in self.required_topics:
            sample = self._nearest(topic, target)
            if sample is None:
                drop_reasons.append(f"missing_topic:{topic}")
                continue
            if abs(float(sample.timestamp) - target) > self._tolerance_for(topic):
                drop_reasons.append(f"stale_topic:{topic}")
                continue
            selected[topic] = sample

        if drop_reasons:
            return SyncedFrame(
                ok=False,
                timestamp=target,
                samples={},
                drop_reasons=drop_reasons,
            )

        for topic in self.optional_topics:
            sample = self._nearest(topic, target)
            if sample is not None and abs(float(sample.timestamp) - target) <= self._tolerance_for(topic):
                selected[topic] = sample

        return SyncedFrame(
            ok=True,
            timestamp=target,
            samples=selected,
            drop_reasons=[],
        )

    def _nearest(self, topic: str, timestamp: float):
        topic_samples = self._samples.get(topic) or []
        if not topic_samples:
            return None
        return min(topic_samples, key=lambda item: abs(float(item.timestamp) - timestamp))

    def _tolerance_for(self, topic: str) -> float:
        return self.topic_tolerances.get(topic, self.tolerance_s)
