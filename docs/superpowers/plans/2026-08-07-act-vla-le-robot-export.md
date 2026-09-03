# ACT / VLA LeRobot v3 Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Capture bilingual labels per episode and export one cleaned UR5e source dataset as an ACT or VLA LeRobot v3 dataset with ImageNet RGB normalization metadata.

**Architecture:** The existing Capture Task remains the batch and directory name. Episode annotation helpers validate and snapshot task ID plus English and Chinese instructions into episode headers; cleaning retains those headers. One profile-aware converter and an episode-aware LeRobot writer produce ACT and VLA outputs, while the Qt panel selects the profile and displays VLA preflight results.

**Tech Stack:** ROS 2 Humble, Python 3, Flask, JSONL, NumPy, official lerobot LeRobotDataset, Qt 5/C++, pytest, colcon.

## Global Constraints

- Limit code changes to data_collection_pkg and data_collection_rviz_panel.
- Preserve Task as the batch and folder name; never derive filesystem paths from language.
- Keep canonical UR5e state/action as six joint radians plus gripper, at 15 Hz.
- Action remains next-sampled absolute qpos plus gripper state; do not introduce delta control.
- Map external to observation.images.top and wrist to observation.images.wrist.
- Both profiles write LeRobot v3 MP4 video and Parquet with the official API.
- VLA skips and reports every episode with no valid English instruction. It never invents text from Task.
- ImageNet RGB mean is [0.485, 0.456, 0.406] and standard deviation is [0.229, 0.224, 0.225], applied after uint8 RGB is divided by 255.0.
- Preserve measured LeRobot statistics; save ImageNet constants separately rather than rewriting meta/stats.json.

---

## File Structure

- Create: data_collection_pkg/data_collection_pkg/dataset/task_annotations.py
  - Annotation parsing, task-ID normalization, task catalog operations, and VLA English validation.
- Modify: data_collection_pkg/data_collection_pkg/dataset/jsonl_writer.py
  - Stores immutable per-episode annotation fields in meta/episodes.jsonl.
- Modify: data_collection_pkg/data_collection_pkg/ros_capture/qpos_demo_collector.py
  - Forwards annotation to the JSONL writer.
- Modify: data_collection_pkg/data_collection_pkg/ros_capture/collector_node.py
  - Declares and forwards task ID and language ROS parameters.
- Modify: data_collection_pkg/data_collection_pkg/visualization/capture_manager.py
  - Registers task labels, adds label list and preflight methods, forwards language launch values, and passes profile to export.
- Modify: data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py
  - Adds label list and VLA preflight routes.
- Modify: data_collection_pkg/data_collection_pkg/dataset/converter.py
  - Implements profile selection, VLA skips and reports, per-episode task selection, and ImageNet metadata.
- Modify: data_collection_pkg/data_collection_pkg/dataset/lerobot_writer.py
  - Makes LeRobot task active-episode scoped rather than dataset scoped.
- Modify: data_collection_pkg/data_collection_pkg/dataset/lerobot_verify.py
  - Verifies profile metadata and ImageNet sidecar values.
- Modify: data_collection_pkg/data_collection_pkg/cli.py
  - Adds conversion profile option.
- Modify: data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp
  - Adds language editor, profile export, and stored annotation declarations.
- Modify: data_collection_rviz_panel/src/main_window.cpp
  - Adds language dialog, ACT/VLA result actions, VLA preflight, and profile export payloads.
- Modify tests: data_collection_pkg/test/test_data_collection_writer.py, test_qpos_demo_collector.py, test_data_collection_ros_nodes.py, test_capture_manager.py, test_data_collection_cleaner.py, test_data_collection_converter.py, test_data_collection_lerobot_writer.py, test_data_collection_lerobot_verify.py, test_data_collection_cli.py, test_data_collection_web_dashboard.py, and data_collection_rviz_panel/test/test_panel_contract.py.
- Modify: data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md

### Task 1: Define and Persist Episode Task Annotations

**Files:**

