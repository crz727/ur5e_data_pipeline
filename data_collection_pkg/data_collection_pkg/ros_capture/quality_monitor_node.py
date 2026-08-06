"""ROS2 entry point for real-time quality monitoring."""


def quality_monitor_node_main(args=None):
    """Start the ROS2 quality monitor adapter."""
    import rclpy

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("data_collection_quality_monitor")
        node.get_logger().info("data_collection quality monitor adapter started")
        rclpy.spin(node)
    finally:
        rclpy.shutdown()
