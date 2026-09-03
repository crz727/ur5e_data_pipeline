# ACT / VLA LeRobot v3 Export Design

## Goal

Extend the existing UR5e data pipeline so that one cleaned source dataset can
be exported as either an ACT-oriented or VLA-oriented LeRobot v3 dataset. The
existing Capture Task field retains its current batch/folder-management role.
VLA language labels are captured separately at episode scope.

## Scope

Changes are limited to the data pipeline package and the Qt data-collection
panel. No change is made to the recorded action semantics: action remains the
next 15 Hz sample of absolute UR5e joint qpos plus gripper state.

## Capture annotation model

The Qt Capture panel keeps its existing Task text field and New Task workflow.
Task remains the human batch label and filesystem grouping name, such as
`pick_place_batch_0807`.

A `Language Instruction` button is placed beside Task. Its modal dialog has:

- an English instruction field;
- a Chinese instruction field;
- an automatically proposed, editable task ID;
- a selector for reusing a previously registered task ID; and
- Save and Cancel buttons.

At capture start, Task, task ID, English instruction, Chinese instruction and
the annotation source are snapshotted onto every created episode. Changes made
to the dialog later apply only to subsequent episodes.

Episode metadata contains at least:

```json
{
  "episode_index": 42,
  "task_name": "pick_place_batch_0807",
  "task_id": "pick_red_block_to_blue_tray",
  "language_instruction_en": "Pick up the red block and place it in the blue tray.",
  "language_instruction_zh": "抓取红色方块并放入蓝色托盘。",
  "annotation_source": "capture_ui",
  "action_semantics": "future_absolute_joint_state"
}
```

`task_id` is a stable machine-oriented semantic grouping key. New tasks
receive an editable slug proposed from the English instruction; equivalent
tasks should select an existing task ID. It is independent of the pre-existing
Task/batch name.

Metadata is stored with the episode records and copied intact from original to
cleaned during cleaning. It is not only stored in session-level metadata,
because one session can contain multiple tasks.

## Export profiles

Both buttons invoke one LeRobot v3 converter core, sharing frame hydration,
camera MP4 creation, Parquet records, feature validation and UR5e action
schema. They write explicitly selected output directories and never overwrite
one another by default.

### ACT profile

The ACT profile emits images, `observation.state`, `action`, timestamps and
standard episode identifiers. It does not expose natural-language instructions
to the ACT training input. If the official LeRobot v3 writer requires a task
index, it receives the stable non-language `task_id`; ACT training ignores
that standard metadata field.

### VLA profile

The VLA profile emits the same physical data and maps the English instruction
to LeRobot's episode task, generating the normal `task_index` and task
mapping. Chinese instruction is retained in an auditable sidecar file,
`meta/episode_language_annotations.jsonl`, indexed by exported episode.

VLA export accepts an episode only when its English instruction is present and
valid. Episodes with no English instruction, only Chinese instruction, blank
text, or non-semantic placeholder text are skipped. The export report records
each skipped episode and one of:

- `missing_english_instruction`
- `invalid_english_instruction`
- an existing data-integrity conversion error.

Historical cleaned episodes are never assigned fabricated language text.

## ImageNet image normalization metadata

ImageNet normalization is an image pre-processing contract, not the actual
dataset distribution. Both export profiles write
`meta/image_normalization.json`:

```json
{
  "input": "uint8_rgb",
  "conversion": "float32_rgb_0_to_1",
  "normalization": "imagenet_rgb",
  "mean": [0.485, 0.456, 0.406],
  "std": [0.229, 0.224, 0.225],
  "applies_to": [
    "observation.images.top",
    "observation.images.wrist"
  ]
}
```

The ACT or VLA training adapter performs this transform only when its model
configuration selects ImageNet normalization:

```text
image_float = image_uint8 / 255.0
image_normalized = (image_float - mean) / std
```

The exporter must preserve the official LeRobot-generated numeric
state/action dataset statistics. It must not overwrite observed image values in
`meta/stats.json` with ImageNet constants and label them as measured data.
The dedicated normalization sidecar avoids this ambiguity. Its presence is
mandatory in both outputs; consuming it remains a model/training-config
choice.

## Qt cleaning result workflow

After successful cleaning, the non-auto-closing result dialog presents:

- Open cleaning report;
- Export ACT;
- Export VLA;
- Close.

Export VLA additionally presents a final preflight summary: eligible count,
skipped count and skipped-language report location before conversion starts.
ACT export has no language eligibility gate.

## Verification

Automated tests cover:

- task name remains the capture batch name;
- language/task-ID snapshot belongs to the created episode;
- cleaning preserves annotations;
- ACT export accepts cleaned episodes without language;
- VLA export accepts only valid English-instruction episodes and reports every
  skipped one;
- both exports retain UR5e 7-D state/action, 15 Hz, top/wrist video mapping,
  and canonical joint order;
- ImageNet sidecar contains RGB mean and standard deviation values exactly as
  specified;
- official LeRobot export verification still succeeds for each profile.

An integration fixture includes three cleaned episodes: one valid bilingual
episode, one missing-English episode, and one ordinary ACT-only episode.

## Non-goals

- Replacing the existing Task input or changing task-root directory behavior.
- Recording a separate raw video stream during collection.
- Changing absolute joint qpos action semantics into delta control.
- Training a Chinese-language model in this change. Chinese labels are
  preserved for later profile selection.
