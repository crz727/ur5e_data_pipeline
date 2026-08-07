import json
import pytest

from data_collection_pkg.visualization.web_dashboard import (
    DashboardStateStore,
    create_dashboard_app,
)
from data_collection_pkg.visualization.capture_manager import CaptureManager


def test_dashboard_state_store_updates_from_ros_json_topics():
    store = DashboardStateStore()
    store.update_json(
        "topology_graph",
        json.dumps({
            "topics": {
                "/joint_states": {
                    "publishers": ["/ur_driver"],
                    "subscribers": ["/collector"],
                }
            },
            "edges": [
                {"from": "/ur_driver", "to": "/collector", "topic": "/joint_states"}
            ],
        }),
        timestamp=10.0,
    )
    store.update_json(
        "flow_status",
        json.dumps({
            "topics": {
                "/joint_states": {
                    "seen": True,
                    "active": True,
                    "age_s": 0.02,
                    "publisher_count": 1,
                    "subscriber_count": 1,
                }
            }
        }),
        timestamp=10.1,
    )

    state = store.snapshot(now=10.2)

    assert state["topology_graph"]["edges"][0]["topic"] == "/joint_states"
    assert state["flow_status"]["topics"]["/joint_states"]["active"] is True
    assert state["sources"]["topology_graph"]["age_s"] == pytest.approx(0.2)
    assert state["sources"]["flow_status"]["valid"] is True


def test_dashboard_state_store_records_invalid_json_without_crashing():
    store = DashboardStateStore()
    store.update_json("flow_status", "{bad-json", timestamp=3.0)

    state = store.snapshot(now=4.0)

    assert state["sources"]["flow_status"]["valid"] is False
    assert "Expecting property name" in state["sources"]["flow_status"]["error"]


def test_dashboard_serves_latest_compressed_camera_frame():
    jpeg = b"\xff\xd8dashboard-jpeg\xff\xd9"
    store = DashboardStateStore()
    store.update_image("external", jpeg, codec="jpeg", timestamp=4.0)
    app = create_dashboard_app(store)
    client = app.test_client()

    state = client.get("/api/state")
    image = client.get("/api/camera/external")

    assert state.get_json()["cameras"]["external"]["codec"] == "jpeg"
    assert state.get_json()["cameras"]["external"]["age_s"] >= 0
    assert image.status_code == 200
    assert image.mimetype == "image/jpeg"
    assert image.data == jpeg


def test_dashboard_state_store_tracks_telemetry_history_and_latest_values():
    store = DashboardStateStore()
    store.update_telemetry(
        {
            "joint_names": ["shoulder_pan_joint", "elbow_joint"],
            "qpos": [0.1, 0.2],
            "qvel": [0.3, 0.4],
            "effort": [0.5, 0.6],
            "gripper": 0.7,
        },
        timestamp=10.0,
    )
    store.update_telemetry({"qpos": [0.2, 0.3]}, timestamp=10.1)

    telemetry = store.snapshot(now=10.2)["telemetry"]

    assert telemetry["latest"]["qpos"] == [0.2, 0.3]
    assert telemetry["latest"]["gripper"] == 0.7
    assert telemetry["mode"] == "live"
    assert len(telemetry["history"]) == 2
    assert telemetry["history"][0]["timestamp"] == 10.0


def test_dashboard_index_contains_unified_realtime_workspace():
    app = create_dashboard_app(DashboardStateStore())
    index = app.test_client().get("/")

    assert b"live-workspace" in index.data
    assert b"robotCanvas" in index.data
    assert b"qposChart" in index.data
    assert b"Replay Episode" in index.data
    assert b"Drop Reason" in index.data
    assert b'"/data_collection/quality_status",' not in index.data
    assert b'"/data_collection/drop_reason",' not in index.data


def test_dashboard_flask_app_serves_index_and_state_api():
    store = DashboardStateStore()
    store.update_json(
        "quality_status",
        json.dumps({"ok": True, "frame_count": 12}),
        timestamp=1.0,
    )
    app = create_dashboard_app(store)
    client = app.test_client()

    index = client.get("/")
    state = client.get("/api/state")

    assert index.status_code == 200
    assert b"id=\"app\"" in index.data
    assert b"data-flow-dashboard" in index.data
    assert b"Task Name" in index.data
    assert b"New Task" in index.data
    assert b"Start Capture" in index.data
    assert b"Stop Capture" in index.data
    assert b"captureMode" in index.data
    assert b"Dataset Path" in index.data
    assert b"Current Task Folder" not in index.data
    assert b"log ${esc" not in index.data
    assert state.status_code == 200
    assert state.get_json()["quality_status"]["frame_count"] == 12


def test_dashboard_replay_seek_api_rejects_idle_replay():
    app = create_dashboard_app(DashboardStateStore())
    client = app.test_client()

    response = client.post("/api/replay/seek", json={"frame_index": 0})

    assert response.status_code == 409
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"] == "replay is not running or paused"


