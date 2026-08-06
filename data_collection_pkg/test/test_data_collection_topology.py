from data_collection_pkg.visualization.topology import (
    FlowHeartbeatMonitor,
    TopicEndpoint,
    build_topology_graph,
    summarize_flow,
)
from data_collection_pkg.visualization.topology_monitor_node import (
    DEFAULT_MONITORED_TOPICS,
    TopologyMonitorNodeAdapter,
    _parameter_list,
)


def test_topology_graph_represents_publishers_and_subscribers():
    graph = build_topology_graph([
        TopicEndpoint(topic="/joint_states", node="/ur_driver", direction="publisher"),
        TopicEndpoint(topic="/joint_states", node="/data_collector", direction="subscriber"),
    ])

    data = graph.to_dict()
    assert data["topics"]["/joint_states"]["publishers"] == ["/ur_driver"]
    assert data["topics"]["/joint_states"]["subscribers"] == ["/data_collector"]
    assert data["edges"] == [
        {"from": "/ur_driver", "to": "/data_collector", "topic": "/joint_states"}
    ]


def test_flow_summary_marks_active_and_stale_topics():
    status = summarize_flow(
        {
            "/joint_states": {"last_timestamp": 10.0, "publisher": "/ur_driver"},
            "/camera/wrist/color/image_raw/compressed": {"last_timestamp": 8.0, "publisher": "/wrist_camera"},
        },
        now=10.2,
        active_age_s=0.5,
    )

    assert status["topics"]["/joint_states"]["active"] is True
    assert status["topics"]["/camera/wrist/color/image_raw/compressed"]["active"] is False


def test_flow_heartbeat_monitor_includes_unseen_topics_and_graph_endpoints():
    graph = build_topology_graph([
        TopicEndpoint(topic="/joint_states", node="/ur_driver", direction="publisher"),
        TopicEndpoint(topic="/joint_states", node="/data_collection", direction="subscriber"),
        TopicEndpoint(topic="/camera/wrist", node="/camera_driver", direction="publisher"),
    ])
    monitor = FlowHeartbeatMonitor(("/joint_states", "/camera/wrist"))
    monitor.mark_received("/joint_states", timestamp=10.0, topic_type="sensor_msgs/msg/JointState")

    status = monitor.summarize(graph, now=10.2, active_age_s=0.5)

    joint_state = status["topics"]["/joint_states"]
    assert joint_state["active"] is True
    assert joint_state["seen"] is True
    assert joint_state["topic_type"] == "sensor_msgs/msg/JointState"
    assert joint_state["publishers"] == ["/ur_driver"]
    assert joint_state["subscribers"] == ["/data_collection"]

    camera = status["topics"]["/camera/wrist"]
    assert camera["active"] is False
    assert camera["seen"] is False
    assert camera["age_s"] is None
    assert camera["publishers"] == ["/camera_driver"]


def test_default_monitored_topics_include_real_robot_camera_and_tcp_streams():
    assert "/camera2/scene_camera/color/image_raw/compressed" in DEFAULT_MONITORED_TOPICS
    assert "/camera1/wrist_camera/color/image_raw/compressed" in DEFAULT_MONITORED_TOPICS
    assert "/tcp_pose_broadcaster/pose" in DEFAULT_MONITORED_TOPICS


def test_parameter_list_accepts_string_list_overrides():
    class FakeParameter:
        def __init__(self, value):
            self.value = value

    class FakeNode:
        def __init__(self, value):
            self.value = value

        def get_parameter(self, name):
            return FakeParameter(self.value)

    default = ["/joint_states"]

    assert _parameter_list(
        FakeNode('["/joint_states", "/camera/external/color/image_raw"]'),
        "monitored_topics",
        default,
    ) == ["/joint_states", "/camera/external/color/image_raw"]
    assert _parameter_list(
        FakeNode("/joint_states,/camera/wrist/color/image_raw"),
        "monitored_topics",
        default,
    ) == ["/joint_states", "/camera/wrist/color/image_raw"]
    assert _parameter_list(FakeNode(""), "monitored_topics", default) == default


def test_topology_monitor_adapter_publishes_graph_and_flow_json():
    class FakeStamp:
        nanoseconds = 10_200_000_000

    class FakeClock:
        def now(self):
            return FakeStamp()

    class FakePublisher:
        def __init__(self):
            self.messages = []

        def publish(self, msg):
            self.messages.append(msg)

    class FakeParameter:
        def __init__(self, value):
            self.value = value

    class FakeInfo:
        def __init__(self, node_name, topic_type):
            self.node_name = node_name
            self.topic_type = topic_type

    class FakeNode:
        def __init__(self):
            self.parameters = {
                "publish_rate_hz": FakeParameter(2.0),
                "active_age_s": FakeParameter(0.5),
                "monitored_topics": FakeParameter(["/joint_states"]),
            }
            self.topics = [("/joint_states", ["sensor_msgs/msg/JointState"])]
            self.publisher_info = [FakeInfo("/ur_driver", "sensor_msgs/msg/JointState")]
            self.subscription_info = [FakeInfo("/data_collection", "sensor_msgs/msg/JointState")]
            self.published = {}

        def create_publisher(self, msg_type, topic, queue_size):
            pub = FakePublisher()
            self.published[topic] = pub
            return pub

        def create_subscription(self, *args, **kwargs):
            return object()

        def create_timer(self, *args, **kwargs):
            return object()

        def get_parameter(self, name):
            return self.parameters[name]

        def declare_parameter(self, *args, **kwargs):
            return None

        def get_topic_names_and_types(self):
            return self.topics

        def get_publishers_info_by_topic(self, topic):
            return self.publisher_info if topic == "/joint_states" else []

        def get_subscriptions_info_by_topic(self, topic):
            return self.subscription_info if topic == "/joint_states" else []

        def get_clock(self):
            return FakeClock()

        def get_logger(self):
            class Logger:
                def info(self, *args, **kwargs):
                    return None

                def warning(self, *args, **kwargs):
                    return None

            return Logger()

    class FakeString:
        def __init__(self, data=""):
            self.data = data

    node = FakeNode()
    adapter = TopologyMonitorNodeAdapter(node=node, string_msg_type=FakeString)
    adapter.heartbeat.mark_received(
        "/joint_states",
        timestamp=10.0,
        topic_type="sensor_msgs/msg/JointState",
    )
    adapter.publish_status()

    topology_payload = node.published["/data_collection/topology_graph"].messages[-1].data
    flow_payload = node.published["/data_collection/flow_status"].messages[-1].data

    assert '"publishers": ["/ur_driver"]' in topology_payload
    assert '"subscribers": ["/data_collection"]' in topology_payload
    assert '"seen": true' in flow_payload
    assert '"active": true' in flow_payload
    assert '"topic_type": "sensor_msgs/msg/JointState"' in flow_payload
