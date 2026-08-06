from data_collection_pkg.ros_capture.synchronizer import (
    Sample,
    TopicSynchronizer,
)


def test_synchronizer_builds_frame_when_required_topics_are_close():
    synchronizer = TopicSynchronizer(
        required_topics=("/joint_states", "/teleop/command"),
        optional_topics=("/camera/wrist",),
        tolerance_s=0.05,
    )
    synchronizer.add_sample(Sample("/joint_states", 10.00, {"state": [0.0] * 7}))
    synchronizer.add_sample(Sample("/teleop/command", 10.03, {"action": [1.0] * 7}))
    synchronizer.add_sample(Sample("/camera/wrist", 9.90, {"image": "old"}))
    synchronizer.add_sample(Sample("/camera/wrist", 10.02, {"image": "fresh"}))

    frame = synchronizer.synchronize_at(10.03)

    assert frame.ok is True
    assert frame.drop_reasons == []
    assert frame.timestamp == 10.03
    assert frame.samples["/joint_states"].payload == {"state": [0.0] * 7}
    assert frame.samples["/camera/wrist"].payload == {"image": "fresh"}


def test_synchronizer_reports_missing_and_stale_required_topics():
    synchronizer = TopicSynchronizer(
        required_topics=("/joint_states", "/teleop/command"),
        tolerance_s=0.05,
    )
    synchronizer.add_sample(Sample("/joint_states", 9.90, {"state": [0.0] * 7}))

    frame = synchronizer.synchronize_at(10.03)

    assert frame.ok is False
    assert frame.samples == {}
    assert frame.drop_reasons == [
        "stale_topic:/joint_states",
        "missing_topic:/teleop/command",
    ]


def test_synchronizer_allows_per_topic_tolerances_for_slow_state_topics():
    synchronizer = TopicSynchronizer(
        required_topics=("/joint_states", "/robotiq_2f_gripper/joint_states"),
        optional_topics=("/camera",),
        tolerance_s=0.05,
        topic_tolerances={
            "/joint_states": 0.25,
            "/robotiq_2f_gripper/joint_states": 0.5,
        },
    )
    synchronizer.add_sample(Sample("/joint_states", 9.85, {"state": [0.0] * 7}))
    synchronizer.add_sample(Sample("/robotiq_2f_gripper/joint_states", 9.65, {"gripper": 0.2}))
    synchronizer.add_sample(Sample("/camera", 9.90, {"image": "too old for camera"}))

    frame = synchronizer.synchronize_at(10.0)

    assert frame.ok is True
    assert "/joint_states" in frame.samples
    assert "/robotiq_2f_gripper/joint_states" in frame.samples
    assert "/camera" not in frame.samples