- Create: data_collection_pkg/data_collection_pkg/dataset/task_annotations.py
- Modify: data_collection_pkg/data_collection_pkg/dataset/jsonl_writer.py:22-112
- Modify: data_collection_pkg/data_collection_pkg/ros_capture/qpos_demo_collector.py:158-210
- Modify: data_collection_pkg/data_collection_pkg/ros_capture/collector_node.py:293-345, 508-545, 691-720
- Test: data_collection_pkg/test/test_data_collection_writer.py
- Test: data_collection_pkg/test/test_qpos_demo_collector.py
- Test: data_collection_pkg/test/test_data_collection_ros_nodes.py

**Interfaces:**

- Produces CaptureTaskAnnotation fields task_id, language_instruction_en, language_instruction_zh, and annotation_source.
- Produces parse_capture_task_annotation(task_name, task_id, english, chinese) returning a dict.
- JsonlDatasetWriter accepts episode_metadata: Mapping[str, Any] | None.
- QposDemoJsonlRecorder accepts and forwards episode_metadata.

- [ ] **Step 1: Write failing writer, recorder, and node tests**

  Construct JsonlDatasetWriter with:

  ~~~python
  annotation = {
      "task_name": "pick_place_batch_0807",
      "task_id": "pick_red_block_to_blue_tray",
      "language_instruction_en": "Pick up the red block and place it in the blue tray.",
      "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
      "annotation_source": "capture_ui",
  }
  writer = JsonlDatasetWriter(
      tmp_path, "qpos_gripper", task="pick_place_batch_0807",
      source="teleop", episode_metadata=annotation,
  )
  ~~~

  Assert the completed episode row contains its unchanged legacy task, task_name,
  task_id, two instructions, and source. Mutate annotation after writer
  construction and assert that written metadata does not change. Add recorder
  and node-adapter cases proving the values reach meta/episodes.jsonl.

- [ ] **Step 2: Run tests to verify failure**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_data_collection_writer.py data_collection_pkg/test/test_qpos_demo_collector.py data_collection_pkg/test/test_data_collection_ros_nodes.py
  ~~~

  Expected: tests fail because episode_metadata and annotation helpers do not exist.

- [ ] **Step 3: Implement the contract and propagation**

  In task_annotations.py implement:

  ~~~python
  def normalize_task_id(value: object) -> str: ...
  def suggest_task_id(english_instruction: str) -> str: ...
  def parse_capture_task_annotation(
      *, task_name: str, task_id: object, english: object, chinese: object
  ) -> dict: ...
  ~~~

  Normalize task IDs to lower-case ASCII letters, digits, and hyphens; reject
  invalid supplied IDs with ValueError. Collapse instruction whitespace. Empty
  language fields remain valid for ACT capture. Set task_name from the existing
  Task and annotation_source to capture_ui whenever an annotation is supplied.

  Add episode_metadata to JsonlDatasetWriter, defensive-copy it in the
  constructor, and merge it into the completed episode record after standard
  schema fields. Keep legacy task equal to self.task. Do not repeat language
  text inside every frame.

  Add the optional mapping to QposDemoJsonlRecorder and pass it through.
  Declare task_id, language_instruction_en, and language_instruction_zh in the
  collector node. Read them in teleop_collector_config_from_parameters, create
  one annotation in collector_node_main, and forward it through
  FixedRateQposDemoNodeAdapter to QposDemoJsonlRecorder.

- [ ] **Step 4: Run focused tests to verify pass**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_data_collection_writer.py data_collection_pkg/test/test_qpos_demo_collector.py data_collection_pkg/test/test_data_collection_ros_nodes.py
  ~~~

  Expected: all selected tests pass.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_pkg/data_collection_pkg/dataset/task_annotations.py data_collection_pkg/data_collection_pkg/dataset/jsonl_writer.py data_collection_pkg/data_collection_pkg/ros_capture/qpos_demo_collector.py data_collection_pkg/data_collection_pkg/ros_capture/collector_node.py data_collection_pkg/test/test_data_collection_writer.py data_collection_pkg/test/test_qpos_demo_collector.py data_collection_pkg/test/test_data_collection_ros_nodes.py
  git commit -m "feat: persist episode language annotations"
  ~~~

