# Dataset Cleaning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable offline cleaner that copies only human-approved, technically valid episodes from an `original` qpos dataset into its sibling `cleaned` dataset and makes the operation available from the Qt Capture panel.

**Architecture:** A new dataset-only cleaner reads `original/<runtime_mode>/qpos_gripper`, combines existing `QualityConfig.trainable` validation with the latest human annotation for each episode, and creates a fresh sibling `cleaned/<runtime_mode>/qpos_gripper` directory. It writes a machine-readable manifest and a standalone HTML report. The Flask dashboard exposes a narrow cleaning endpoint; the Qt panel obtains the current capture dataset path, asks for confirmation, then opens the generated report.

**Tech Stack:** Python 3.10, Flask, Qt5/C++, ROS 2 Humble, pytest, colcon.

## Global Constraints

- Modify only `data_collection_pkg` and the necessary Qt panel integration points.
- Original JSONL, images, episode metadata, and human annotations are immutable.
- Input must be a directory segment named `original/<runtime_mode>/qpos_gripper`; output is its sibling `cleaned/<runtime_mode>/qpos_gripper`.
- A cleaning run is rejected while capture is running.
- An accepted episode requires latest human annotation `outcome == "success"` and no enabled quality issue.
- A `failure` annotation rejects the episode; missing annotation is `needs_review` and is not copied.
- Cleaning never trims or repairs individual frames in this release.
- Output contains `meta/episodes.jsonl`, copied `data/` and `images/` trees, `meta/episode_annotations.jsonl`, `meta/cleaning_manifest.jsonl`, `meta/cleaning_summary.json`, and `meta/cleaning_report.html`.

---

### Task 1: Implement an Auditable Dataset Cleaner

**Files:**
- Create: `data_collection_pkg/data_collection_pkg/dataset/cleaner.py`
- Test: `data_collection_pkg/test/test_data_collection_cleaner.py`

**Interfaces:**
- Produces: `CleaningConfig` with conservative defaults: two required cameras, JPEG decoding, 100 ms maximum camera sync delta, 10 Hz target, 30-frame minimum, 2 s minimum duration.
- Produces: `clean_original_dataset(dataset_dir: Path, config: CleaningConfig | None = None) -> dict`.
- Input: the absolute qpos dataset path below an `original` directory.
- Output: `{"ok": True, "source_dataset_dir": str, "cleaned_dataset_dir": str, "report_path": str, "accepted_episode_indices": list[int], "rejected_episode_indices": list[int], "needs_review_episode_indices": list[int]}`.

- [ ] **Step 1: Write failing cleaner tests**

```python
def test_cleaner_copies_only_successful_quality_approved_episode(tmp_path):
    source = make_original_dataset(tmp_path, annotations={0: "success", 1: "failure"})
    result = clean_original_dataset(source)

    cleaned = Path(result["cleaned_dataset_dir"])
    assert result["accepted_episode_indices"] == [0]
    assert result["rejected_episode_indices"] == [1]
    assert (cleaned / "data" / "episode_000000.jsonl").exists()
    assert not (cleaned / "data" / "episode_000001.jsonl").exists()
    assert source.exists()


def test_cleaner_marks_unannotated_and_invalid_episodes_with_reasons(tmp_path):
    source = make_original_dataset(tmp_path, annotations={0: "success"}, invalid_episode=1)
    result = clean_original_dataset(source)

    manifest = read_jsonl(Path(result["cleaned_dataset_dir"]) / "meta" / "cleaning_manifest.jsonl")
    assert manifest[0]["decision"] == "accepted"
    assert manifest[1]["decision"] == "rejected"
    assert "action_dim_mismatch" in manifest[1]["reasons"]
```

