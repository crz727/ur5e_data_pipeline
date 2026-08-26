from setuptools import find_packages, setup

package_name = "data_collection_pkg"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", [
            "launch/data_collection_monitor.launch.py",
            "launch/data_collection_hardware_qpos.launch.py",
            "launch/data_collection_http_api.launch.py",
            "launch/data_collection_teleop_ur_ros2.launch.py",
            "launch/data_collection_teleop_demo_qpos.launch.py",
            "launch/data_collection_replay.launch.py",
        ]),
    ],
    install_requires=["setuptools", "flask", "numpy"],
    zip_safe=True,
    maintainer="陈润泽",
    maintainer_email="1762638741@qq.com",
    description="Reusable ROS2 data collection, validation, visualization, LeRobot export, and replay package for UR5e workflows.",
    license="Apache-2.0",
    extras_require={
        "test": ["pytest"],
        "lerobot": ["lerobot"],
    },
    entry_points={
        "console_scripts": [
            "data_collection = data_collection_pkg.cli:main",
            "data_collection_collector_node = data_collection_pkg.ros_capture.collector_node:collector_node_main",
            "data_collection_quality_monitor_node = data_collection_pkg.ros_capture.quality_monitor_node:quality_monitor_node_main",
            "data_collection_topology_monitor_node = data_collection_pkg.visualization.topology_monitor_node:topology_monitor_node_main",
            "data_collection_web_dashboard_node = data_collection_pkg.visualization.web_dashboard_node:web_dashboard_node_main",
            "hardware_interface_check = data_collection_pkg.hardware_check.hardware_interface_check_node:hardware_interface_check_node_main",
            "data_collection_replay_simulator_node = data_collection_pkg.action_replay.replay_simulator_node:replay_simulator_node_main",
            "ursim_rviz_replay_adapter_node = data_collection_pkg.action_replay.ursim_rviz_adapter_node:ursim_rviz_adapter_node_main",
            "teleop_bridge_node = data_collection_pkg.ros_capture.teleop_bridge_node:teleop_bridge_node_main",
        ],
    },
)