### Task 2: Register Labels, Launch with Them, and Preserve Them in Cleaned Data

**Files:**

- Modify: data_collection_pkg/data_collection_pkg/dataset/task_annotations.py
- Modify: data_collection_pkg/data_collection_pkg/visualization/capture_manager.py:36-134, 312-353
- Test: data_collection_pkg/test/test_capture_manager.py
- Test: data_collection_pkg/test/test_data_collection_cleaner.py

**Interfaces:**

- CaptureManager.task_labels() returns a dict with most-recent-first labels.
- Append catalog events to <CaptureManager.root>/_task_catalog.jsonl.

- [ ] **Step 1: Write failing manager and cleaner tests**

  Start CaptureManager with Task pick_place_batch_0807, task ID
  pick_red_block_to_blue_tray, and both instructions. Assert the launch list
  includes task:=pick_place_batch_0807 and the three new launch arguments.
  Assert task_labels returns the stored label.

  Add annotation fields to an accepted cleaner fixture and assert
  cleaned/meta/episodes.jsonl retains all of them unchanged. This protects the
  existing cleaner behavior of copying the complete episode header.

- [ ] **Step 2: Run tests to verify failure**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_cleaner.py
  ~~~

  Expected: catalog and launch argument assertions fail.

- [ ] **Step 3: Implement catalog registration and launch arguments**

  Add helpers:

  ~~~python
  def load_task_catalog(path: Path) -> list[dict]: ...
  def register_task_label(path: Path, annotation: Mapping[str, object], now: float) -> dict: ...
  def validate_vla_english_instruction(value: object) -> str | None: ...
  ~~~

  The catalog returns the latest valid row per task ID, ordered by last use.
  It rejects reuse of a task ID with conflicting non-empty English or Chinese
  text. English validation returns missing_english_instruction for blank text
  or text without an ASCII alphabetic character. It returns
  invalid_english_instruction for test, task, demo, unknown, none, n/a, and
  numbered variants such as test_01 or episode-003.

  In CaptureManager.start parse annotation before subprocess startup, register
  non-empty task IDs, retain the current annotation, and add:

  ~~~python
  f"task_id:={annotation['task_id']}"
  f"language_instruction_en:={annotation['language_instruction_en']}"
  f"language_instruction_zh:={annotation['language_instruction_zh']}"
  ~~~

  to _command. Existing no-language ACT capture remains accepted.

  Add task_labels to CaptureManager. The HTTP routes are deliberately added
  after the converter preflight exists in Task 4.

- [ ] **Step 4: Run focused tests to verify pass**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_cleaner.py
  ~~~

  Expected: all selected tests pass.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_pkg/data_collection_pkg/dataset/task_annotations.py data_collection_pkg/data_collection_pkg/visualization/capture_manager.py data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_cleaner.py
  git commit -m "feat: register capture task language labels"
  ~~~

### Task 3: Add Profile-Aware LeRobot v3 Conversion and ImageNet Metadata

**Files:**

- Modify: data_collection_pkg/data_collection_pkg/dataset/converter.py:13-96
- Modify: data_collection_pkg/data_collection_pkg/dataset/lerobot_writer.py:14-108
- Modify: data_collection_pkg/data_collection_pkg/dataset/lerobot_verify.py:10-66
- Modify: data_collection_pkg/data_collection_pkg/cli.py:62-76, 154-167
- Test: data_collection_pkg/test/test_data_collection_converter.py
- Test: data_collection_pkg/test/test_data_collection_lerobot_writer.py
- Test: data_collection_pkg/test/test_data_collection_lerobot_verify.py
- Test: data_collection_pkg/test/test_data_collection_cli.py

**Interfaces:**

- convert_jsonl_to_lerobot(..., profile: str = "act") returns a summary.
- preflight_jsonl_to_lerobot(dataset_dir: Path, profile: str) returns eligible and skipped episode records without writing a dataset.
- LeRobotDatasetWriter.start_episode(*, task: str) starts one task-labeled output episode.
- write_image_normalization_metadata(output_dir, camera_names) returns the created sidecar path.

