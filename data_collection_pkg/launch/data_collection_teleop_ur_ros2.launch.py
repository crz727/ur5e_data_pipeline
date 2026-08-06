from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("root", default_value="/tmp/ur5e_datasets"),
        DeclareLaunchArgument("task", default_value="teleop_ur_ros2"),
        DeclareLaunchArgument("action_topic", default_value="/teleop/command"),
        DeclareLaunchArgument("gripper_state_topic", default_value="/gripper/state"),
        DeclareLaunchArgument("external_camera_topic", default_value="/camera2/scene_camera/color/image_raw/compressed"),
        DeclareLaunchArgument("wrist_camera_topic", default_value="/camera1/wrist_camera/color/image_raw/compressed"),
        DeclareLaunchArgument("external_camera_msg_type", default_value="sensor_msgs.msg:CompressedImage"),
        DeclareLaunchArgument("wrist_camera_msg_type", default_value="sensor_msgs.msg:CompressedImage"),
        DeclareLaunchArgument("safety_state_topic", default_value="/safety/state"),
        DeclareLaunchArgument("end_effector_pose_topic", default_value="/tool0/pose"),
        DeclareLaunchArgument("max_sync_delta_s", default_value="0.05"),
        DeclareLaunchArgument("required_cameras", default_value=""),
        Node(
            package="data_collection_pkg",
            executable="data_collection_collector_node",
            name="data_collection_teleop_ur_ros2_collector",
            output="screen",
            parameters=[{
                "root": LaunchConfiguration("root"),
                "task": LaunchConfiguration("task"),
                "source": "teleop",
                "runtime_mode": "teleop",
                "dataset_schema": "teleop_twist_gripper",
                "action_topic": LaunchConfiguration("action_topic"),
                "gripper_state_topic": LaunchConfiguration("gripper_state_topic"),
                "external_camera_topic": LaunchConfiguration("external_camera_topic"),
                "wrist_camera_topic": LaunchConfiguration("wrist_camera_topic"),
                "external_camera_msg_type": LaunchConfiguration("external_camera_msg_type"),
                "wrist_camera_msg_type": LaunchConfiguration("wrist_camera_msg_type"),
                "safety_state_topic": LaunchConfiguration("safety_state_topic"),
                "end_effector_pose_topic": LaunchConfiguration("end_effector_pose_topic"),
                "servo_l_command_msg_type": "std_msgs.msg:String",
                "required_cameras": LaunchConfiguration("required_cameras"),
                "max_sync_delta_s": LaunchConfiguration("max_sync_delta_s"),
            }],
        ),
    ])
