"""Compatibility launch for HTTP control-event audit collectors.

This is not the current ``runtime_mode:=http`` fixed-rate capture entry point.
It records legacy ``http_api_action``, ``delta_ee_pose`` and ``auto_grasp``
events when the corresponding external topics are available.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _collector_node(name, schema, action_topic):
    root = LaunchConfiguration("root")
    task = LaunchConfiguration("task")
    max_sync_delta_s = LaunchConfiguration("max_sync_delta_s")
    gripper_state_topic = LaunchConfiguration("gripper_state_topic")

    return Node(
        package="data_collection_pkg",
        executable="data_collection_collector_node",
        name=name,
        output="screen",
        parameters=[{
            "root": root,
            "task": task,
            "source": "http_api",
            "runtime_mode": "http_api",
            "dataset_schema": schema,
            "action_topic": action_topic,
            "gripper_state_topic": gripper_state_topic,
            "servo_l_command_msg_type": "std_msgs.msg:String",
            "required_cameras": "",
            "max_sync_delta_s": max_sync_delta_s,
        }],
    )


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("root", default_value="/tmp/ur5e_datasets"),
        DeclareLaunchArgument("task", default_value="http_api"),
        DeclareLaunchArgument("max_sync_delta_s", default_value="0.07"),
        DeclareLaunchArgument("gripper_state_topic", default_value="/gripper/state"),
        _collector_node(
            "data_collection_http_api_action_collector",
            "http_api_action",
            "/ur5e/control/action_event",
        ),
        _collector_node(
            "data_collection_http_api_delta_collector",
            "delta_ee_pose",
            "/ur5e/control/delta_ee_pose_event",
        ),
        _collector_node(
            "data_collection_auto_grasp_collector",
            "auto_grasp",
            "/auto_grasp/event",
        ),
    ])
