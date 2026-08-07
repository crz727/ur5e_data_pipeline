import numpy as np
import pytest
from io import BytesIO
from PIL import Image

from data_collection_pkg.dataset.lerobot_writer import LeRobotDatasetWriter


class FakeLeRobotDataset:
    created = None

    def __init__(self):
        self.frames = []
        self.saved = 0
        self.finalized = False

    @classmethod
    def create(cls, **kwargs):
        cls.created = kwargs
        return cls()

    def add_frame(self, frame):
        self.frames.append(frame)

    def save_episode(self):
        self.saved += 1

    def finalize(self):
        self.finalized = True


def test_lerobot_writer_calls_official_dataset_api(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "qpos_gripper",
        repo_id="local/ur5e_pick",
        dataset_cls=FakeLeRobotDataset,
    )

    writer.start_episode(task="pick")
    writer.add_frame(
        {"timestamp": 1.25, "state": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3]},
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8],
    )
    writer.close_episode()
    writer.finalize()

    assert FakeLeRobotDataset.created["repo_id"] == "local/ur5e_pick"
    assert FakeLeRobotDataset.created["root"] == tmp_path / "trainable" / "policy" / "qpos_gripper"
    assert writer.dataset.saved == 1
    assert writer.dataset.finalized is True
    assert "timestamp" not in FakeLeRobotDataset.created["features"]
    assert "timestamp" not in writer.dataset.frames[0]
    assert np.allclose(writer.dataset.frames[0]["observation.state"], np.array([0.0] * 6 + [0.3]))
    assert np.allclose(writer.dataset.frames[0]["action"], np.array([0.0] * 6 + [0.8]))


def test_lerobot_writer_declares_camera_features(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "teleop_servo_l_pose",
        repo_id="local/teleop",
        cameras=("external", "wrist"),
        image_shape=(480, 640, 3),
        dataset_cls=FakeLeRobotDataset,
    )

    features = FakeLeRobotDataset.created["features"]

    assert features["observation.images.external"]["shape"] == (480, 640, 3)
    assert features["observation.images.wrist"]["shape"] == (480, 640, 3)
    assert features["observation.images.external"]["dtype"] == "video"
    assert FakeLeRobotDataset.created["use_videos"] is True
    assert FakeLeRobotDataset.created["vcodec"] == "h264"
    assert type(FakeLeRobotDataset.created["fps"]) is int


def test_lerobot_writer_rejects_non_integer_video_fps(tmp_path):
    with pytest.raises(ValueError, match="integer fps"):
        LeRobotDatasetWriter(
            tmp_path,
            "qpos_gripper",
            repo_id="local/pick",
            cameras=("wrist",),
            fps=12.5,
            dataset_cls=FakeLeRobotDataset,
        )


def test_lerobot_writer_can_keep_legacy_images_outside_video_mode(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "qpos_gripper",
        repo_id="local/pick",
        cameras=("wrist",),
        visual_storage="image",
        dataset_cls=FakeLeRobotDataset,
    )

    assert FakeLeRobotDataset.created["features"]["observation.images.wrist"]["dtype"] == "image"
    assert FakeLeRobotDataset.created["use_videos"] is False


def test_lerobot_writer_converts_project_image_payloads_to_arrays(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "teleop_servo_l_pose",
        repo_id="local/teleop",
        cameras=("external", "wrist"),
        image_shape=(1, 1, 3),
        dataset_cls=FakeLeRobotDataset,
    )

    writer.start_episode(task="teleop")
    writer.add_frame(
        {
            "timestamp": 1.0,
            "state": [0.0] * 7,
            "images": {
                "external": {"format": "raw", "data": [1, 2, 3], "frame_id": "external"},
                "wrist": np.array([[[4, 5, 6]]], dtype=np.uint8),
            },
        },
        [0.0] * 7,
    )

    frame = writer.dataset.frames[0]

    assert isinstance(frame["observation.images.external"], np.ndarray)
    assert frame["observation.images.external"].shape == (1, 1, 3)
    assert frame["observation.images.external"].dtype == np.uint8
    assert frame["observation.images.external"].tolist() == [[[1, 2, 3]]]
    assert isinstance(frame["observation.images.wrist"], np.ndarray)


def test_lerobot_writer_decodes_compressed_jpeg_payload(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "qpos_gripper",
        repo_id="local/pick",
        cameras=("external",),
        image_shape=(2, 3, 3),
        dataset_cls=FakeLeRobotDataset,
    )
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color=(10, 20, 30)).save(buffer, format="JPEG")

    writer.start_episode(task="pick")
    writer.add_frame(
        {
            "state": [0.0] * 7,
            "images": {"external": {"codec": "jpeg", "data": list(buffer.getvalue())}},
        },
        [0.0] * 7,
    )

    assert writer.dataset.frames[0]["observation.images.external"].shape == (2, 3, 3)


def test_lerobot_writer_declares_and_writes_end_effector_pose(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "teleop_servo_l_pose",
        repo_id="local/teleop",
        include_ee_pose=True,
        dataset_cls=FakeLeRobotDataset,
    )

    writer.start_episode(task="teleop")
    writer.add_frame(
        {
            "timestamp": 1.0,
            "state": [0.0] * 7,
            "ee_pose": [0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0],
        },
        [0.0] * 7,
    )

    features = FakeLeRobotDataset.created["features"]
    frame = writer.dataset.frames[0]

    assert features["observation.ee_pose"]["shape"] == (7,)
    assert np.allclose(
        frame["observation.ee_pose"],
        np.array([0.4, 0.1, 0.3, 0.0, 0.0, 0.0, 1.0]),
    )


def test_lerobot_writer_rejects_macro_schema(tmp_path):
    with pytest.raises(ValueError, match="does not support LeRobotDataset"):
        LeRobotDatasetWriter(
            tmp_path,
            "auto_grasp",
            repo_id="local/macro",
            dataset_cls=FakeLeRobotDataset,
        )


def test_lerobot_writer_uses_each_episode_task_and_rejects_blank_tasks(tmp_path):
    writer = LeRobotDatasetWriter(
        tmp_path,
        "qpos_gripper",
        repo_id="local/multi-task",
        dataset_cls=FakeLeRobotDataset,
    )

    writer.start_episode(task="pick-red-block")
    writer.add_frame({"state": [0.0] * 7}, [0.0] * 7)
    writer.close_episode()
    writer.start_episode(task="place-blue-block")
    writer.add_frame({"state": [1.0] * 7}, [1.0] * 7)
    writer.close_episode()

    assert [frame["task"] for frame in writer.dataset.frames] == [
        "pick-red-block",
        "place-blue-block",
    ]
    with pytest.raises(ValueError, match="task must be non-empty"):
        writer.start_episode(task="   ")
