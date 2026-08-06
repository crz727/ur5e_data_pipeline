from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    dataset_dir = LaunchConfiguration("dataset_dir")
    episode_index = LaunchConfiguration("episode_index")
    rate_hz = LaunchConfiguration("rate_hz")
    sim_command_topic = LaunchConfiguration("sim_command_topic")
    frame_id = LaunchConfiguration("frame_id")

    return LaunchDescription([
        DeclareLaunchArgument("dataset_dir", default_value=""),
        DeclareLaunchArgument("episode_index", default_value="0"),
        DeclareLaunchArgument("rate_hz", default_value="10.0"),
        DeclareLaunchArgument(
            "sim_command_topic",
            default_value="/ur_control/sim/replay_command",
        ),
        DeclareLaunchArgument("frame_id", default_value="base"),
        Node(
            package="data_collection_pkg",
            executable="data_collection_replay_simulator_node",
            name="data_collection_replay_simulator",
            output="screen",
            parameters=[{
                "dataset_dir": dataset_dir,
                "episode_index": episode_index,
                "rate_hz": rate_hz,
            }],
        ),
        Node(
            package="data_collection_pkg",
            executable="ursim_rviz_replay_adapter_node",
            name="ursim_rviz_replay_adapter",
            output="screen",
            parameters=[{
                "sim_command_topic": sim_command_topic,
                "frame_id": frame_id,
            }],
        ),
    ])