- [ ] **Step 1: Write failing ACT, VLA, report, and normalization tests**

  Extend converter fixtures to have three cleaned episodes: one with a valid
  English/Chinese label, one Chinese-only episode, and one ACT-only episode
  with task_id but no instructions.

  Assert ACT exports all three and writes task_id for each fake LeRobot frame.
  Assert VLA exports only the bilingual episode and uses its English
  instruction as task. Assert VLA output includes:

  ~~~text
  meta/vla_export_report.json
  meta/episode_language_annotations.jsonl
  meta/image_normalization.json
  ~~~

  Assert Chinese-only and ACT-only indices appear as
  missing_english_instruction. Check the sidecar exact mean, standard
  deviation, input conversion, and top/wrist feature names. Add a writer test
  with two episodes whose task values differ.

- [ ] **Step 2: Run tests to verify failure**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_data_collection_converter.py data_collection_pkg/test/test_data_collection_lerobot_writer.py data_collection_pkg/test/test_data_collection_lerobot_verify.py data_collection_pkg/test/test_data_collection_cli.py
  ~~~

  Expected: tests fail because conversion uses the first episode task globally.

- [ ] **Step 3: Implement writer tasks, profiles, reports, and sidecar**

  Change the writer interface:

  ~~~python
  def start_episode(self, *, task: str) -> Episode:
      self._episode_task = str(task).strip()
      if not self._episode_task:
          raise ValueError("LeRobot episode task must be non-empty")
      ...
  ~~~

  add_frame writes self._episode_task and close_episode clears it. Update all
  writer call sites and tests.

  In converter.py accept act and vla profiles. Preflight validates a single
  qpos schema and selects tasks as:

  ~~~python
  if profile == "act":
      task = row.get("task_id") or row.get("task") or f"episode-{row['episode_index']}"
  else:
      reason = validate_vla_english_instruction(row.get("language_instruction_en"))
      if reason is not None:
          skipped.append({"episode_index": row["episode_index"], "reason": reason})
      else:
          task = normalized_english_instruction
  ~~~

  Default no-camera calls to top=external and wrist=wrist, while respecting
  explicit mappings. Convert only eligible episodes.

  After writer.finalize, write meta/image_normalization.json exactly with
  input uint8_rgb, conversion float32_rgb_0_to_1, normalization
  imagenet_rgb, specified RGB vectors, and present output image keys.

  For VLA write meta/vla_export_report.json with source, profile, eligible
  source indices, source-to-output episode mapping, skipped items, and export
  timestamp. Write meta/episode_language_annotations.jsonl with output and
  source indices, task_id, English, and Chinese. When no VLA episode is
  eligible, write the report, then raise a clear error without creating an
  empty trainable dataset.

  Extend verify_lerobot_export with profile and
  require_image_normalization. Verify exact sidecar values and image keys; VLA
  verification additionally requires both VLA metadata files and validates
  exported count instead of total cleaned count.

  Add CLI option:

  ~~~bash
  data_collection convert-jsonl-to-lerobot CLEANED_DIR --profile vla --output-dir OUTPUT_DIR --camera top=external --camera wrist=wrist
  ~~~

  Profile defaults to act and JSON output includes profile and skipped count.

- [ ] **Step 4: Run focused tests to verify pass**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_data_collection_converter.py data_collection_pkg/test/test_data_collection_lerobot_writer.py data_collection_pkg/test/test_data_collection_lerobot_verify.py data_collection_pkg/test/test_data_collection_cli.py
  ~~~

  Expected: all selected tests pass and VLA fake frames contain no unlabeled episode.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_pkg/data_collection_pkg/dataset/converter.py data_collection_pkg/data_collection_pkg/dataset/lerobot_writer.py data_collection_pkg/data_collection_pkg/dataset/lerobot_verify.py data_collection_pkg/data_collection_pkg/cli.py data_collection_pkg/test/test_data_collection_converter.py data_collection_pkg/test/test_data_collection_lerobot_writer.py data_collection_pkg/test/test_data_collection_lerobot_verify.py data_collection_pkg/test/test_data_collection_cli.py
  git commit -m "feat: add ACT and VLA LeRobot export profiles"
  ~~~

