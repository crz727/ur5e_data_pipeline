# Capture Outcome Annotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate Qt capture start/stop controls with one toggle button and persist a human success/failure annotation for every episode created by that capture run.

**Architecture:** `CaptureManager` snapshots existing episode indices when a run starts, finds the newly written indices after it stops, and appends one annotation per new episode. The Flask dashboard exposes this as a narrowly scoped API. The Qt panel toggles capture state from the backend, stops the active capture, then displays a modal result dialog before it submits the annotation.

**Tech Stack:** Python 3.10, Flask, Qt5/C++, ROS 2 Humble, pytest, colcon.

## Global Constraints

- Do not implement automatic candidate-success/failure classification in this feature.
- Do not modify recorded JSONL frames or `meta/episodes.jsonl`.
- Store annotations in `meta/episode_annotations.jsonl`; every row must have an `episode_index`.
- Store a missing or dismissed annotation as unreviewed by omitting its row.
- Only `success` and `failure` are valid human outcome values.
- Preserve the existing capture API behavior for external clients.

---

### Task 1: Persist Capture Annotations

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Test: `data_collection_pkg/test/test_capture_manager.py`

**Interfaces:**
- Produces: `CaptureManager.annotate(payload: Mapping) -> dict`
- Input: `{"outcome": "success" | "failure"}` after a stopped capture.
- Output: `{"ok": True, "outcome": str, "annotation_path": str, "dataset_dir": str, "episode_indices": list[int]}`.
- Internal state: `_episode_indices_before: set[int]` is captured before the collector process starts; `_last_stopped_episode_indices: tuple[int, ...]` is calculated after it exits.

- [x] **Step 1: Write the failing tests**

```python
def test_capture_manager_writes_success_annotation_after_stop(tmp_path):
    manager = CaptureManager(root=tmp_path, popen=FakePopen, now=lambda: 10.0)
    manager.start({"runtime_mode": "teleop", "task": "pick"})
    manager.stop()

    result = manager.annotate({"outcome": "success"})

    annotation = json.loads(Path(result["annotation_path"]).read_text().strip())
    assert annotation["episode_index"] == 0
    assert annotation["outcome"] == "success"


def test_capture_manager_rejects_annotation_while_running_or_with_invalid_outcome(tmp_path):
    manager = CaptureManager(root=tmp_path, popen=FakePopen, now=lambda: 10.0)
    manager.start({"runtime_mode": "teleop", "task": "pick"})

    assert manager.annotate({"outcome": "success"})["ok"] is False
    manager.stop()
    assert manager.annotate({"outcome": "unknown"})["ok"] is False
```

- [x] **Step 2: Run the tests and verify they fail**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test/test_capture_manager.py`

Expected: `AttributeError` because `annotate` does not exist.

- [x] **Step 3: Implement `CaptureManager.annotate`**

```python
# In start(), before Popen:
self._episode_indices_before = _episode_indices(dataset_dir)

# In stop(), after process.wait() and before returning status:
self._last_stopped_episode_indices = tuple(sorted(
    _episode_indices(Path(status["dataset_dir"])) - self._episode_indices_before
))

def annotate(self, payload: Mapping) -> dict:
    if self._is_running() or not self._last_stopped_episode_indices:
        return {"ok": False, "error": "stop a completed capture before annotation"}
    outcome = str(payload.get("outcome", "")).strip().lower()
    if outcome not in {"success", "failure"}:
        return {"ok": False, "error": "outcome must be success or failure"}
    dataset_dir = Path(self.status()["dataset_dir"])
    annotation_path = dataset_dir / "meta" / "episode_annotations.jsonl"
    annotation_path.parent.mkdir(parents=True, exist_ok=True)
    with annotation_path.open("a", encoding="utf-8") as stream:
        for episode_index in self._last_stopped_episode_indices:
            stream.write(json.dumps({
                "schema_version": 1,
                "episode_index": episode_index,
                "outcome": outcome,
                "review_status": "reviewed",
                "annotated_at": self.now(),
                "source": "human",
            }, ensure_ascii=False) + "\n")
    return {"ok": True, "outcome": outcome, "annotation_path": str(annotation_path), "dataset_dir": str(dataset_dir), "episode_indices": list(self._last_stopped_episode_indices)}


