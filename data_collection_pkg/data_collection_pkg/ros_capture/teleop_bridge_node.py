"""Reserved publish-only action-collection bridge entry point.

This node intentionally remains a minimal ROS2 lifecycle placeholder. It is
reserved for a future action-triggered collector and is not part of the
current fixed-rate ``qpos_gripper`` capture path.
"""


def teleop_bridge_node_main(args=None):
    """Keep the reserved action-collection bridge node alive."""
    import rclpy

    rclpy.init(args=args)
    try:
        node = rclpy.create_node("teleop_bridge")
        node.get_logger().info("publish-only teleop bridge adapter started")
        rclpy.spin(node)
    finally:
        rclpy.shutdown()
