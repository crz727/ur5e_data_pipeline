"""Publish-only teleoperation bridge entry point."""


def teleop_bridge_node_main(args=None):
    """Start a publish-only teleop bridge adapter."""
    import rclpy

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("teleop_bridge")
        node.get_logger().info("publish-only teleop bridge adapter started")
        rclpy.spin(node)
    finally:
        rclpy.shutdown()