### Task 4: Expose Capture Labels and Export Preflight through HTTP

**Files:**

- Modify: data_collection_pkg/data_collection_pkg/visualization/capture_manager.py:183-260
- Modify: data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py:320-360
- Test: data_collection_pkg/test/test_capture_manager.py
- Test: data_collection_pkg/test/test_data_collection_web_dashboard.py

**Interfaces:**

- CaptureManager.preflight_lerobot_export(payload) returns converter
  eligibility without starting a worker thread.
- GET /api/capture/task-labels returns the Task 2 catalog.
- POST /api/capture/export-lerobot/preflight returns profile eligibility.

- [ ] **Step 1: Write failing HTTP and manager preflight tests**

  Add a VLA preflight test with one valid English episode and one
  Chinese-only episode. Assert CaptureManager returns profile vla, eligible
  source index, skipped source index/reason, and planned output report path.
  Add Flask tests that GET task labels and POST VLA preflight.

- [ ] **Step 2: Run tests to verify failure**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_web_dashboard.py
  ~~~

  Expected: failure because neither preflight nor its routes exist.

- [ ] **Step 3: Implement read-only HTTP preflight**

  Implement CaptureManager.preflight_lerobot_export by checking capture is
  stopped, reading cleaned_dataset_dir, output_dir, and profile, then calling
  preflight_jsonl_to_lerobot. Include planned_report_path as
  output_dir/meta/vla_export_report.json for profile vla. Do not create an
  output directory, launch a thread, or write a dataset in this method.

  Add Flask GET /api/capture/task-labels and POST
  /api/capture/export-lerobot/preflight. Return normal JSON result bodies,
  HTTP 409 for invalid requests or disabled controls, and HTTP 200 for a
  successful read-only preflight.

- [ ] **Step 4: Run focused tests to verify pass**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_web_dashboard.py
  ~~~

  Expected: all selected tests pass.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_pkg/data_collection_pkg/visualization/capture_manager.py data_collection_pkg/data_collection_pkg/visualization/web_dashboard.py data_collection_pkg/test/test_capture_manager.py data_collection_pkg/test/test_data_collection_web_dashboard.py
  git commit -m "feat: add language label and export preflight APIs"
  ~~~

### Task 5: Add Qt Language Entry, Preflight, and Dual Export Controls

**Files:**

- Modify: data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp:30-138
- Modify: data_collection_rviz_panel/src/main_window.cpp:690-756, 1140-1300
- Test: data_collection_rviz_panel/test/test_panel_contract.py

**Interfaces:**

- request_language_instruction_editor()
- show_language_instruction_editor(const QJsonArray & labels)
- request_lerobot_export(cleaned_dataset_dir, profile)
- request_lerobot_export_preflight(cleaned_dataset_dir, profile, output_dir)
- Persistent fields capture_task_id_, capture_language_instruction_en_, capture_language_instruction_zh_.

- [ ] **Step 1: Write failing panel contract tests**

  Require source text for Language Instruction, English instruction, 中文指令,
  Export ACT, Export VLA, /api/capture/task-labels,
  /api/capture/export-lerobot/preflight, and profile. Require the old generic
  Export LeRobot label to be absent and preserve current non-modal,
  manually-closable cleaning-dialog assertions.

- [ ] **Step 2: Run test to verify failure**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_rviz_panel/test/test_panel_contract.py
  ~~~

  Expected: failure because the panel has one generic export button and no language editor.

- [ ] **Step 3: Implement dialog, capture payload, preflight, and exports**

  Add Language Instruction beside the existing Task field without changing Task
  or New Task behavior. Fetch task labels first; then display a modal dialog
  containing editable existing task-ID combo box, multiline English editor,
  multiline Chinese editor, Save, and Cancel. Selecting known ID fills both
  instructions. An empty ID plus English input receives a local kebab-case
  suggestion; backend validation remains authoritative. Save sets the three
  persistent fields and updates button text to Language: ready or Language:
  not set. Disable this control while capture is running.

  Extend the existing start JSON with task_id, language_instruction_en, and
  language_instruction_zh.

  Replace Export LeRobot in the existing non-closing cleaning result dialog
  with Export ACT and Export VLA. Keep Open Report and Close. Choose parent
  and output name per profile, with defaults lerobot_act_v3 and
  lerobot_vla_v3.

  ACT immediately starts asynchronous profile act export. VLA makes a
  preflight request after output selection, displays eligible count, skipped
  count, and planned meta/vla_export_report.json path, then starts profile vla
  only after confirmation. Reuse current status polling and label status text
  as ACT export or VLA export.