- [ ] **Step 2: Run tests to verify the missing module fails**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_cleaner.py`

Expected: import failure for `data_collection_pkg.dataset.cleaner`.

- [ ] **Step 3: Implement `clean_original_dataset`**

```python
def clean_original_dataset(dataset_dir: Path, config: CleaningConfig | None = None) -> dict:
    source = _validate_original_dataset_dir(Path(dataset_dir))
    destination = _cleaned_dataset_dir(source)
    decisions = _evaluate_episodes(source, config or CleaningConfig())
    _replace_clean_destination(destination)
    _copy_accepted_episodes(source, destination, decisions)
    _write_cleaning_artifacts(destination, source, decisions)
    return _summary(source, destination, decisions)
```

`_evaluate_episodes` must use `check_frame` and `_check_episode_summary` equivalents per episode so it can retain structured reason codes rather than parsing strings from a whole-dataset report. It must read the final annotation row for each `episode_index`. Image references are copied relative to the source dataset and must be rejected if they escape that dataset root or are missing.

- [ ] **Step 4: Run cleaner tests to verify they pass**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_cleaner.py`

Expected: both cleaner behavior tests pass.

### Task 2: Write Human-Readable Report and CLI Entry Point

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/cli.py`
- Modify: `data_collection_pkg/README.md`
- Test: `data_collection_pkg/test/test_data_collection_cli.py`
- Test: `data_collection_pkg/test/test_data_collection_cleaner.py`

**Interfaces:**
- Produces: `data_collection clean-original DATASET_DIR`.
- Output JSON includes source, output, report path, and decision counts.
- HTML report lists the configuration, run time, count cards, then one row per episode with outcome, decision, frame count, and rejection reasons.

- [ ] **Step 1: Write failing CLI and report tests**

```python
def test_clean_original_cli_prints_report_location(tmp_path, capsys):
    source = make_original_dataset(tmp_path, annotations={0: "success"})
    assert main(["clean-original", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["report_path"]).is_file()


def test_cleaning_html_report_explains_every_rejected_episode(tmp_path):
    result = clean_original_dataset(make_original_dataset(tmp_path, annotations={0: "failure"}))
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "episode 0" in report
    assert "human_outcome_failure" in report
```

- [ ] **Step 2: Run tests to verify parser/report behavior is absent**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_cli.py test/test_data_collection_cleaner.py`

Expected: parser rejects `clean-original`; report assertion fails.

- [ ] **Step 3: Add CLI command and report renderer**

```python
clean = subparsers.add_parser("clean-original", help="Create cleaned dataset from original episodes")
clean.add_argument("dataset_dir")

if args.command == "clean-original":
    result = clean_original_dataset(Path(args.dataset_dir))
    print(json.dumps(result, ensure_ascii=False))
    return 0
```

The README must document the immutable original-to-cleaned layout and the `clean-original` command. Report content must use HTML escaping for all filenames and JSON-derived strings.

- [ ] **Step 4: Run tests to verify CLI and report pass**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_cli.py test/test_data_collection_cleaner.py`

Expected: all cleaner and CLI tests pass.

### Task 3: Expose Cleaning Through the Dashboard API

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py`
- Test: `data_collection_pkg/test/test_capture_manager.py`
- Test: `data_collection_pkg/test/test_data_collection_web_dashboard.py`

**Interfaces:**
- Produces: `CaptureManager.clean(payload: Mapping) -> dict`.
- Produces: `POST /api/capture/clean` accepting `{"dataset_dir": "/.../original/teleop/qpos_gripper"}`.
- A running capture returns HTTP 409 and makes no filesystem changes.

- [ ] **Step 1: Write failing manager/API tests**

```python
def test_capture_manager_refuses_cleaning_while_capture_is_running(tmp_path):
    manager = CaptureManager(root=tmp_path, popen=lambda *_a, **_k: FakeProcess())
    manager.start({"runtime_mode": "teleop", "task": "pick"})
    assert manager.clean({"dataset_dir": str(tmp_path)})["ok"] is False


def test_dashboard_clean_endpoint_delegates_dataset_path():
    response = client.post("/api/capture/clean", json={"dataset_dir": "/tmp/original/teleop/qpos_gripper"})
    assert response.status_code == 200
    assert manager.clean_payload["dataset_dir"].endswith("qpos_gripper")
```

- [ ] **Step 2: Run API tests to verify the interface is absent**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_capture_manager.py test/test_data_collection_web_dashboard.py`

Expected: missing `CaptureManager.clean` and HTTP 404.

- [ ] **Step 3: Add manager delegation and endpoint**

```python
def clean(self, payload: Mapping) -> dict:
    if self._is_running():
        return {"ok": False, "error": "stop capture before cleaning"}
    dataset_dir = Path(str(payload.get("dataset_dir", ""))).expanduser()
    return clean_original_dataset(dataset_dir)
```

The endpoint returns 200 for `ok`, otherwise 409. It must only accept an existing valid `original/<mode>/qpos_gripper` directory through the cleaner validation.

- [ ] **Step 4: Run API tests to verify they pass**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_capture_manager.py test/test_data_collection_web_dashboard.py`

Expected: tests pass and a running collector cannot trigger cleaning.

### Task 4: Add Confirmed Qt Cleaning Action

**Files:**
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- Produces: `clean_dataset_button_` next to `capture_toggle_button_`.
- Consumes: `/api/capture/clean` with the displayed Capture `Dataset Path`.
- Produces: a confirmation dialog before sending the request, progress text while running, and an `Open Report` action after success.

- [ ] **Step 1: Write failing panel contract assertions**

```python
assert "clean_dataset_button_" in main_window
assert "Clean Data" in main_window
assert 'QStringLiteral("/api/capture/clean")' in main_window
assert "Cleaning will read original data" in main_window
assert "Open Report" in main_window
```

- [ ] **Step 2: Run contract test to verify it fails**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py`

Expected: assertions fail because no cleaning control exists.

- [ ] **Step 3: Add clean button behavior**

```cpp
connect(clean_dataset_button_, &QPushButton::clicked, this, [this]() {
  if (capture_running_ || capture_dataset_path_.isEmpty()) { return; }
  const auto answer = QMessageBox::question(
    this, QStringLiteral("Confirm Data Cleaning"),
    QStringLiteral("Cleaning will read original data at:\n%1\n\nand replace its sibling cleaned dataset. Original files are unchanged.")
      .arg(capture_dataset_path_),
    QMessageBox::Yes | QMessageBox::Cancel, QMessageBox::Cancel);
  if (answer == QMessageBox::Yes) { request_dataset_cleaning(); }
});
```

`request_dataset_cleaning()` disables the button, posts the dataset path, parses the response, updates the write-status label with accepted/rejected/review counts, and offers `QDesktopServices::openUrl(QUrl::fromLocalFile(report_path))`. State refresh must disable the button while a capture runs.

- [ ] **Step 4: Run panel contract test and compile**

Run: `PYTHONPATH=/home/crz/src/data_collection_pkg python3 -m pytest -q /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py && source /opt/ros/humble/setup.bash && colcon build --packages-select data_collection_rviz_panel data_collection_pkg`

Expected: contract passes and both packages compile.

### Task 5: Verify End-to-End Cleaning

**Files:**
- Modify: `data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md`

- [ ] **Step 1: Add manual verification procedure**

Document selecting a stopped original capture, confirming cleaning, opening the report, checking each rejected episode has reasons, and replaying an accepted episode from `cleaned`.

- [ ] **Step 2: Run focused and full tests**

Run: `cd /home/crz/src/data_collection_pkg && source /opt/ros/humble/setup.bash && PYTHONPATH=. python3 -m pytest -q test /home/crz/src/data_collection_rviz_panel/test && cd /home/crz/src && colcon test --packages-select data_collection_pkg data_collection_rviz_panel && colcon test-result --verbose`

Expected: all tests pass with no test errors or failures.
