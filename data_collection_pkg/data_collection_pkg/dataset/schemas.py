"""Action schema registry for the ROS2-only data pipeline."""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union


OBSERVATION_SCHEMA = "ur5e_ros2_observation_v1"


@dataclass(frozen=True)
class ActionSchema:
    """One final action schema used for dataset classification."""

    name: str
    category: str
    directory: str
    runtime_mode: str
    action_fields: Tuple[str, ...]
    action_dim: Optional[int]
    observation_schema: str = OBSERVATION_SCHEMA

    @property
    def lerobot_compatible(self) -> bool:
        """Return whether this schema can be written as a numeric LeRobot action."""
        return self.category == "trainable" and self.action_dim is not None


SCHEMAS: Dict[str, ActionSchema] = {
    "qpos_gripper": ActionSchema(
        name="qpos_gripper",
        category="trainable",
        directory="policy/qpos_gripper",
        runtime_mode="policy",
        action_fields=(
            "target_qpos_0",
            "target_qpos_1",
            "target_qpos_2",
            "target_qpos_3",
            "target_qpos_4",
            "target_qpos_5",
            "target_gripper",
        ),
        action_dim=7,
    ),
    "teleop_servo_l_pose": ActionSchema(
        name="teleop_servo_l_pose",
        category="trainable",
        directory="teleop/servo_l_pose",
        runtime_mode="teleop",
        action_fields=("x", "y", "z", "rx", "ry", "rz", "gripper"),
        action_dim=7,
    ),
    "teleop_twist_gripper": ActionSchema(
        name="teleop_twist_gripper",
        category="trainable",
        directory="teleop/twist_gripper",
        runtime_mode="teleop",
        action_fields=("vx", "vy", "vz", "wx", "wy", "wz", "gripper"),
        action_dim=7,
    ),
    "delta_ee_pose": ActionSchema(
        name="delta_ee_pose",
        category="debug",
        directory="http_api/delta_ee_pose",
        runtime_mode="http_api",
        action_fields=("dx", "dy", "dz", "dqx", "dqy", "dqz", "dqw"),
        action_dim=7,
    ),
    "auto_grasp": ActionSchema(
        name="auto_grasp",
        category="macro",
        directory="auto_grasp",
        runtime_mode="auto_grasp",
        action_fields=("event", "parameters"),
        action_dim=None,
    ),
    "http_api_action": ActionSchema(
        name="http_api_action",
        category="debug",
        directory="http_api/action",
        runtime_mode="http_api",
        action_fields=("endpoint", "action_schema", "action", "parameters"),
        action_dim=None,
    ),
    "debug_replay": ActionSchema(
        name="debug_replay",
        category="debug",
        directory="replay",
        runtime_mode="debug",
        action_fields=("event", "payload"),
        action_dim=None,
    ),
}


def get_schema(name: str) -> ActionSchema:
    """Return the registered action schema named by ``name``."""
    try:
        return SCHEMAS[name]
    except KeyError as exc:
        raise KeyError(f"unknown action schema: {name}") from exc


def dataset_relative_dir(
    schema_or_name: Union[ActionSchema, str],
    *,
    dataset_stage: Optional[str] = None,
    runtime_mode: Optional[str] = None,
) -> str:
    """Return the storage directory for one schema."""
    schema = get_schema(schema_or_name) if isinstance(schema_or_name, str) else schema_or_name
    if schema.name == "qpos_gripper" and dataset_stage:
        mode = str(runtime_mode or schema.runtime_mode).strip() or schema.runtime_mode
        return f"{dataset_stage}/{mode}/qpos_gripper"
    return f"{schema.category}/{schema.directory}"