- [ ] **Step 4: Run contract test and build**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_rviz_panel/test/test_panel_contract.py
  colcon build --packages-select data_collection_rviz_panel
  ~~~

  Expected: contract test passes and panel builds.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_rviz_panel/include/data_collection_rviz_panel/main_window.hpp data_collection_rviz_panel/src/main_window.cpp data_collection_rviz_panel/test/test_panel_contract.py
  git commit -m "feat: add language labels and dual dataset exports"
  ~~~

### Task 6: Document and Verify the Real-Robot Workflow

**Files:**

- Modify: data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md
- Test: all test targets named in Tasks 1-5

**Interfaces:**

- Documents Task versus task ID, bilingual entry, cleaned-only export, VLA skip reports, and ImageNet transform.

- [ ] **Step 1: Add exact manual validation checklist**

  Document:

  ~~~text
  1. Create Task pick_place_batch_0807.
  2. Set task ID pick_red_block_to_blue_tray and bilingual instructions.
  3. Capture, stop, and inspect original/meta/episodes.jsonl.
  4. Mark success, clean, and inspect cleaned/meta/episodes.jsonl.
  5. Export ACT and inspect MP4, Parquet, and image_normalization.json.
  6. Export VLA and inspect task mapping, language sidecar, and VLA report.
  7. Remove English from a fixture episode; ACT accepts it and VLA skips it.
  ~~~

  Include RGB / 255.0 followed by ImageNet subtraction and division.

- [ ] **Step 2: Run all tests**

  Run:

  ~~~bash
  cd /home/crz/src
  pytest -q data_collection_pkg/test data_collection_rviz_panel/test
  ~~~

  Expected: all tests pass.

- [ ] **Step 3: Build changed packages**

  Run:

  ~~~bash
  cd /home/crz/src
  colcon build --packages-select data_collection_pkg data_collection_rviz_panel
  ~~~

  Expected: both packages build.

- [ ] **Step 4: Run local ACT and VLA conversion smoke tests**

  Run with an already-cleaned qpos dataset:

  ~~~bash
  cd /home/crz/src
  source install/setup.bash
  data_collection convert-jsonl-to-lerobot CLEANED_QPOS_DIR --profile act --output-dir /tmp/ur5e_act_v3 --camera top=external --camera wrist=wrist
  data_collection convert-jsonl-to-lerobot CLEANED_QPOS_DIR --profile vla --output-dir /tmp/ur5e_vla_v3 --camera top=external --camera wrist=wrist
  ~~~

  Verify ACT output contains image_normalization.json. Verify VLA output also
  contains vla_export_report.json and episode_language_annotations.jsonl, and
  compare report counts to source episode headers.

- [ ] **Step 5: Commit**

  ~~~bash
  cd /home/crz/src
  git add data_collection_pkg/docs/REAL_ROBOT_VALIDATION.md
  git commit -m "docs: document ACT and VLA export validation"
  ~~~

## Final Review Checklist

- [ ] Task still creates/selects task-root folders and stays independent from task ID.
- [ ] Episode headers, rather than only session files, contain frozen language snapshots.
- [ ] Cleaning retains accepted annotations and does not mutate original data.
- [ ] ACT accepts unlabeled cleaned episodes.
- [ ] VLA exports only valid-English episodes and records every skipped episode.
- [ ] VLA task is English; Chinese is retained in the sidecar.
- [ ] Both outputs retain 15 Hz, UR5e 7-D state/action, top/wrist MP4 mapping, and ImageNet metadata.
- [ ] ImageNet metadata does not overwrite observed LeRobot statistics.
- [ ] Cleaning dialog remains open until Close and exports run asynchronously.
