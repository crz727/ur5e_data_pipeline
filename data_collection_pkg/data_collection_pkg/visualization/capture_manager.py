"""Start and stop data-collection-only capture jobs for the dashboard."""

import os
import json
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

from data_collection_pkg.dataset.cleaner import CleaningConfig, clean_original_dataset
from data_collection_pkg.dataset.converter import (
    convert_jsonl_to_lerobot,
    preflight_jsonl_to_lerobot,
)
from data_collection_pkg.dataset.task_annotations import (
    load_task_catalog,
    parse_capture_task_annotation,
    register_task_label,
)


ALLOWED_RUNTIME_MODES = ("teleop", "http", "act", "vla")


class CaptureManager:
    """Manage one hardware qpos collector subprocess.

    This class intentionally starts only the data pipeline collector. It does
    not launch teleoperation, HTTP control, policy execution, or robot drivers.
    """

    def __init__(
        self,
        *,
        root,
        popen: Optional[Callable] = None,
        now: Optional[Callable[[], float]] = None,
        converter: Optional[Callable] = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.popen = popen or subprocess.Popen
        self.now = now or time.time
        self.converter = converter or convert_jsonl_to_lerobot
        self.process = None
        self.started_at = None
        self.command = None
        self.log_path = None
        self._log_stream = None
        self.current_task = None
        self.current_task_root = None
        self.current_task_annotation = {}
        self._episode_indices_before = set()
        self._pending_annotation_batches = []
        self._export_lock = threading.Lock()
        self._export_thread = None
        self._export_job_id = 0
        self._export_status = {"ok": True, "status": "idle", "job_id": None}

    def new_task(self, payload: Mapping) -> dict:
        """Create/select a new task batch folder under the capture base root."""
        if self._is_running():
            return {
                "ok": False,
                "running": True,
                "error": "stop the current capture before creating a new task",
                **self.status(),
            }

        task = _safe_task_name(payload.get("task") or "capture_task")
        task_root = self.root / f"{task}_{_timestamp_label(self.now())}"
        task_root.mkdir(parents=True, exist_ok=True)
        self.current_task = task
        self.current_task_root = task_root
        self.current_task_annotation = {}
        return {
            "ok": True,
            "running": False,
            "task": task,
            "task_root": str(task_root),
        }

    def start(self, payload: Mapping) -> dict:
        """Start a hardware qpos collector for one runtime mode."""
        if self._is_running():
            return {
                "ok": False,
                "running": True,
                "error": "capture already running",
                **self.status(),
            }

        runtime_mode = str(payload.get("runtime_mode", "teleop")).strip()
        if runtime_mode not in ALLOWED_RUNTIME_MODES:
            return {
                "ok": False,
                "running": False,
                "error": f"runtime_mode must be one of {', '.join(ALLOWED_RUNTIME_MODES)}",
            }

        if self.current_task_root is None:
            self.new_task({"task": payload.get("task") or f"{runtime_mode}_segment"})

        task = self.current_task or _safe_task_name(payload.get("task") or f"{runtime_mode}_segment")
        task_root = self.current_task_root or self.root
        try:
            annotation = parse_capture_task_annotation(
                task_name=task,
                task_id=payload.get("task_id", ""),
                english=payload.get("language_instruction_en", ""),
                chinese=payload.get("language_instruction_zh", ""),
            )
            if annotation.get("task_id"):
                register_task_label(self.root / "_task_catalog.jsonl", annotation, self.now())
        except ValueError as exc:
            return {"ok": False, "running": False, "error": str(exc)}
        self.current_task_annotation = annotation
        dataset_stage = str(payload.get("dataset_stage", "original")).strip() or "original"
        dataset_dir = task_root / dataset_stage / runtime_mode / "qpos_gripper"
        command = self._command(
            payload, runtime_mode, task, dataset_stage, task_root, annotation
        )
        task_root.mkdir(parents=True, exist_ok=True)
        self._episode_indices_before = _episode_indices(dataset_dir)
        log_dir = task_root / "_ui_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{task}_{int(self.now())}.log"
        self._log_stream = self.log_path.open("a", encoding="utf-8")
        self._log_stream.write(" ".join(command) + "\n")
        self._log_stream.flush()

        self.process = self.popen(
            command,
            stdout=self._log_stream,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            start_new_session=True,
        )
        self.started_at = self.now()
        self.command = command
        return {
            "ok": True,
            "running": True,
            "runtime_mode": runtime_mode,
            "dataset_stage": dataset_stage,
            "task": task,
            "task_root": str(task_root),
            "dataset_dir": str(dataset_dir),
            "log_path": str(self.log_path),
        }

    def task_labels(self) -> dict:
        """Return registered task-language labels in most-recent-first order."""
        return {
            "ok": True,
            "labels": load_task_catalog(self.root / "_task_catalog.jsonl"),
        }

    def stop(self) -> dict:
        """Stop the active collector process."""
        if not self._is_running():
            self._remember_stopped_episodes()
            self._close_log()
            return {"ok": True, "running": False, "message": "capture was not running"}

        self._terminate_process_tree()
        try:
            self.process.wait(timeout=8.0)
        except Exception:
            self._kill_process_tree()
            self.process.wait(timeout=3.0)
        status = self.status()
        self._remember_stopped_episodes(status)
        self._close_log()
        return {"ok": True, **status}

    def annotate(self, payload: Mapping) -> dict:
        """Append one human outcome annotation for each episode from the last run."""
        if not self._pending_annotation_batches:
            return {"ok": False, "error": "stop a completed capture before annotation"}
        outcome = str(payload.get("outcome", "")).strip().lower()
        if outcome not in {"success", "failure"}:
            return {"ok": False, "error": "outcome must be success or failure"}
        dataset_dir, pending_indices = self._pending_annotation_batches[0]
        episode_indices = list(pending_indices)
        annotation_path = dataset_dir / "meta" / "episode_annotations.jsonl"
        annotation_path.parent.mkdir(parents=True, exist_ok=True)
        with annotation_path.open("a", encoding="utf-8") as stream:
            for episode_index in episode_indices:
                stream.write(json.dumps({
                    "schema_version": 1,
                    "episode_index": episode_index,
                    "outcome": outcome,
                    "review_status": "reviewed",
                    "annotated_at": self.now(),
                    "source": "human",
                }, ensure_ascii=False) + "\n")
        del self._pending_annotation_batches[0]
        return {
            "ok": True,
            "outcome": outcome,
            "annotation_path": str(annotation_path),
            "dataset_dir": str(dataset_dir),
            "episode_indices": episode_indices,
        }

    def clean(self, payload: Mapping) -> dict:
        """Create a high-quality sibling dataset from a stopped original capture."""
        if self._is_running():
            return {"ok": False, "error": "stop capture before cleaning"}
        dataset_dir = Path(str(payload.get("dataset_dir", ""))).expanduser()
        try:
            return clean_original_dataset(dataset_dir, config=CleaningConfig(
                target_fps=float(payload.get("target_fps", 15.0)),
                max_sync_delta_s=float(payload.get("max_sync_delta_s", 0.02)),
                fps_tolerance_ratio=float(payload.get("fps_tolerance_ratio", 0.5)),
            ))
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def export_lerobot(self, payload: Mapping) -> dict:
        """Export an already-cleaned dataset without touching original capture data."""
        if self._is_running():
            return {"ok": False, "error": "stop capture before exporting LeRobot"}
        try:
            cleaned_value = str(payload.get("cleaned_dataset_dir", "")).strip()
            output_value = str(payload.get("output_dir", "")).strip()
            if not cleaned_value:
                raise ValueError("cleaned_dataset_dir is required")
            if not output_value:
                raise ValueError("output_dir is required")
            cleaned_dataset_dir = Path(cleaned_value).expanduser()
            output_dir = Path(output_value).expanduser()
            if output_dir.exists():
                raise ValueError(
                    f"output directory already exists: {output_dir}; choose a new path"
                )
            profile = str(payload.get("profile", "act")).strip().lower()
            if profile not in {"act", "vla"}:
                raise ValueError("profile must be act or vla")
            cameras = tuple(payload.get("cameras") or ("external", "wrist"))
            result = self.converter(
                cleaned_dataset_dir,
                output_dir=output_dir,
                repo_id=payload.get("repo_id") or None,
                fps=float(payload.get("fps", 15.0)),
                cameras=cameras,
                visual_storage=str(payload.get("visual_storage", "video")),
                video_codec=str(payload.get("video_codec", "h264")),
                profile=profile,
            )
            return {"ok": True, **result}
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def preflight_lerobot_export(self, payload: Mapping) -> dict:
        """Report LeRobot export eligibility without writing an output dataset."""
        if self._is_running():
            return {"ok": False, "error": "stop capture before exporting LeRobot"}
        if not isinstance(payload, Mapping):
            return {"ok": False, "error": "preflight payload must be a JSON object"}
        try:
            cleaned_value = payload.get("cleaned_dataset_dir", "")
            output_value = payload.get("output_dir", "")
            profile = payload.get("profile", "act")
            if not isinstance(cleaned_value, str) or not cleaned_value.strip():
                raise ValueError("cleaned_dataset_dir must be a non-empty string")
            if not isinstance(output_value, str) or not output_value.strip():
                raise ValueError("output_dir must be a non-empty string")
            if not isinstance(profile, str) or not profile.strip():
                raise ValueError("profile must be a non-empty string")
            cleaned_dataset_dir = Path(cleaned_value.strip()).expanduser()
            output_dir = Path(output_value.strip()).expanduser()
            if output_dir.exists():
                raise ValueError(
                    f"output directory already exists: {output_dir}; choose a new path"
                )
            result = preflight_jsonl_to_lerobot(cleaned_dataset_dir, profile.strip())
            if result["profile"] == "vla":
                result["planned_report_path"] = str(
                    output_dir / "meta" / "vla_export_report.json"
                )
            return {"ok": True, **result}
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def start_lerobot_export(self, payload: Mapping) -> dict:
        """Start an export without occupying the dashboard request thread."""
        if self._is_running():
            return {"ok": False, "error": "stop capture before exporting LeRobot"}
        with self._export_lock:
            if self._export_thread is not None and self._export_thread.is_alive():
                return {"ok": False, **dict(self._export_status), "error": "LeRobot export already running"}
            self._export_job_id += 1
            job_id = self._export_job_id
            self._export_status = {
                "ok": True,
                "status": "queued",
                "job_id": job_id,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self._export_thread = threading.Thread(
                target=self._run_lerobot_export,
                args=(job_id, dict(payload)),
                daemon=True,
            )
            self._export_thread.start()
            return dict(self._export_status)

    def lerobot_export_status(self) -> dict:
        """Return the latest asynchronous export status."""
        with self._export_lock:
            return dict(self._export_status)

    def _run_lerobot_export(self, job_id: int, payload: Mapping) -> None:
        with self._export_lock:
            if self._export_status.get("job_id") != job_id:
                return
            self._export_status.update({"status": "running", "started_at": self.now()})
        result = self.export_lerobot(payload)
        with self._export_lock:
            if self._export_status.get("job_id") != job_id:
                return
            if result.get("ok"):
                self._export_status.update({
                    "ok": True,
                    "status": "done",
                    "result": result,
                    "error": None,
                    "finished_at": self.now(),
                })
            else:
                self._export_status.update({
                    "ok": False,
                    "status": "failed",
                    "result": None,
                    "error": result.get("error", "LeRobot export failed"),
                    "finished_at": self.now(),
                })

    def status(self) -> dict:
        """Return current capture state."""
        running = self._is_running()
        age_s = None if self.started_at is None else max(0.0, self.now() - self.started_at)
        dataset_dir = None
        runtime_mode = None
        dataset_stage = None
        task = None
        task_root = self.current_task_root
        if self.command:
            values = _launch_arg_values(self.command)
            runtime_mode = values.get("runtime_mode")
            dataset_stage = values.get("dataset_stage")
            task = values.get("task")
            if values.get("root"):
                task_root = Path(values["root"])
            if runtime_mode and dataset_stage:
                dataset_dir = str(task_root / dataset_stage / runtime_mode / "qpos_gripper")
        return {
            "running": running,
            "age_s": age_s,
            "runtime_mode": runtime_mode,
            "dataset_stage": dataset_stage,
            "task": task,
            "base_root": str(self.root),
            "task_root": None if task_root is None else str(task_root),
            "dataset_dir": dataset_dir,
            "log_path": None if self.log_path is None else str(self.log_path),
            "returncode": None if self.process is None else self.process.poll(),
        }

    def _command(
        self,
        payload: Mapping,
        runtime_mode: str,
        task: str,
        dataset_stage: str,
        task_root: Path,
        annotation: Mapping[str, object],
    ) -> list:
        annotation_args = []
        for name in (
            "task_id",
            "language_instruction_en",
            "language_instruction_zh",
        ):
            value = str(annotation.get(name, "")).strip()
            if value:
                annotation_args.append(f"{name}:={value}")
        command = [
            "ros2",
            "launch",
            "data_collection_pkg",
            "data_collection_hardware_qpos.launch.py",
            f"root:={task_root}",
            f"task:={task}",
            *annotation_args,
            f"dataset_stage:={dataset_stage}",
            f"runtime_mode:={runtime_mode}",
            f"sample_rate_hz:={_ros_double(payload.get('sample_rate_hz', 15.0))}",
            f"sampling_clock:={payload.get('sampling_clock', 'scene_camera_header')}",
            f"gripper_state_topic:={payload.get('gripper_state_topic', '/binary_gripper_state')}",
            f"gripper_state_msg_type:={payload.get('gripper_state_msg_type', 'std_msgs.msg:Int8')}",
            f"external_camera_topic:={payload.get('external_camera_topic', '/camera2/scene_camera/color/image_raw/compressed')}",
            f"wrist_camera_topic:={payload.get('wrist_camera_topic', '/camera1/wrist_camera/color/image_raw/compressed')}",
            f"external_camera_msg_type:={payload.get('external_camera_msg_type', 'sensor_msgs.msg:CompressedImage')}",
            f"wrist_camera_msg_type:={payload.get('wrist_camera_msg_type', 'sensor_msgs.msg:CompressedImage')}",
            f"end_effector_pose_topic:={payload.get('end_effector_pose_topic', '/tcp_pose_broadcaster/pose')}",
            f"required_cameras:={payload.get('required_cameras', 'external,wrist')}",
            f"max_sync_delta_s:={_ros_double(payload.get('max_sync_delta_s', 0.02))}",
            f"camera_sync_tolerance_s:={_ros_double(payload.get('camera_sync_tolerance_s', 0.02))}",
            f"joint_state_sync_tolerance_s:={_ros_double(payload.get('joint_state_sync_tolerance_s', payload.get('state_max_sync_delta_s', 0.02)))}",
            f"gripper_sync_tolerance_s:={_ros_double(payload.get('gripper_sync_tolerance_s', 0.03))}",
            f"scene_camera_settle_delay_s:={_ros_double(payload.get('scene_camera_settle_delay_s', 0.07))}",
            f"camera_receive_delay_health_threshold_s:={_ros_double(payload.get('camera_receive_delay_health_threshold_s', 0.05))}",
            f"image_storage_format:={payload.get('image_storage_format', 'jpeg')}",
            f"jpeg_quality:={payload.get('jpeg_quality', 75)}",
        ]
        safety_topic = str(payload.get("safety_state_topic", "")).strip()
        if safety_topic:
            command.append(f"safety_state_topic:={safety_topic}")
        return command

    def _is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _remember_stopped_episodes(self, status: Optional[Mapping] = None) -> None:
        capture_status = dict(status or self.status())
        dataset_dir = capture_status.get("dataset_dir")
        if not dataset_dir:
            return
        stopped_dataset_dir = Path(dataset_dir)
        episode_indices = tuple(sorted(
            _episode_indices(stopped_dataset_dir) - self._episode_indices_before
        ))
        if episode_indices:
            self._pending_annotation_batches.append((stopped_dataset_dir, episode_indices))
        self._episode_indices_before = _episode_indices(stopped_dataset_dir)

    def _terminate_process_tree(self) -> None:
        if self.process is None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                return
            except Exception:
                pass
        self.process.terminate()

    def _kill_process_tree(self) -> None:
        if self.process is None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                return
            except Exception:
                pass
        self.process.kill()

    def _close_log(self) -> None:
        if self._log_stream is not None:
            self._log_stream.close()
            self._log_stream = None


def _safe_task_name(value) -> str:
    text = str(value).strip() or "capture_segment"
    return "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in text)


def _ros_double(value) -> str:
    """Format a ROS 2 DOUBLE parameter without integer type inference."""
    number = float(value)
    text = str(number)
    return text if "." in text or "e" in text.lower() else f"{text}.0"


def _timestamp_label(value: float) -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime(float(value)))


def _episode_indices(dataset_dir: Path) -> set:
    metadata_path = Path(dataset_dir) / "meta" / "episodes.jsonl"
    if not metadata_path.exists():
        return set()
    with metadata_path.open("r", encoding="utf-8-sig") as stream:
        return {
            int(json.loads(line)["episode_index"])
            for line in stream
            if line.strip()
        }


def _launch_arg_values(command: list) -> dict:
    values = {}
    for item in command:
        if ":=" in item:
            key, value = item.split(":=", 1)
            values[key] = value
    return values
