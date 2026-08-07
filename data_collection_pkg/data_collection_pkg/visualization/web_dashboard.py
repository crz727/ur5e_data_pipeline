"""Read-only Web dashboard for data collection visualization."""

import json
import threading
import time
from typing import Any, Mapping, Optional

from flask import Flask, jsonify, request, Response

from data_collection_pkg.visualization.replay_controller import DashboardReplayController


DASHBOARD_SOURCES = (
    "topology_graph",
    "flow_status",
    "quality_status",
    "drop_reason",
    "replay_status",
)

DASHBOARD_CAMERAS = ("external", "wrist")
MAX_TELEMETRY_HISTORY = 300


class DashboardStateStore:
    """Thread-safe cache for JSON messages published by ROS2 monitor topics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payloads = {
            source: {"data": None, "timestamp": None, "valid": False, "error": "no message"}
            for source in DASHBOARD_SOURCES
        }
        self._images = {
            camera: {"data": None, "timestamp": None, "codec": None, "valid": False}
            for camera in DASHBOARD_CAMERAS
        }
        self._telemetry_latest = {
            "timestamp": None,
            "joint_names": [],
            "qpos": [],
            "qvel": [],
            "effort": [],
            "gripper": None,
            "ee_pose": [],
        }
        self._telemetry_history = []
        self._telemetry_mode = "live"

    def update_json(self, source: str, data: str, *, timestamp: Optional[float] = None) -> None:
        """Update one dashboard source from a JSON string."""
        timestamp = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as exc:
                self._payloads[source] = {
                    "data": None,
                    "timestamp": timestamp,
                    "valid": False,
                    "error": str(exc),
                }
                return
            self._payloads[source] = {
                "data": parsed,
                "timestamp": timestamp,
                "valid": True,
                "error": None,
            }

    def update_image(
        self,
        camera: str,
        data: bytes,
        *,
        codec: str = "jpeg",
        timestamp: Optional[float] = None,
    ) -> None:
        """Cache one encoded camera frame for the browser image endpoint."""
        timestamp = time.time() if timestamp is None else float(timestamp)
        camera = str(camera)
        if camera not in DASHBOARD_CAMERAS:
            raise KeyError(f"unknown dashboard camera: {camera}")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("camera data must be non-empty encoded bytes")
        with self._lock:
            self._images[camera] = {
                "data": bytes(data),
                "timestamp": timestamp,
                "codec": str(codec or "jpeg").lower(),
                "valid": True,
            }

    def image(self, camera: str) -> Optional[dict]:
        """Return a copy of the latest encoded frame for one camera."""
        with self._lock:
            payload = self._images.get(str(camera))
            return None if payload is None else dict(payload)

    def update_telemetry(
        self,
        payload: dict,
        *,
        timestamp: Optional[float] = None,
        mode: str = "live",
    ) -> None:
        """Merge a live or replay telemetry sample and retain a bounded history."""
        timestamp = time.time() if timestamp is None else float(timestamp)
        normalized = {}
        for field in ("joint_names", "qpos", "qvel", "effort", "ee_pose"):
            if field not in payload:
                continue
            values = payload[field] or []
            normalized[field] = (
                [str(value) for value in values]
                if field == "joint_names"
                else [float(value) for value in values]
            )
        if "gripper" in payload and payload["gripper"] is not None:
            normalized["gripper"] = float(payload["gripper"])
        with self._lock:
            if mode == "live" and self._telemetry_mode == "replay":
                return
            self._telemetry_latest.update(normalized)
            self._telemetry_latest["timestamp"] = timestamp
            self._telemetry_mode = str(mode or "live")
            self._telemetry_history.append({
                "timestamp": timestamp,
                "qpos": list(self._telemetry_latest["qpos"]),
                "qvel": list(self._telemetry_latest["qvel"]),
                "effort": list(self._telemetry_latest["effort"]),
                "gripper": self._telemetry_latest["gripper"],
            })
            if len(self._telemetry_history) > MAX_TELEMETRY_HISTORY:
                del self._telemetry_history[:-MAX_TELEMETRY_HISTORY]

    def replace_telemetry_history(self, samples, *, mode: str = "replay") -> None:
        """Atomically replace telemetry with one replay episode prefix."""
        latest = {
            "timestamp": None,
            "joint_names": [],
            "qpos": [],
            "qvel": [],
            "effort": [],
            "gripper": None,
            "ee_pose": [],
        }
        history = []
        for payload, timestamp in samples:
            normalized = {}
            for field in ("joint_names", "qpos", "qvel", "effort", "ee_pose"):
                if field not in payload:
                    continue
                values = payload[field] or []
                normalized[field] = (
                    [str(value) for value in values]
                    if field == "joint_names"
                    else [float(value) for value in values]
                )
            if "gripper" in payload and payload["gripper"] is not None:
                normalized["gripper"] = float(payload["gripper"])
            latest.update(normalized)
            latest["timestamp"] = float(timestamp)
            history.append({
                "timestamp": latest["timestamp"],
                "qpos": list(latest["qpos"]),
                "qvel": list(latest["qvel"]),
                "effort": list(latest["effort"]),
                "gripper": latest["gripper"],
            })
        with self._lock:
            self._telemetry_latest = latest
            self._telemetry_history = history[-MAX_TELEMETRY_HISTORY:]
            self._telemetry_mode = str(mode or "replay")

    def resume_live_telemetry(self) -> None:
        """Allow the live ROS telemetry stream to update the dashboard again."""
        with self._lock:
            self._telemetry_history = []
            self._telemetry_mode = "live"

    def snapshot(self, *, now: Optional[float] = None) -> dict:
        """Return the latest full dashboard state."""
        now = time.time() if now is None else float(now)
        with self._lock:
            payloads = dict(self._payloads)
            images = dict(self._images)
            telemetry_latest = {
                key: list(value) if isinstance(value, list) else value
                for key, value in self._telemetry_latest.items()
            }
            telemetry_history = [dict(item) for item in self._telemetry_history]
            telemetry_mode = self._telemetry_mode
        sources = {}
        state = {"generated_at": now, "sources": sources}
        for source in DASHBOARD_SOURCES:
            payload = payloads.get(source, {})
            timestamp = payload.get("timestamp")
            age = None if timestamp is None else max(0.0, now - float(timestamp))
            sources[source] = {
                "valid": bool(payload.get("valid")),
                "age_s": age,
                "last_timestamp": timestamp,
                "error": payload.get("error"),
            }
            state[source] = payload.get("data")
        cameras = {}
        for camera in DASHBOARD_CAMERAS:
            payload = images.get(camera, {})
            timestamp = payload.get("timestamp")
            cameras[camera] = {
                "valid": bool(payload.get("valid")),
                "age_s": None if timestamp is None else max(0.0, now - float(timestamp)),
                "last_timestamp": timestamp,
                "codec": payload.get("codec"),
            }
        state["cameras"] = cameras
        state["telemetry"] = {
            "mode": telemetry_mode,
            "latest": telemetry_latest,
            "history": telemetry_history,
        }
        return state


def create_dashboard_app(store: DashboardStateStore, capture_manager=None) -> Flask:
    """Create the Flask app serving the read-only dashboard."""
    app = Flask(__name__)
    replay_controller = DashboardReplayController(store)

    @app.get("/")
    def index() -> Response:
        return Response(_dashboard_html(), mimetype="text/html")

    @app.get("/api/state")
    def api_state():
        state = store.snapshot()
        state["capture_status"] = (
            {"running": False, "available": False}
            if capture_manager is None
            else {"available": True, **capture_manager.status()}
        )
        return jsonify(state)

    @app.get("/api/camera/<camera>")
    def api_camera(camera: str):
        payload = store.image(camera)
        if payload is None or not payload.get("valid"):
            return jsonify({"ok": False, "error": "camera frame unavailable"}), 404
        codec = str(payload.get("codec") or "jpeg").lower()
        mimetype = {
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
        }.get(codec, "application/octet-stream")
        return Response(
            payload["data"],
            mimetype=mimetype,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/replay/episodes")
    def api_replay_episodes():
        dataset_dir = request.args.get("dataset_dir", "")
        if not dataset_dir:
            return jsonify({"ok": False, "error": "dataset_dir is required"}), 400
        try:
            return jsonify({"ok": True, "episodes": replay_controller.list_episodes(dataset_dir)})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/replay/start")
    def api_replay_start():
        payload = request.get_json(silent=True) or {}
        try:
            result = replay_controller.start(
                payload["dataset_dir"],
                episode_index=int(payload.get("episode_index", 0)),
                rate_hz=float(payload.get("rate_hz", 10.0)),
            )
        except (KeyError, OSError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/replay/pause")
    def api_replay_pause():
        return jsonify(replay_controller.pause())

    @app.post("/api/replay/resume")
    def api_replay_resume():
        return jsonify(replay_controller.resume())

    @app.post("/api/replay/stop")
    def api_replay_stop():
        return jsonify(replay_controller.stop())

    @app.post("/api/replay/seek")
    def api_replay_seek():
        payload = request.get_json(silent=True) or {}
        try:
            frame_index = int(payload["frame_index"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "frame_index must be an integer"}), 400
        result = replay_controller.seek(frame_index)
        return jsonify(result), 200 if result.get("ok") else 409

    @app.get("/api/capture/status")
    def api_capture_status():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        return jsonify({"ok": True, "available": True, **capture_manager.status()})

    @app.post("/api/capture/start")
    def api_capture_start():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        result = capture_manager.start(request.get_json(silent=True) or {})
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/capture/new-task")
    def api_capture_new_task():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        result = capture_manager.new_task(request.get_json(silent=True) or {})
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/capture/stop")
    def api_capture_stop():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        return jsonify(capture_manager.stop())

    @app.post("/api/capture/annotate")
    def api_capture_annotate():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        result = capture_manager.annotate(request.get_json(silent=True) or {})
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/capture/clean")
    def api_capture_clean():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        result = capture_manager.clean(request.get_json(silent=True) or {})
        return jsonify(result), 200 if result.get("ok") else 409

    @app.get("/api/capture/task-labels")
    def api_capture_task_labels():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 409
        result = capture_manager.task_labels()
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/capture/export-lerobot/preflight")
    def api_capture_export_lerobot_preflight():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 409
        payload = request.get_json(silent=True)
        if not isinstance(payload, Mapping):
            return jsonify({"ok": False, "error": "preflight payload must be a JSON object"}), 409
        result = capture_manager.preflight_lerobot_export(payload)
        return jsonify(result), 200 if result.get("ok") else 409

    @app.post("/api/capture/export-lerobot")
    def api_capture_export_lerobot():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        result = capture_manager.start_lerobot_export(request.get_json(silent=True) or {})
        return jsonify(result), 202 if result.get("ok") else 409

    @app.get("/api/capture/export-lerobot/status")
    def api_capture_export_lerobot_status():
        if capture_manager is None:
            return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
        return jsonify(capture_manager.lerobot_export_status())

    return app


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Data Flow Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d8dde6;
      --text: #1f2933;
      --muted: #667085;
      --good: #1f8a5b;
      --warn: #b7791f;
      --bad: #c2413a;
      --accent: #2563eb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .status-row {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      white-space: nowrap;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--bad);
      display: inline-block;
    }
    .dot.ok { background: var(--good); }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 1fr) minmax(360px, 1.1fr);
      gap: 14px;
      padding: 14px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }
    section h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 14px;
      border-bottom: 1px solid var(--line);
      letter-spacing: 0;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 12px 14px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 66px;
    }
    .metric strong {
      display: block;
      font-size: 20px;
      line-height: 1.1;
    }
    .metric span { color: var(--muted); font-size: 12px; }
    .content { padding: 12px 14px; }
    .camera-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .camera-card {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #111827;
    }
    .camera-card img {
      display: block;
      width: 100%;
      aspect-ratio: 16 / 10;
      object-fit: contain;
      background: #111827;
    }
    .camera-caption {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 7px 9px;
      color: #e5e7eb;
      font-size: 12px;
    }
    .live-workspace {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: minmax(360px, 0.9fr) minmax(500px, 1.25fr);
      gap: 14px;
      min-width: 0;
    }
    .live-stack { display: grid; gap: 14px; min-width: 0; }
    .robot-stage {
      position: relative;
      min-height: 300px;
      background:
        linear-gradient(#edf1f5 1px, transparent 1px),
        linear-gradient(90deg, #edf1f5 1px, transparent 1px),
        #fbfcfe;
      background-size: 28px 28px;
    }
    .robot-stage canvas { display: block; width: 100%; height: 320px; }
    .stage-caption {
      position: absolute;
      left: 12px;
      top: 10px;
      color: var(--muted);
      font-size: 12px;
      pointer-events: none;
    }
    .telemetry-stack { display: grid; gap: 10px; padding: 10px; }
    .chart-card { border: 1px solid var(--line); border-radius: 6px; background: #fbfcfe; overflow: hidden; }
    .chart-head { display: flex; justify-content: space-between; gap: 8px; padding: 8px 10px 0; }
    .chart-head strong { font-size: 13px; }
    .chart-head span { color: var(--muted); font-size: 11px; }
    .chart-card canvas { display: block; width: 100%; height: 145px; }
    .chart-legend { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 10px 8px; color: var(--muted); font-size: 10px; }
    .chart-legend i { width: 8px; height: 8px; display: inline-block; border-radius: 2px; margin-right: 3px; }
    .replay-toolbar { display: grid; grid-template-columns: minmax(180px, 1fr) 120px 82px repeat(5, auto); gap: 8px; padding: 10px 14px; align-items: end; }
    .control-panel {
      display: grid;
      grid-template-columns: minmax(120px, 160px) minmax(180px, 1fr) repeat(2, minmax(104px, 130px));
      gap: 10px;
      padding: 12px 14px;
      align-items: end;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
    }
    select, input, button {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      padding: 0 10px;
    }
    button {
      cursor: pointer;
      font-weight: 650;
    }
    button.primary {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    button.danger {
      color: var(--bad);
      border-color: #efaaa5;
      background: #fff7f6;
    }
    button:disabled {
      opacity: 0.55;
      cursor: default;
    }
    .topic-list, .edge-list, .event-list { display: grid; gap: 8px; }
    .topic, .edge, .event {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fbfcfe;
      min-width: 0;
    }
    .topic-head, .edge-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
    }
    .name {
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      overflow-wrap: anywhere;
    }
    .badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }
    .badge.ok { color: var(--good); border-color: #98d4b8; background: #eefbf5; }
    .badge.bad { color: var(--bad); border-color: #efaaa5; background: #fff2f1; }
    .badge.warn { color: var(--warn); border-color: #e5c36b; background: #fff8dc; }
    .meta {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .graph {
      position: relative;
      min-height: 360px;
      overflow: hidden;
      border-top: 1px solid var(--line);
      background:
        linear-gradient(#eef1f5 1px, transparent 1px),
        linear-gradient(90deg, #eef1f5 1px, transparent 1px);
      background-size: 28px 28px;
    }
    .node {
      position: absolute;
      width: 168px;
      min-height: 54px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      padding: 8px;
      box-shadow: 0 5px 15px rgba(15, 23, 42, 0.08);
    }
    .node .name { font-size: 12px; }
    .node small { color: var(--muted); display: block; margin-top: 4px; }
    svg.links {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    pre {
      margin: 8px 0 0;
      max-height: 180px;
      overflow: auto;
      font-size: 12px;
      white-space: pre-wrap;
    }
    @media (max-width: 960px) {
      main { grid-template-columns: 1fr; }
      .live-workspace { grid-template-columns: 1fr; }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .control-panel { grid-template-columns: 1fr 1fr; }
      .replay-toolbar { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body data-flow-dashboard>
  <header>
    <h1>Data Flow Dashboard</h1>
    <div class="status-row"><span id="statusDot" class="dot"></span><span id="statusText">Connecting</span></div>
  </header>
  <main id="app">
    <div class="live-workspace">
      <div class="live-stack">
        <section>
          <h2>Robot State <span id="telemetryMeta" class="badge">waiting</span></h2>
          <div class="robot-stage">
            <span class="stage-caption">UR5e simplified forward-kinematics view</span>
            <canvas id="robotCanvas" aria-label="UR5e joint-state view"></canvas>
          </div>
        </section>
        <section>
          <h2>Camera Views <span class="badge">CompressedImage</span></h2>
          <div class="content camera-grid">
            <div class="camera-card">
              <img id="cameraExternal" alt="External camera unavailable">
              <div class="camera-caption"><span>Scene / external</span><span id="cameraExternalMeta">unavailable</span></div>
            </div>
            <div class="camera-card">
              <img id="cameraWrist" alt="Wrist camera unavailable">
              <div class="camera-caption"><span>Wrist camera</span><span id="cameraWristMeta">unavailable</span></div>
            </div>
          </div>
        </section>
      </div>
      <section>
        <h2>Realtime Telemetry</h2>
        <div class="telemetry-stack">
          <div class="chart-card"><div class="chart-head"><strong>Joint Position (qpos)</strong><span>rad</span></div><canvas id="qposChart"></canvas><div id="qposLegend" class="chart-legend"></div></div>
          <div class="chart-card"><div class="chart-head"><strong>Joint Velocity (qvel)</strong><span>rad/s</span></div><canvas id="qvelChart"></canvas><div id="qvelLegend" class="chart-legend"></div></div>
          <div class="chart-card"><div class="chart-head"><strong>Effort / Torque</strong><span>Nm</span></div><canvas id="effortChart"></canvas><div id="effortLegend" class="chart-legend"></div></div>
        </div>
      </section>
    </div>
    <section>
      <h2>Capture</h2>
      <div class="control-panel">
        <label>Mode
          <select id="captureMode">
            <option value="teleop">teleop</option>
            <option value="http">http</option>
            <option value="policy">policy</option>
          </select>
        </label>
        <label>Task Name
          <input id="captureTask" value="teleop_segment_01">
        </label>
        <button id="newTask">New Task</button>
        <button id="startCapture" class="primary">Start Capture</button>
        <button id="stopCapture" class="danger">Stop Capture</button>
      </div>
      <div class="content"><div id="capture" class="event-list"></div></div>
    </section>
    <section>
      <h2>Key Topics</h2>
      <div id="summary" class="summary"></div>
      <div class="content"><div id="topics" class="topic-list"></div></div>
    </section>
    <section>
      <h2>Advanced Topology</h2>
      <div class="content"><div id="edges" class="edge-list"></div></div>
    </section>
    <section>
      <h2>Quality</h2>
      <div class="content"><div id="quality" class="event-list"></div></div>
    </section>
    <section>
      <h2>Replay</h2>
      <div class="replay-toolbar">
        <label>Dataset Path<input id="replayDatasetPath" value=""></label>
        <label>Replay Episode<select id="replayEpisode"><option value="0">Episode 000000</option></select></label>
        <label>Rate Hz<input id="replayRateHz" type="number" min="0.1" step="0.1" value="10"></label>
        <button id="loadReplayEpisodes">Load</button>
        <button id="startReplay" class="primary">Replay</button>
        <button id="pauseReplay">Pause</button>
        <button id="resumeReplay">Resume</button>
        <button id="stopReplay" class="danger">Stop</button>
      </div>
      <div class="content"><div id="replay" class="event-list"></div></div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const KEY_TOPICS = [
      "/joint_states",
      "/robotiq_2f_gripper/joint_states",
      "/camera2/scene_camera/color/image_raw/compressed",
      "/camera1/wrist_camera/color/image_raw/compressed",
      "/tcp_pose_broadcaster/pose",
    ];
    const cameraTimestamps = {};
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
    function age(value) {
      if (value === null || value === undefined) return "-";
      return `${Number(value).toFixed(2)}s`;
    }
    function updateCamera(name, imageId, metaId, cameras) {
      const image = $(imageId);
      const meta = $(metaId);
      const item = (cameras || {})[name] || {};
      if (!item.valid || item.last_timestamp === null || item.last_timestamp === undefined) {
        image.removeAttribute("src");
        meta.textContent = "unavailable";
        delete cameraTimestamps[name];
        return;
      }
      if (cameraTimestamps[name] !== item.last_timestamp) {
        image.src = `/api/camera/${encodeURIComponent(name)}?t=${encodeURIComponent(item.last_timestamp)}`;
        cameraTimestamps[name] = item.last_timestamp;
      }
      meta.textContent = `${item.codec || "compressed"} | age ${age(item.age_s)}`;
    }
    const chartColors = ["#2563eb", "#c2413a", "#1d8b5b", "#7c3aed", "#d97706", "#0f8b8d"];
    function canvasContext(canvas) {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(320, Math.floor(rect.width || 640));
      const height = Math.max(120, Math.floor(rect.height || 145));
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      const context = canvas.getContext("2d");
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { context, width, height };
    }
    function drawRobot(telemetry) {
      const canvas = $("robotCanvas");
      const { context: ctx, width, height } = canvasContext(canvas);
      ctx.clearRect(0, 0, width, height);
      const qpos = (telemetry && telemetry.latest && telemetry.latest.qpos) || [];
      const lengths = [58, 78, 72, 58, 44, 34];
      let x = width * 0.5;
      let y = height - 28;
      let angle = -Math.PI / 2;
      const points = [[x, y]];
      for (let i = 0; i < lengths.length; i++) {
        angle += Number(qpos[i] || 0) * (i === 0 ? 0.4 : 0.7);
        x += lengths[i] * Math.cos(angle);
        y += lengths[i] * Math.sin(angle);
        points.push([x, y]);
      }
      ctx.strokeStyle = "#17212b";
      ctx.lineWidth = 15;
      ctx.lineCap = "round";
      ctx.beginPath();
      points.forEach((point, index) => index ? ctx.lineTo(point[0], point[1]) : ctx.moveTo(point[0], point[1]));
      ctx.stroke();
      points.forEach((point, index) => {
        ctx.fillStyle = index === points.length - 1 ? "#2563eb" : "#64748b";
        ctx.beginPath();
        ctx.arc(point[0], point[1], index === 0 ? 17 : 11, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#f8fafc";
        ctx.beginPath();
        ctx.arc(point[0], point[1], 3, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.fillStyle = "#657386";
      ctx.font = "12px system-ui";
      ctx.fillText("base_link", width * 0.5 - 28, height - 8);
      ctx.fillText("tool0", Math.min(width - 48, x + 9), Math.max(16, y - 10));
    }
    function drawChart(canvasId, legendId, field, telemetry) {
      const canvas = $(canvasId);
      const { context: ctx, width, height } = canvasContext(canvas);
      ctx.clearRect(0, 0, width, height);
      ctx.strokeStyle = "#e2e8f0";
      ctx.lineWidth = 1;
      for (let y = 20; y < height; y += 28) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
      for (let x = 0; x < width; x += 70) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
      const history = (telemetry && telemetry.history) || [];
      const latest = (telemetry && telemetry.latest) || {};
      const values = history.length ? history : [{ [field]: latest[field] || [] }];
      const jointCount = Math.min(6, Math.max(1, ...values.map((item) => (item[field] || []).length)));
      for (let joint = 0; joint < jointCount; joint++) {
        ctx.strokeStyle = chartColors[joint];
        ctx.lineWidth = 2;
        ctx.beginPath();
        values.forEach((item, index) => {
          const vector = item[field] || [];
          const number = Number(vector[joint] || 0);
          const x = values.length === 1 ? width / 2 : index * width / (values.length - 1);
          const y = height / 2 - Math.max(-1, Math.min(1, number / (field === "effort" ? 20 : field === "qvel" ? 3 : 3))) * (height * 0.38);
          if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      const names = (latest.joint_names || []).slice(0, jointCount);
      $(legendId).innerHTML = Array.from({ length: jointCount }, (_, index) => `<span><i style="background:${chartColors[index]}"></i>${esc(names[index] || `joint_${index + 1}`)}</span>`).join("");
    }
    function updateTelemetry(telemetry) {
      drawRobot(telemetry || {});
      drawChart("qposChart", "qposLegend", "qpos", telemetry || {});
      drawChart("qvelChart", "qvelLegend", "qvel", telemetry || {});
      drawChart("effortChart", "effortLegend", "effort", telemetry || {});
      const latest = (telemetry && telemetry.latest) || {};
      const mode = telemetry && telemetry.mode || "live";
      $("telemetryMeta").textContent = `${mode} | ${latest.qpos && latest.qpos.length ? "active" : "waiting"}`;
    }
    function topicRows(flow) {
      const allTopics = (flow && flow.topics) || {};
      const topics = KEY_TOPICS.map((name) => [name, allTopics[name] || { seen: false, active: false }]);
      if (!topics.length) return '<div class="event">No flow data</div>';
      return topics.map(([name, item]) => `
        <div class="topic">
          <div class="topic-head">
            <div class="name">${esc(name)}</div>
            <span class="badge ${item.active ? "ok" : item.seen ? "warn" : "bad"}">${item.active ? "active" : item.seen ? "stale" : "unseen"}</span>
          </div>
          <div class="meta">age ${age(item.age_s)} | pubs ${item.publisher_count || 0} | subs ${item.subscriber_count || 0}</div>
          <div class="meta">${esc(item.topic_type || "unknown type")}</div>
        </div>
      `).join("");
    }
    function edgeRows(topology) {
      const edges = (topology && topology.edges) || [];
      if (!edges.length) return '<div class="edge">No graph edges</div>';
      return edges.slice(0, 12).map((edge) => `
        <div class="edge">
          <div class="edge-head"><span class="name">${esc(edge.from)} -> ${esc(edge.to)}</span></div>
          <div class="meta">${esc(edge.topic)}</div>
        </div>
      `).join("");
    }
    function summary(flow, topology) {
      const topicValues = Object.values((flow && flow.topics) || {});
      const active = topicValues.filter((topic) => topic.active).length;
      const stale = topicValues.filter((topic) => topic.seen && !topic.active).length;
      const unseen = topicValues.filter((topic) => !topic.seen).length;
      const edges = ((topology && topology.edges) || []).length;
      return [
        ["Active", active],
        ["Stale", stale],
        ["Unseen", unseen],
        ["Edges", edges],
      ].map(([label, value]) => `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
    }
    function eventBlock(title, payload, source) {
      const valid = source && source.valid;
      const badge = valid ? "ok" : "bad";
      const label = valid ? "valid" : "missing";
      return `<div class="event"><div class="topic-head"><strong>${esc(title)}</strong><span class="badge ${badge}">${label}</span></div><div class="meta">age ${age(source && source.age_s)}</div><pre>${esc(JSON.stringify(payload || source, null, 2))}</pre></div>`;
    }
    function captureBlock(status) {
      const running = status && status.running;
      $("startCapture").disabled = !!running;
      $("stopCapture").disabled = !running;
      $("newTask").disabled = !!running;
      const badge = running ? "ok" : "warn";
      const label = running ? "running" : "stopped";
      return `<div class="event">
        <div class="topic-head"><strong>Collector</strong><span class="badge ${badge}">${label}</span></div>
        <div class="meta">Dataset Path ${esc(status && status.dataset_dir || "-")}</div>
      </div>`;
    }
    async function newTask() {
      const task = $("captureTask").value || "capture_task";
      const response = await fetch("/api/capture/new-task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task })
      });
      const result = await response.json();
      if (!result.ok) alert(result.error || "Failed to create task");
      await refresh();
    }
    async function startCapture() {
      const runtimeMode = $("captureMode").value;
      const task = $("captureTask").value || `${runtimeMode}_segment`;
      const response = await fetch("/api/capture/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runtime_mode: runtimeMode, task })
      });
      const result = await response.json();
      if (!result.ok) alert(result.error || "Failed to start capture");
      await refresh();
    }
    async function stopCapture() {
      await fetch("/api/capture/stop", { method: "POST" });
      await refresh();
    }
    async function loadReplayEpisodes() {
      const datasetDir = $("replayDatasetPath").value.trim();
      const response = await fetch(`/api/replay/episodes?dataset_dir=${encodeURIComponent(datasetDir)}`, { cache: "no-store" });
      const result = await response.json();
      if (!result.ok) { alert(result.error || "Failed to load episodes"); return; }
      $("replayEpisode").innerHTML = (result.episodes || []).map((episode) => `<option value="${episode.episode_index}">Episode ${String(episode.episode_index).padStart(6, "0")} (${episode.frame_count} frames)</option>`).join("");
    }
    async function startReplay() {
      const response = await fetch("/api/replay/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataset_dir: $("replayDatasetPath").value.trim(),
          episode_index: Number($("replayEpisode").value || 0),
          rate_hz: Number($("replayRateHz").value || 10),
        })
      });
      const result = await response.json();
      if (!result.ok) alert(result.error || "Failed to start replay");
      await refresh();
    }
    async function pauseReplay() {
      await fetch("/api/replay/pause", { method: "POST" });
      await refresh();
    }
    async function resumeReplay() {
      await fetch("/api/replay/resume", { method: "POST" });
      await refresh();
    }
    async function stopReplay() {
      await fetch("/api/replay/stop", { method: "POST" });
      await refresh();
    }
    async function refresh() {
      const response = await fetch("/api/state", { cache: "no-store" });
      const state = await response.json();
      $("statusDot").className = "dot ok";
      $("statusText").textContent = `Updated ${new Date().toLocaleTimeString()}`;
      $("summary").innerHTML = summary(state.flow_status, state.topology_graph);
      $("capture").innerHTML = captureBlock(state.capture_status || {});
      updateCamera("external", "cameraExternal", "cameraExternalMeta", state.cameras);
      updateCamera("wrist", "cameraWrist", "cameraWristMeta", state.cameras);
      updateTelemetry(state.telemetry || {});
      $("topics").innerHTML = topicRows(state.flow_status);
      $("edges").innerHTML = edgeRows(state.topology_graph);
      $("quality").innerHTML = eventBlock("Quality Status", state.quality_status, state.sources.quality_status) + eventBlock("Drop Reason", state.drop_reason, state.sources.drop_reason);
      $("replay").innerHTML = eventBlock("Replay Status", state.replay_status, state.sources.replay_status);
    }
    $("newTask").addEventListener("click", newTask);
    $("startCapture").addEventListener("click", startCapture);
    $("stopCapture").addEventListener("click", stopCapture);
    $("loadReplayEpisodes").addEventListener("click", loadReplayEpisodes);
    $("startReplay").addEventListener("click", startReplay);
    $("pauseReplay").addEventListener("click", pauseReplay);
    $("resumeReplay").addEventListener("click", resumeReplay);
    $("stopReplay").addEventListener("click", stopReplay);
    async function loop() {
      try { await refresh(); }
      catch (error) {
        $("statusDot").className = "dot";
        $("statusText").textContent = "Disconnected";
      }
      setTimeout(loop, 500);
    }
    loop();
  </script>
</body>
</html>"""
