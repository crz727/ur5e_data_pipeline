# Cleaned LeRobot Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export only cleaned qpos-gripper episodes to an arbitrary official LeRobot dataset directory, and offer that export immediately after successful cleaning without removing the CLI workflow.

**Architecture:** The converter validates that its JSONL input is below `cleaned/<mode>/qpos_gripper`, maps source cameras to configurable LeRobot feature names, and delegates Parquet, image frames, tasks, episodes, info, and statistics to the pinned official `LeRobotDataset` API. A small post-export verifier produces a JSON report and fails the conversion when expected official artifacts or dataset metadata are absent. The dashboard returns conversion results and Qt makes it an optional post-cleaning action.

**Tech Stack:** Python 3.10, LeRobot 0.4.4, Pillow, NumPy, Flask, Qt5/C++, ROS 2 Humble, pytest, colcon.

## Global Constraints

- Only a `cleaned/<runtime_mode>/qpos_gripper` directory is a conversion input; reject `original` and empty cleaned datasets.
- `--output-dir` controls the actual output path; `--repo-id` is independent and optional.
- Preserve source camera names by default; permit explicit `target=source` mappings such as `pano=external`.
- The implementation must not hard-code output directory names, chunk numbers, or media filenames.
- The official LeRobot library, not project code, writes Parquet, image frames, `meta/info.json`, statistics, tasks, and episode offsets.
- Qt export is optional after cleaning and unavailable when no episode was accepted.

---

### Task 1: Require Cleaned Input and Produce Official-Path Output

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/dataset/converter.py`
- Modify: `data_collection_pkg/data_collection_pkg/dataset/lerobot_writer.py`
- Test: `data_collection_pkg/test/test_data_collection_converter.py`

**Interfaces:**
- `convert_jsonl_to_lerobot(dataset_dir, *, output_dir, repo_id=None, fps=10.0, robot_type="ur5e", cameras=()) -> dict`.
- `cameras` is a tuple of `(target_name, source_name)` pairs.
- `output_dir` is passed directly as the root argument to `LeRobotDataset.create`.

- [ ] **Step 1: Write failing converter tests**

```python
def test_converter_rejects_original_and_accepts_cleaned_input(tmp_path):
    original = make_qpos_dataset(tmp_path / "original")
    with pytest.raises(ValueError, match="cleaned"):
        convert_jsonl_to_lerobot(original, output_dir=tmp_path / "out")


def test_converter_uses_exact_output_dir_and_camera_mapping(tmp_path):
    cleaned = make_cleaned_qpos_dataset(tmp_path)
    convert_jsonl_to_lerobot(
        cleaned, output_dir=tmp_path / "arbitrary-name", repo_id="lab/any-id",
        cameras=(("pano", "external"), ("wrist", "wrist")), dataset_cls=FakeLeRobotDataset)
    assert FakeLeRobotDataset.created["root"] == tmp_path / "arbitrary-name"
    assert "observation.images.pano" in FakeLeRobotDataset.created["features"]
```

- [ ] **Step 2: Run tests and verify the old interface fails**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_converter.py`

Expected: old converter accepts original data and nests the output below an internal schema path.

- [ ] **Step 3: Implement cleaned validation, direct output, and mapping**

```python
def _validate_cleaned_qpos_dataset(dataset_dir: Path) -> None:
    if dataset_dir.name != "qpos_gripper" or dataset_dir.parent.parent.name != "cleaned":
        raise ValueError("LeRobot conversion requires cleaned/<mode>/qpos_gripper")

writer = LeRobotDatasetWriter(
    output_dir, "qpos_gripper", task=task, repo_id=repo_id or f"local/{output_dir.name}",
    cameras=camera_mapping, image_shape=inferred_shape)
```

Decode compressed JPEG dimensions with Pillow before declaring image feature shapes. Reject an episode missing a mapped camera or a decoded image with a different shape.

- [ ] **Step 4: Run focused tests**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_converter.py test/test_data_collection_lerobot_writer.py`

Expected: converter uses direct output roots and preserves image feature mappings.

### Task 2: Add Export Verification and CLI

**Files:**
- Create: `data_collection_pkg/data_collection_pkg/dataset/lerobot_verify.py`
- Modify: `data_collection_pkg/data_collection_pkg/cli.py`
- Modify: `data_collection_pkg/test/test_data_collection_cli.py`
- Create: `data_collection_pkg/test/test_data_collection_lerobot_verify.py`

**Interfaces:**
- `verify_lerobot_export(output_dir: Path, expected_episode_count: int, expected_cameras: Sequence[str]) -> dict`.
- CLI: `convert-jsonl-to-lerobot CLEANED_DIR --output-dir DIR [--repo-id ID] [--camera TARGET=SOURCE]`.
- Conversion result includes `verification_report_path`.

- [ ] **Step 1: Write failing verifier and CLI tests**

```python
def test_export_verifier_reports_missing_stats_and_image_tree(tmp_path):
    result = verify_lerobot_export(tmp_path, expected_episode_count=1, expected_cameras=("pano",))
    assert result["ok"] is False
    assert "missing_meta_stats" in result["issues"]


