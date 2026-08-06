from types import SimpleNamespace

from data_collection_pkg.ros_capture.message_adapters import (
    camera_sample,
    end_effector_pose_sample,
    gripper_sample,
    joint_state_sample,
    safety_sample,
    servo_l_command_sample,
)
from data_collection_pkg.ros_capture.teleop_recorder import TELEOP_TOPICS


def test_joint_state_adapter_preserves_joint_names_and_numeric_fields():
    msg = SimpleNamespace(
        name=["wrist_2_joint", "shoulder_pan_joint"],
        position=[0.0, -1.0, 1.0, -1.5, -1.2, 0.1],
        velocity=[0.1] * 6,
        effort=[0.2] * 6,
    )

    sample = joint_state_sample(msg, timestamp=10.0)

    assert sample.topic == TELEOP_TOPICS["joint_states"]
    assert sample.timestamp == 10.0
    assert sample.payload == {
        "joint_names": ["wrist_2_joint", "shoulder_pan_joint"],
        "positions": [0.0, -1.0, 1.0, -1.5, -1.2, 0.1],
        "velocities": [0.1] * 6,
        "efforts": [0.2] * 6,
    }


def test_servo_l_adapter_accepts_data_or_pose_fields():
    msg = SimpleNamespace(data=[0.4, 0.0, 0.3, 3.14, 0.0, 1.57, 0.6])

    sample = servo_l_command_sample(msg, timestamp=10.1)

    assert sample.topic == TELEOP_TOPICS["servo_l_command"]
    assert sample.payload == {"action": [0.4, 0.0, 0.3, 3.14, 0.0, 1.57, 0.6]}


def test_action_adapter_accepts_json_action_event():
    msg = SimpleNamespace(
        data=(
            '{"source": "http_api", "runtime_mode": "http_api", '
            '"action_schema": "qpos_gripper", "action": [0, 1, 2, 3, 4, 5, 0.6], '
            '"converted_from": "/ur5e/control/action_event"}'
        )
    )

    sample = servo_l_command_sample(
        msg,
        timestamp=10.2,
        topic="/ur5e/control/action_event",
    )

    assert sample.topic == "/ur5e/control/action_event"
    assert sample.payload == {
        "source": "http_api",
        "runtime_mode": "http_api",
        "action_schema": "qpos_gripper",
        "action": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 0.6],
        "converted_from": "/ur5e/control/action_event",
    }


def test_action_adapter_preserves_json_mapping_action_event():
    msg = SimpleNamespace(
        data=(
            '{"source": "http_api", "runtime_mode": "http_api", '
            '"action_schema": "http_api_action", '
            '"action": {"command_schema": "qpos_gripper", "values": [0, 1, 2, 3, 4, 5, 0.6]}, '
            '"converted_from": "/ur5e/control/action_event"}'
        )
    )

    sample = servo_l_command_sample(
        msg,
        timestamp=10.2,
        topic="/ur5e/control/action_event",
    )

    assert sample.payload["action_schema"] == "http_api_action"
    assert sample.payload["action"] == {
        "command_schema": "qpos_gripper",
        "values": [0, 1, 2, 3, 4, 5, 0.6],
    }


def test_gripper_safety_and_camera_adapters_build_payloads():
    gripper = gripper_sample(SimpleNamespace(data=[0.75]), timestamp=1.0)
    safety = safety_sample(
        SimpleNamespace(software_estop=True, protective_stop=False, gello_intervention=False),
        timestamp=1.0,
    )
    camera = camera_sample(
        SimpleNamespace(
            format="jpeg",
            data=b"abc",
            width=2,
            height=1,
            encoding="rgb8",
            step=6,
            header=SimpleNamespace(frame_id="wrist"),
        ),
        topic=TELEOP_TOPICS["wrist_camera"],
        timestamp=1.0,
    )

    assert gripper.payload == {"gripper": 0.75}
    assert safety.payload["software_estop"] is True
    assert camera.payload == {
        "format": "jpeg",
        "data": b"abc",
        "frame_id": "wrist",
        "height": 1,
        "width": 2,
        "encoding": "rgb8",
        "step": 6,
        "timestamp": 1.0,
    }


def test_compressed_image_adapter_preserves_jpeg_transport_without_raw_dimensions():
    camera = camera_sample(
        SimpleNamespace(
            format="jpeg",
            data=b"\xff\xd8jpeg-bytes\xff\xd9",
            header=SimpleNamespace(frame_id="scene_camera"),
        ),
        topic="/camera2/scene_camera/color/image_raw/compressed",
        timestamp=2.0,
    )

    assert camera.payload["transport"] == "compressed"
    assert camera.payload["codec"] == "jpeg"
    assert camera.payload["data"] == b"\xff\xd8jpeg-bytes\xff\xd9"
    assert camera.payload["height"] == 0
    assert camera.payload["width"] == 0


def test_safety_adapter_accepts_json_string_data():
    safety = safety_sample(
        SimpleNamespace(
            data='{"software_estop": false, "protective_stop": true, "gello_intervention": false}'
        ),
        timestamp=1.0,
    )

    assert safety.payload == {
        "software_estop": False,
        "protective_stop": True,
        "gello_intervention": False,
    }


def test_end_effector_pose_adapter_extracts_pose_and_frames():
    msg = SimpleNamespace(
        header=SimpleNamespace(frame_id="base"),
        pose=SimpleNamespace(
            position=SimpleNamespace(x=0.4, y=0.1, z=0.3),
            orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )

    sample = end_effector_pose_sample(msg, timestamp=2.5)

    assert sample.topic == TELEOP_TOPICS["end_effector_pose"]
    assert sample.payload == {
        "frame_id": "base",
        "child_frame_id": "tool0",
        "pose": [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0],
    }
