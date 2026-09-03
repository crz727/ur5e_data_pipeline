"""Start the Qt/RViz console and its safe, read-only replay visualization."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, Shutdown
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    data_collection_share = get_package_share_directory("data_collection_pkg")
    description_share = get_package_share_directory("my_description")
    monitor_launch = os.path.join(
        data_collection_share, "launch", "data_collection_monitor.launch.py"
    )
    xacro_file = os.path.join(description_share, "urdf", "my_robot.urdf.xacro")

    dashboard_host = LaunchConfiguration("dashboard_host")
    dashboard_port = LaunchConfiguration("dashboard_port")
    dashboard_url = LaunchConfiguration("dashboard_url")
    capture_root = LaunchConfiguration("capture_root")
    start_live_state_publisher = LaunchConfiguration("start_live_state_publisher")
    start_replay_state_publisher = LaunchConfiguration("start_replay_state_publisher")

    live_description = ParameterValue(
        Command(["xacro ", xacro_file]), value_type=str
    )
    replay_description = ParameterValue(
        Command(["xacro ", xacro_file]), value_type=str
    )

    return LaunchDescription([
        DeclareLaunchArgument("dashboard_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("dashboard_port", default_value="8765"),
        DeclareLaunchArgument("dashboard_url", default_value="http://127.0.0.1:8765"),
        DeclareLaunchArgument(
            "capture_root", default_value="~/ur5e_ws/datasets/ui_capture"
        ),
        DeclareLaunchArgument("start_live_state_publisher", default_value="true"),
        DeclareLaunchArgument("start_replay_state_publisher", default_value="true"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(monitor_launch),
            launch_arguments={
                "dashboard_host": dashboard_host,
                "dashboard_port": dashboard_port,
                "capture_root": capture_root,
            }.items(),
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="data_collection_live_state_publisher",
            output="screen",
            condition=IfCondition(start_live_state_publisher),
            parameters=[{
                "robot_description": live_description,
            }],
            remappings=[
                ("joint_states", "/data_collection/robot_model/joint_states"),
                ("robot_description", "/robot_description"),
            ],
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="data_collection_replay_state_publisher",
            output="screen",
            condition=IfCondition(start_replay_state_publisher),
            parameters=[{
                "robot_description": replay_description,
                "frame_prefix": "replay/",
            }],
            remappings=[
                ("joint_states", "/data_collection/replay/joint_states"),
                ("robot_description", "/replay/robot_description"),
            ],
        ),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="data_collection_replay_world_transform",
            output="screen",
            condition=IfCondition(start_replay_state_publisher),
            arguments=[
                "--x", "0", "--y", "0", "--z", "0",
                "--roll", "0", "--pitch", "0", "--yaw", "0",
                "--frame-id", "base_link", "--child-frame-id", "replay/world",
            ],
        ),
        Node(
            package="data_collection_rviz_panel",
            executable="data_collection_rviz_panel",
            output="screen",
            parameters=[{"dashboard_url": dashboard_url}],
            on_exit=Shutdown(reason="Qt data collection panel exited"),
        ),
    ])
