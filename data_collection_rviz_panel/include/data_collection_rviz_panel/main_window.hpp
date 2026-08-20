#pragma once

#include <memory>
#include <thread>

#include <QJsonArray>
#include <QMainWindow>
#include <QtGlobal>

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
class QProgressBar;
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
  void request_language_instruction_editor();
  void show_language_instruction_editor(const QJsonArray & labels);
  void request_lerobot_export(const QString & cleaned_dataset_dir, const QString & profile);
  void request_lerobot_export_preflight(
    const QString & cleaned_dataset_dir, const QString & profile, const QString & output_dir);
  void start_lerobot_export(
    const QString & cleaned_dataset_dir, const QString & profile, const QString & output_dir);
  void request_lerobot_export_status();
  void set_lerobot_export_activity(bool active);
  void request_replay_seek(int frame_index);
  void update_capture_toggle();
  void show_temporary_capture_status(const QString & status);
  void post_json(const QString & path, const QJsonObject & payload);
  void clear_capture_dataset_selection();
  void apply_existing_dataset_selection(const QJsonObject & capture);
  void update_dashboard_state(const QJsonObject & state);
  void update_camera(QLabel * label, const sensor_msgs::msg::CompressedImage & image);
  void request_mode(const QString & mode);
  void request_existing_dataset();
  void request_standalone_lerobot_export();
  void start_control_services();
  void stop_control_services();
  bool recover_residual_control_services();
  void check_control_api_health();
  void start_control_mode_manager();
  void stop_owned_mode_manager();
  void stop_owned_control_api();
  void check_owned_control_processes_stopped();
  void fail_control_services_start(const QString & reason);
  void finish_control_services_stop(const QString & status);
  void set_mode_buttons_enabled(bool enabled);
  void update_control_services_button();
  void handle_control_services_timeout();

  enum class ControlServicesState
  {
    Stopped,
    CheckingExternalApi,
    StartingApi,
    StartingModeManager,
    Running,
    WaitingForIdle,
    StoppingModeManager,
    StoppingApi,
  };

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
  QTimer * control_services_timeout_timer_{nullptr};
  QTimer * mode_status_stale_timer_{nullptr};
  qint64 control_api_pid_{0};
  qint64 control_mode_manager_pid_{0};
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
  QLabel * control_services_status_value_{nullptr};
  QLabel * capture_status_value_{nullptr};
  QLabel * dataset_path_value_{nullptr};
  QProgressBar * lerobot_export_progress_{nullptr};
  QPushButton * capture_toggle_button_{nullptr};
  QPushButton * clean_dataset_button_{nullptr};
  QPushButton * continue_dataset_button_{nullptr};
  QPushButton * convert_lerobot_button_{nullptr};
  QPushButton * language_instruction_button_{nullptr};
  QPushButton * idle_button_{nullptr};
  QPushButton * auto_button_{nullptr};
  QPushButton * api_button_{nullptr};
  QPushButton * teleop_button_{nullptr};
  QPushButton * hil_button_{nullptr};
  QPushButton * control_services_button_{nullptr};
  QPushButton * stop_control_services_button_{nullptr};
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
  QString capture_task_id_;
  QString capture_language_instruction_en_;
  QString capture_language_instruction_zh_;
  QString lerobot_export_profile_{QStringLiteral("act")};
  bool capture_running_{false};
  bool replay_mode_active_{false};
  bool replay_timeline_dragging_{false};
  bool cleaning_in_progress_{false};
  bool capture_stop_in_progress_{false};
  bool capture_annotation_in_progress_{false};
  bool lerobot_export_in_progress_{false};
  bool language_editor_request_in_progress_{false};
  bool capture_task_id_is_suggested_{false};
  bool continued_dataset_annotation_dirty_{false};
  bool capture_status_override_active_{false};
  bool services_owned_{false};
  bool mode_status_received_{false};
  bool dashboard_state_request_in_flight_{false};
  int owned_process_stop_attempts_{0};
  int lerobot_export_status_retry_count_{0};
  int capture_status_override_generation_{0};
  ControlServicesState control_services_state_{ControlServicesState::Stopped};
};

}  // namespace data_collection_rviz_panel
