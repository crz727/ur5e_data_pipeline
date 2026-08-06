#pragma once

#include <memory>
#include <thread>

#include <QMainWindow>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/string.hpp>

#include <rviz_common/ros_integration/ros_node_abstraction.hpp>

class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QNetworkAccessManager;
class QPlainTextEdit;
class QPushButton;
class QSlider;
class QTimer;
class QVBoxLayout;

namespace rviz_common
{
class Display;
class VisualizationManager;
class VisualizationFrame;
}

namespace data_collection_rviz_panel
{

class TelemetryChart;

class MainWindow final : public QMainWindow
{
public:
  explicit MainWindow(QWidget * parent = nullptr);
  ~MainWindow() override;

private:
  void build_ui();
  void initialize_rviz();
  void initialize_ros();
  void request_dashboard_state();
  void request_replay_episodes();
  void request_capture_stop_and_annotation();
  void request_capture_annotation(const QString & outcome);
  void request_dataset_cleaning();
  void request_lerobot_export(const QString & cleaned_dataset_dir);
  void request_lerobot_export_status();
  void request_replay_seek(int frame_index);
  void update_capture_toggle();
  void post_json(const QString & path, const QJsonObject & payload);
  void update_dashboard_state(const QJsonObject & state);
  void update_camera(QLabel * label, const sensor_msgs::msg::CompressedImage & image);
  void request_mode(const QString & mode);

  rclcpp::Node::SharedPtr node_;
  rclcpp::executors::MultiThreadedExecutor::SharedPtr executor_;
  std::thread executor_thread_;
  std::shared_ptr<rviz_common::ros_integration::RosNodeAbstraction> rviz_node_;
  rviz_common::VisualizationManager * rviz_manager_{nullptr};
  rviz_common::VisualizationFrame * rviz_frame_{nullptr};
  rviz_common::Display * live_model_{nullptr};
  rviz_common::Display * replay_model_{nullptr};
  QVBoxLayout * rviz_layout_{nullptr};

  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr mode_request_publisher_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr robot_model_joint_state_publisher_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr replay_joint_state_publisher_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr mode_subscription_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr mode_status_subscription_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_subscription_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr gripper_joint_state_subscription_;
  rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr external_camera_subscription_;
  rclcpp::Subscription<sensor_msgs::msg::CompressedImage>::SharedPtr wrist_camera_subscription_;

  QNetworkAccessManager * network_{nullptr};
  QTimer * state_timer_{nullptr};
  QLabel * connection_label_{nullptr};
  QLabel * robot_health_value_{nullptr};
  QLabel * scene_camera_health_value_{nullptr};
  QLabel * wrist_camera_health_value_{nullptr};
  QLabel * writer_health_value_{nullptr};
  QLabel * external_camera_label_{nullptr};
  QLabel * wrist_camera_label_{nullptr};
  QLabel * mode_value_{nullptr};
  QLabel * mode_state_value_{nullptr};
  QLabel * mode_owner_value_{nullptr};
  QLabel * mode_step_value_{nullptr};
  QLabel * mode_fault_value_{nullptr};
  QLabel * capture_status_value_{nullptr};
  QLabel * dataset_path_value_{nullptr};
  QPushButton * capture_toggle_button_{nullptr};
  QPushButton * clean_dataset_button_{nullptr};
  QPushButton * idle_button_{nullptr};
  QPushButton * auto_button_{nullptr};
  QPushButton * api_button_{nullptr};
  QPushButton * teleop_button_{nullptr};
  QComboBox * capture_mode_{nullptr};
  QLineEdit * capture_task_{nullptr};
  QLineEdit * replay_dataset_path_{nullptr};
  QComboBox * replay_episode_{nullptr};
  QDoubleSpinBox * replay_rate_{nullptr};
  QSlider * replay_timeline_{nullptr};
  QLabel * replay_progress_value_{nullptr};
  QLabel * replay_status_value_{nullptr};
  QPushButton * replay_button_{nullptr};
  QPushButton * replay_pause_button_{nullptr};
  QPushButton * replay_resume_button_{nullptr};
  QPushButton * replay_stop_button_{nullptr};
  TelemetryChart * qpos_chart_{nullptr};
  TelemetryChart * qvel_chart_{nullptr};
  TelemetryChart * effort_chart_{nullptr};
  QPlainTextEdit * topics_text_{nullptr};
  QPlainTextEdit * topology_text_{nullptr};
  QPlainTextEdit * quality_text_{nullptr};
  QPlainTextEdit * drop_reason_text_{nullptr};
  QPlainTextEdit * replay_status_text_{nullptr};
  double replay_timestamp_{-1.0};
  double external_replay_camera_timestamp_{-1.0};
  double wrist_replay_camera_timestamp_{-1.0};
  int replay_episode_index_{-1};
  int replay_frame_index_{-1};
  QString last_replay_status_name_;
  QString capture_dataset_path_;
  bool capture_running_{false};
  bool replay_mode_active_{false};
  bool replay_timeline_dragging_{false};
  bool cleaning_in_progress_{false};
  bool lerobot_export_in_progress_{false};
};

}  // namespace data_collection_rviz_panel
