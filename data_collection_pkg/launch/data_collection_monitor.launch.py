"""Launch data collection topology and flow monitoring."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    publish_rate_hz = LaunchConfiguration("publish_rate_hz")
    active_age_s = LaunchConfiguration("active_age_s")
    monitored_topics = LaunchConfiguration("monitored_topics")
    dashboard_host = LaunchConfiguration("dashboard_host")
    dashboard_port = LaunchConfiguration("dashboard_port")
    capture_root = LaunchConfiguration("capture_root")
    external_camera_topic = LaunchConfiguration("external_camera_topic")
    wrist_camera_topic = LaunchConfiguration("wrist_camera_topic")

    return LaunchDescription([
        DeclareLaunchArgument("publish_rate_hz", default_value="2.0"),
        DeclareLaunchArgument("active_age_s", default_value="2.0"),
        DeclareLaunchArgument("monitored_topics", default_value=""),
        DeclareLaunchArgument("dashboard_host", default_value="0.0.0.0"),
        DeclareLaunchArgument("dashboard_port", default_value="8765"),
        DeclareLaunchArgument("capture_root", default_value="~/ur5e_ws/datasets/ui_capture"),
        DeclareLaunchArgument(
            "external_camera_topic",
            default_value="/camera2/scene_camera/color/image_raw/compressed",
        ),
        DeclareLaunchArgument(
            "wrist_camera_topic",
            default_value="/camera1/wrist_camera/color/image_raw/compressed",
        ),
        Node(
            package="data_collection_pkg",
            executable="data_collection_topology_monitor_node",
            name="data_collection_topology_monitor",
            output="screen",
            parameters=[{
                "publish_rate_hz": publish_rate_hz,
                "active_age_s": active_age_s,
                "monitored_topics": monitored_topics,
            }],
        ),
        Node(
            package="data_collection_pkg",
            executable="data_collection_web_dashboard_node",
            name="data_collection_web_dashboard",
            output="screen",
            parameters=[{
                "host": dashboard_host,
                "port": dashboard_port,
                "capture_root": capture_root,
                "external_camera_topic": external_camera_topic,
                "wrist_camera_topic": wrist_camera_topic,
            }],
        ),
    ])