def test_cli_requires_output_dir_for_cleaned_conversion(tmp_path):
    with pytest.raises(SystemExit):
        main(["convert-jsonl-to-lerobot", str(tmp_path / "cleaned" / "teleop" / "qpos_gripper")])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_lerobot_verify.py test/test_data_collection_cli.py`

Expected: missing module and obsolete CLI parsing.

- [ ] **Step 3: Implement verifier and CLI**

The verifier checks `meta/info.json`, `meta/stats.json`, either supported tasks metadata file, a nonempty `meta/episodes` tree, a nonempty `data` Parquet tree, and one nonempty image tree per mapped target camera. It writes `meta/data_collection_export_report.json` without altering official data files.

- [ ] **Step 4: Run focused tests**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_data_collection_lerobot_verify.py test/test_data_collection_cli.py`

Expected: verifier lists missing artifacts and successful conversions include a report path.

### Task 3: Offer Optional Export After Cleaning

**Files:**
- Modify: `data_collection_pkg/data_collection_pkg/visualization/capture_manager.py`
- Modify: `data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py`
- Modify: `data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp`
- Modify: `data_collection_rviz_panel/src/main_window.cpp`
- Modify: `data_collection_pkg/test/test_capture_manager.py`
- Modify: `data_collection_pkg/test/test_data_collection_web_dashboard.py`
- Modify: `data_collection_rviz_panel/test/test_panel_contract.py`

**Interfaces:**
- `POST /api/capture/export-lerobot` accepts `cleaned_dataset_dir`, `output_dir`, `repo_id`, `fps`, and camera mapping.
- `CaptureManager.export_lerobot(payload)` rejects running capture and non-cleaned input.
- Qt cleaning completion dialog shows `Export LeRobot` only when `accepted_episode_indices` is nonempty.

- [ ] **Step 1: Write failing API and Qt contract tests**

```python
response = client.post("/api/capture/export-lerobot", json={"cleaned_dataset_dir": "/tmp/cleaned/teleop/qpos_gripper", "output_dir": "/tmp/out"})
assert response.status_code == 200
assert "Export LeRobot" in main_window
assert 'QStringLiteral("/api/capture/export-lerobot")' in main_window
```

- [ ] **Step 2: Run tests to verify routes and controls are absent**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_capture_manager.py test/test_data_collection_web_dashboard.py /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py`

Expected: missing manager method, 404 endpoint, and panel assertions.

- [ ] **Step 3: Implement backend and optional Qt dialog**

The result dialog must offer only `Open Report` and `Close` when accepted count is zero. Otherwise it adds `Export LeRobot`; selecting it opens an output-directory chooser and a small configuration dialog, submits the backend request, then exposes the exported verification report.

- [ ] **Step 4: Run API and panel tests**

Run: `cd /home/crz/src/data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test/test_capture_manager.py test/test_data_collection_web_dashboard.py /home/crz/src/data_collection_rviz_panel/test/test_panel_contract.py`

Expected: cleaning remains optional and UI/API exports only cleaned data.

### Task 4: Verify With Official LeRobot 0.4.4

**Files:**
- Modify: `data_collection_pkg/README.md`
- Modify: `data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md`

- [ ] **Step 1: Install and verify pinned optional dependency**

Run: `cd /home/crz/src/data_collection_pkg && python3 -m pip install -r requirements-lerobot.txt && python3 -c 'import lerobot; print(lerobot.__version__)'`

Expected: installed version is `0.4.4`.

- [ ] **Step 2: Export a temporary cleaned fixture and inspect it with the verifier**

Run: `PYTHONPATH=. python3 -m pytest -q test/test_data_collection_lerobot_integration.py`

Expected: an official `LeRobotDataset` creates info, stats, tasks, episode, data, and per-camera image artifacts; verifier returns `ok: true`.

- [ ] **Step 3: Build and run full regression suite**

Run: `cd /home/crz/src && source /opt/ros/humble/setup.bash && colcon build --packages-select data_collection_pkg data_collection_rviz_panel && cd data_collection_pkg && PYTHONPATH=. python3 -m pytest -q test /home/crz/src/data_collection_rviz_panel/test && cd /home/crz/src && colcon test --packages-select data_collection_pkg data_collection_rviz_panel && colcon test-result --verbose`

Expected: all tests pass with zero errors and zero failures.
