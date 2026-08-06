"""Safe in-dashboard replay of recorded observations."""

import json
import threading
import time
from pathlib import Path

from data_collection_pkg.action_replay.replay_simulator import simulate_episode


# The fixed-rate collector used before joint names were persisted received this
# order from the deployed UR5e state source. It was validated against the
# recorded TCP trajectory for teleop_segment_01_20260804_172530.
LEGACY_UR5E_COLLECTOR_JOINT_NAMES = (
    "shoulder_pan_joint",
    "wrist_2_joint",
    "wrist_3_joint",
    "wrist_1_joint",
    "elbow_joint",
    "shoulder_lift_joint",
)


class DashboardReplayController:
    """Replay dataset observations into dashboard-only telemetry state."""

    def __init__(self, store, *, sleeper=time.sleep) -> None:
        self.store = store
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread = None
        self._replay = None
        self._dataset_dir = None
        self._rate_hz = 10.0
        self._next_frame_index = 0
        self._status = {
            "status": "idle",
            "published_frames": 0,
            "frame_count": 0,
            "frame_index": -1,
            "timestamp": None,
            "start_timestamp": None,
        }

    def list_episodes(self, dataset_dir) -> list:
        path = Path(dataset_dir).expanduser()
        metadata_path = path / "meta" / "episodes.jsonl"
        episodes = []
        with metadata_path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip():
                    continue
                item = json.loads(line)
                episodes.append({
                    "episode_index": int(item["episode_index"]),
                    "frame_count": int(item.get("frame_count", 0)),
                    "task": str(item.get("task", "")),
                })
        return episodes

    def start(self, dataset_dir, *, episode_index: int, rate_hz: float, background: bool = True) -> dict:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, **dict(self._status), "error": "replay already running"}
            replay = simulate_episode(Path(dataset_dir), episode_index=int(episode_index))
            self._stop.clear()
            self._paused.clear()
            self._replay = replay
            self._dataset_dir = Path(dataset_dir)
            self._rate_hz = float(rate_hz)
            self._next_frame_index = 0
            self._status = {
                "status": "started",
                "episode_index": replay.episode_index,
                "frame_count": replay.frame_count,
                "published_frames": 0,
                "frame_index": -1,
                "timestamp": None,
                "start_timestamp": (
                    replay.events[0].get("timestamp") if replay.events else None
                ),
                "executed": False,
                "error": None,
            }
            self.store.replace_telemetry_history([], mode="replay")
        if background:
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
            )
            self._thread.start()
        else:
            self._run()
        return {"ok": True, **self.status()}

    def pause(self) -> dict:
        if self.status().get("status") != "running":
            return {"ok": False, **self.status(), "error": "replay is not running"}
        self._paused.set()
        self._set_status("paused")
        return {"ok": True, **self.status()}

    def resume(self) -> dict:
        if self.status().get("status") != "paused":
            return {"ok": False, **self.status(), "error": "replay is not paused"}
        self._paused.clear()
        self._set_status("running")
        return {"ok": True, **self.status()}

    def stop(self) -> dict:
        self._stop.set()
        self._paused.clear()
        with self._lock:
            worker_is_inactive = self._thread is None or not self._thread.is_alive()
        if worker_is_inactive:
            self._set_status("stopped")
            return {"ok": True, **self.status()}
        self._set_status("stopping")
        return {"ok": True, **self.status()}

    def seek(self, frame_index: int) -> dict:
        """Apply one recorded frame immediately and continue from the next one."""
        with self._lock:
            if self._status.get("status") not in {"running", "paused"}:
                return {
                    "ok": False,
                    **dict(self._status),
                    "error": "replay is not running or paused",
                }
            replay = self._replay
            dataset_dir = self._dataset_dir
            if replay is None or dataset_dir is None or not replay.events:
                return {
                    "ok": False,
                    **dict(self._status),
                    "error": "replay has no frames",
                }
            selected = min(max(int(frame_index), 0), len(replay.events) - 1)
            event = replay.events[selected]
            self._replace_replay_history(replay.events[:selected + 1])
            self._apply_observation(
                dataset_dir,
                event.get("observation") or {},
                event.get("timestamp"),
                update_telemetry=False,
            )
            self._next_frame_index = selected + 1
            self._status["frame_index"] = selected
            self._status["published_frames"] = selected + 1
            self._status["timestamp"] = event.get("timestamp")
            result = {"ok": True, **dict(self._status)}
        self._publish_status()
        return result

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _run(self) -> None:
        try:
            period = 1.0 / self._rate_hz if self._rate_hz > 0 else 0.1
            self._set_status("running")
            while True:
                while self._paused.is_set() and not self._stop.is_set():
                    time.sleep(0.05)
                if self._stop.is_set():
                    self._set_status("stopped")
                    return
                with self._lock:
                    replay = self._replay
                    dataset_dir = self._dataset_dir
                    frame_index = self._next_frame_index
                    if replay is None or dataset_dir is None or frame_index >= len(replay.events):
                        break
                    event = replay.events[frame_index]
                    self._next_frame_index = frame_index + 1
                    self._apply_observation(
                        dataset_dir,
                        event.get("observation") or {},
                        event.get("timestamp"),
                    )
                    self._status["frame_index"] = frame_index
                    self._status["published_frames"] = frame_index + 1
                    self._status["timestamp"] = event.get("timestamp")
                self._publish_status()
                self.sleeper(period)
            self._set_status("done")
        except Exception as exc:  # Keep the read-only UI usable after malformed replay data.
            self._set_status("error", error=str(exc))

    def _telemetry_payload(self, observation: dict) -> dict:
        payload = {
            key: observation[key]
            for key in ("joint_names", "qpos", "qvel", "effort", "gripper", "ee_pose")
            if key in observation
        }
        # New data includes its canonical order. Old recordings from the
        # fixed-rate collector use the verified source order above.
        payload.setdefault("joint_names", list(LEGACY_UR5E_COLLECTOR_JOINT_NAMES))
        return payload

    def _replace_replay_history(self, events) -> None:
        self.store.replace_telemetry_history([
            (self._telemetry_payload(event.get("observation") or {}), event.get("timestamp"))
            for event in events
        ], mode="replay")

    def _apply_observation(
        self, dataset_dir: Path, observation: dict, timestamp, *, update_telemetry: bool = True
    ) -> None:
        if update_telemetry:
            self.store.update_telemetry(
                self._telemetry_payload(observation), timestamp=timestamp, mode="replay")
        for camera, image in (observation.get("images") or {}).items():
            if camera not in ("external", "wrist") or not isinstance(image, dict):
                continue
            data_path = image.get("data_path")
            if not data_path:
                continue
            candidate = (dataset_dir / str(data_path)).resolve()
            if dataset_dir.resolve() not in candidate.parents:
                continue
            try:
                self.store.update_image(camera, candidate.read_bytes(), codec=image.get("codec", "jpeg"), timestamp=timestamp)
            except (OSError, ValueError):
                continue

    def _set_status(self, status: str, *, error=None) -> None:
        if status == "done" and self._stop.is_set():
            status = "stopped"
        with self._lock:
            self._status["status"] = status
            self._status["error"] = error
        if status in {"stopped", "error"}:
            self.store.resume_live_telemetry()
        self._publish_status()

    def _publish_status(self) -> None:
        self.store.update_json("replay_status", json.dumps(self.status()), timestamp=time.time())