def test_dashboard_capture_api_delegates_to_manager():
    class FakeManager:
        def __init__(self):
            self.new_task_payload = None
            self.started = None
            self.stopped = False
            self.annotation_payload = None

        def new_task(self, payload):
            self.new_task_payload = payload
            return {"ok": True, "task": payload["task"], "task_root": "/tmp/demo_task"}

        def start(self, payload):
            self.started = payload
            return {"ok": True, "running": True, "runtime_mode": payload["runtime_mode"]}

        def stop(self):
            self.stopped = True
            return {"ok": True, "running": False}

        def annotate(self, payload):
            self.annotation_payload = payload
            return {"ok": True, "outcome": payload["outcome"], "episode_indices": [0]}

        def clean(self, payload):
            self.clean_payload = payload
            return {"ok": True, "accepted_episode_indices": [0], "report_path": "/tmp/report.html"}

        def task_labels(self):
            return {"ok": True, "labels": [{"task_id": "pick_red_block"}]}

        def preflight_lerobot_export(self, payload):
            self.preflight_payload = payload
            return {
                "ok": True,
                "profile": "vla",
                "eligible": [{"episode_index": 10}],
                "skipped": [{"episode_index": 11, "reason": "missing_english_instruction"}],
                "planned_report_path": "/tmp/lerobot-export/meta/vla_export_report.json",
            }

        def export_lerobot(self, payload):
            self.export_payload = payload
            return {"ok": True, "output_dir": payload["output_dir"], "verification_report_path": "/tmp/export-report.json"}

        def start_lerobot_export(self, payload):
            self.export_payload = payload
            return {"ok": True, "status": "queued", "job_id": 1}

        def lerobot_export_status(self):
            return {"ok": True, "status": "running", "job_id": 1}

        def status(self):
            return {"running": False}

    manager = FakeManager()
    app = create_dashboard_app(DashboardStateStore(), capture_manager=manager)
    client = app.test_client()

    new_task = client.post(
        "/api/capture/new-task",
        json={"task": "pick_red_block"},
    )
    started = client.post(
        "/api/capture/start",
        json={"runtime_mode": "http", "task": "http_segment_01"},
    )
    stopped = client.post("/api/capture/stop")
    annotation = client.post("/api/capture/annotate", json={"outcome": "failure"})
    cleaned = client.post(
        "/api/capture/clean",
        json={"dataset_dir": "/tmp/original/teleop/qpos_gripper"},
    )
    labels = client.get("/api/capture/task-labels")
    preflight = client.post(
        "/api/capture/export-lerobot/preflight",
        json={
            "cleaned_dataset_dir": "/tmp/cleaned/teleop/qpos_gripper",
            "output_dir": "/tmp/lerobot-export",
            "profile": "vla",
        },
    )
    exported = client.post(
        "/api/capture/export-lerobot",
        json={
            "cleaned_dataset_dir": "/tmp/cleaned/teleop/qpos_gripper",
            "output_dir": "/tmp/lerobot-export",
        },
    )

    assert new_task.status_code == 200
    assert new_task.get_json()["task_root"] == "/tmp/demo_task"
    assert manager.new_task_payload["task"] == "pick_red_block"
    assert started.status_code == 200
    assert started.get_json()["runtime_mode"] == "http"
    assert manager.started["task"] == "http_segment_01"
    assert stopped.status_code == 200
    assert manager.stopped is True
    assert annotation.status_code == 200
    assert annotation.get_json()["episode_indices"] == [0]
    assert manager.annotation_payload == {"outcome": "failure"}
    assert cleaned.status_code == 200
    assert cleaned.get_json()["report_path"] == "/tmp/report.html"
    assert manager.clean_payload == {"dataset_dir": "/tmp/original/teleop/qpos_gripper"}
    assert labels.status_code == 200
    assert labels.get_json()["labels"] == [{"task_id": "pick_red_block"}]
    assert preflight.status_code == 200
    assert preflight.get_json()["planned_report_path"].endswith("vla_export_report.json")
    assert manager.preflight_payload["profile"] == "vla"
    export_status = client.get("/api/capture/export-lerobot/status")

    assert exported.status_code == 202
    assert exported.get_json()["status"] == "queued"
    assert export_status.status_code == 200
    assert export_status.get_json()["status"] == "running"
    assert manager.export_payload["cleaned_dataset_dir"].endswith("qpos_gripper")


def test_dashboard_preflight_and_task_labels_require_capture_controls():
    app = create_dashboard_app(DashboardStateStore())
    client = app.test_client()

    labels = client.get("/api/capture/task-labels")
    preflight = client.post("/api/capture/export-lerobot/preflight", json={})

    assert labels.status_code == 409
    assert labels.get_json()["error"] == "capture controls disabled"
    assert preflight.status_code == 409
    assert preflight.get_json()["error"] == "capture controls disabled"


def test_dashboard_preflight_rejects_non_object_json_payloads():
    class Manager:
        def preflight_lerobot_export(self, _payload):
            return {"ok": True, "profile": "act"}

    app = create_dashboard_app(DashboardStateStore(), capture_manager=Manager())
    client = app.test_client()

    string_payload = client.post("/api/capture/export-lerobot/preflight", json="invalid")
    list_payload = client.post("/api/capture/export-lerobot/preflight", json=["invalid"])

    for response in (string_payload, list_payload):
        assert response.status_code == 409
        assert response.get_json()["ok"] is False
        assert response.get_json()["error"] == "preflight payload must be a JSON object"


def test_dashboard_preflight_rejects_null_or_non_string_output_dir(tmp_path):
    manager = CaptureManager(root=tmp_path)
    app = create_dashboard_app(DashboardStateStore(), capture_manager=manager)
    client = app.test_client()
    payload = {
        "cleaned_dataset_dir": str(tmp_path / "cleaned" / "teleop" / "qpos_gripper"),
        "profile": "vla",
    }

    null_output = client.post(
        "/api/capture/export-lerobot/preflight",
        json={**payload, "output_dir": None},
    )
    numeric_output = client.post(
        "/api/capture/export-lerobot/preflight",
        json={**payload, "output_dir": 17},
    )

    for response in (null_output, numeric_output):
        assert response.status_code == 409
        assert response.get_json()["ok"] is False
        assert response.get_json()["error"] == "output_dir must be a non-empty string"
    assert manager._export_thread is None