def _episode_indices(dataset_dir: Path) -> set[int]:
    metadata_path = dataset_dir / "meta" / "episodes.jsonl"
    if not metadata_path.exists():
        return set()
    return {
        int(json.loads(line)["episode_index"])
        for line in metadata_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }
```

- [x] **Step 4: Run the tests and verify they pass**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test/test_capture_manager.py`

Expected: all capture-manager tests pass.

### Task 2: Expose the Annotation API

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py`
- Modify: `data_collection_pkg/test/test_data_collection_web_dashboard.py`

**Interfaces:**
- Produces: `POST /api/capture/annotate`.
- Consumes: JSON payload `{"outcome": "success" | "failure"}`.
- Delegates: `capture_manager.annotate(payload)`.

- [x] **Step 1: Write the failing API test**

```python
response = client.post("/api/capture/annotate", json={"outcome": "failure"})

assert response.status_code == 200
assert manager.annotation_payload == {"outcome": "failure"}
```

- [x] **Step 2: Run the API test and verify it fails with 404**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test/test_data_collection_web_dashboard.py`

Expected: the annotation route is absent.

- [x] **Step 3: Add the Flask endpoint**

```python
@app.post("/api/capture/annotate")
def api_capture_annotate():
    if capture_manager is None:
        return jsonify({"ok": False, "available": False, "error": "capture controls disabled"}), 404
    result = capture_manager.annotate(request.get_json(silent=True) or {})
    return jsonify(result), 200 if result.get("ok") else 409
```

- [x] **Step 4: Run the API test and verify it passes**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test/test_data_collection_web_dashboard.py`

Expected: all dashboard tests pass.

### Task 3: Replace Qt Capture Buttons With an Outcome Dialog

**Files:**
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- Produces: one `capture_toggle_button_` with idle text `Start Capture` and running text `Stop Capture`.
- Consumes: `/api/capture/start`, `/api/capture/stop`, and `/api/capture/annotate`.
- Produces: `QMessageBox` success/failure decision after a successful stop response.

- [x] **Step 1: Write the failing panel contract assertions**

```python
assert "capture_toggle_button_" in main_window
assert "Start Capture" in main_window
assert "Stop Capture" in main_window
assert "/api/capture/annotate" in main_window
assert "QMessageBox" in main_window
assert "start_capture" not in main_window
assert "stop_capture" not in main_window
```

- [x] **Step 2: Run the panel contract test and verify it fails**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py`

Expected: the toggle button and annotation endpoint references are absent.

- [x] **Step 3: Implement the toggle and modal flow**

```cpp
connect(capture_toggle_button_, &QPushButton::clicked, this, [this]() {
  if (capture_running_) {
    post_capture_stop_then_request_outcome();
  } else {
    post_json(QStringLiteral("/api/capture/start"), {
      {QStringLiteral("runtime_mode"), capture_mode_->currentText()},
      {QStringLiteral("task"), capture_task_->text()}});
  }
});
```

`post_capture_stop_then_request_outcome()` must request `/api/capture/stop`, require an `ok` response, show a `QMessageBox` with Success, Failure, and Cancel buttons, and submit only Success or Failure to `/api/capture/annotate`. `update_dashboard_state()` must update the toggle text and danger styling from `capture_status.running`.

- [x] **Step 4: Run the panel contract test and compile the panel**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py && source /opt/ros/humble/setup.bash && colcon build --packages-select data_collection_rviz_panel`

Expected: test passes and `data_collection_rviz_panel` compiles.

### Task 4: Full Verification

**Files:**
- No production file changes.

- [x] **Step 1: Run package tests**

Run: `source /opt/ros/humble/setup.bash && PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q test /home/crz/src/data_collection_rviz_panel/test`

Expected: all Python tests pass.

- [x] **Step 2: Run ROS package tests**

Run: `source /opt/ros/humble/setup.bash && colcon test --packages-select data_collection_pkg data_collection_rviz_panel && colcon test-result --verbose`

Expected: 0 errors and 0 failures.

- [ ] **Step 3: Smoke test the UI**

1. Start capture and verify one button changes to `Stop Capture`.
2. Stop capture and choose Success; verify `meta/episode_annotations.jsonl` contains the newly recorded `episode_index` and `"outcome": "success"`.
3. Repeat and choose Failure; verify a new JSONL row contains only the newly recorded `episode_index` and `"outcome": "failure"`.
4. Stop and dismiss the dialog; verify no annotation row is appended.
