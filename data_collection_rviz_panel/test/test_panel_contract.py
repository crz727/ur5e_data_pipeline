from pathlib import Path


PANEL_ROOT = Path(__file__).resolve().parents[1]


def test_panel_package_declares_rviz_qt_executable_and_live_topic_defaults():
    package_xml = (PANEL_ROOT / "package.xml").read_text(encoding="utf-8")
    cmake_lists = (PANEL_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(
        encoding="utf-8"
    )

    assert "<build_type>ament_cmake</build_type>" in package_xml
    assert "rviz_common" in package_xml
    assert "add_executable(data_collection_rviz_panel" in cmake_lists
    assert '"/camera2/scene_camera/color/image_raw/compressed"' in main_window
    assert '"/camera1/wrist_camera/color/image_raw/compressed"' in main_window
    assert '"/control_mode/request"' in main_window
    assert '"/control_mode/status"' in main_window
    assert '"/data_collection/replay/joint_states"' in main_window
    assert '"/data_collection/robot_model/joint_states"' in main_window
    assert '"/robotiq_2f_gripper/joint_states"' in main_window
    assert 'QStringLiteral("replay")' in main_window
    assert "QTimer::singleShot(0, this, &MainWindow::initialize_rviz)" in main_window
    assert "rviz_common::VisualizationFrame" in main_window
    assert 'createDisplay(QStringLiteral("rviz_default_plugins/TF")' not in main_window
    assert 'QStringLiteral("Replay RobotModel"), false)' in main_window
    assert "live_model_->setEnabled(!replay_mode)" in main_window
    assert "replay_model_->setEnabled(replay_mode)" in main_window
    assert "executor_->add_node(rviz_node_->get_raw_node())" not in main_window
    assert "findChildren<QDockWidget *>" in main_window
    assert "rviz_frame_->menuBar()->hide()" in main_window
    assert 'live_description_topic->setValue(QStringLiteral("/robot_description"))' in main_window
    assert "visual_layout->addWidget(rviz_box, 7)" in main_window
    assert "visual_layout->addWidget(camera_box, 3)" in main_window
    assert "capture_status_value_" in main_window
    assert "capture_toggle_button_" in main_window
    assert 'QStringLiteral("Start Capture")' in main_window
    assert 'QStringLiteral("Stop Capture")' in main_window
    assert 'QStringLiteral("/api/capture/annotate")' in main_window
    assert "clean_dataset_button_" in main_window
    assert 'QStringLiteral("Clean Data")' in main_window
    assert 'QStringLiteral("/api/capture/clean")' in main_window
    assert "Cleaning will read original data" in main_window
    assert "clean_dialog_buttons->addWidget(clean_yes)" in main_window
    assert "clean_dialog_buttons->addWidget(clean_no)" in main_window
    assert 'QStringLiteral("Open Report")' in main_window
    assert "QDesktopServices::openUrl" in main_window
    assert 'QStringLiteral("Language Instruction")' in main_window
    assert 'QStringLiteral("English instruction")' in main_window
    assert 'QStringLiteral("中文指令")' in main_window
    assert 'QStringLiteral("Export ACT")' in main_window
    assert 'QStringLiteral("Export VLA")' in main_window
    assert 'QStringLiteral("Export LeRobot")' not in main_window
    assert 'QStringLiteral("/api/capture/task-labels")' in main_window
    assert 'QStringLiteral("/api/capture/export-lerobot/preflight")' in main_window
    assert 'QStringLiteral("/api/capture/export-lerobot")' in main_window
    assert 'QStringLiteral("profile")' in main_window
    assert 'path == QStringLiteral("/api/capture/start")' in main_window
    assert 'QStringLiteral("Capture could not start: %1")' in main_window
    assert "connect(dialog, &QFileDialog::rejected" in main_window
    assert "show_temporary_capture_status" in main_window
    assert "language_editor_request_in_progress_" in main_window
    assert "if (capture_running_ || language_editor_request_in_progress_)" in main_window
    assert "QMessageBox" in main_window
    assert "#include <QDialog>" in main_window
    assert "auto * result_dialog = new QDialog(this);" in main_window
    assert "result_dialog->setModal(false);" in main_window
    assert "connect(close_result, &QPushButton::clicked, result_dialog, &QDialog::close);" in main_window
    assert "start_capture" not in main_window
    assert "stop_capture" not in main_window
    assert "drop_reason_preview_" not in main_window
    assert "showFullScreen" in main_window
    assert "showNormal" in main_window
    assert "QScrollArea" in main_window
    assert "Qt::ScrollBarAlwaysOn" in main_window
    assert "workspace->setStretchFactor(0, 12)" in main_window
    assert "workspace->setStretchFactor(1, 8)" in main_window
    assert "shared_value_range" in main_window
    assert "set_scale" not in main_window
    assert "robot_model_joint_state_publisher_" in main_window
    assert "gripper_joint_state_subscription_" in main_window
    assert 'replay_state.name.push_back("finger_joint")' in main_window
    assert "QFileDialog::getExistingDirectory" not in main_window
    assert "QFileDialog::DontUseNativeDialog" in main_window
    assert "dialog->open();" in main_window
    assert 'QStringLiteral("/api/capture/export-lerobot/status")' in main_window
    assert "lerobot_export_in_progress_" in main_window
    assert "&QLineEdit::editingFinished" in main_window
    assert "replay_status_value_" in main_window
    assert "root_scroll" not in main_window
    assert "right_sidebar->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn)" in main_window
    assert "left_column = new QSplitter(Qt::Vertical, workspace)" in main_window
    assert "Replay pose blocked: recording has no joint_names" in main_window
    assert "panel->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn)" in main_window
    assert "set_text_preserving_scroll" in main_window
    assert "replay_timestamp_ = -1.0" in main_window
    assert "published_frames" in main_window
    assert "last_replay_status_name_" in main_window
    assert "joint_names_" in main_window
    assert "shoulder_pan_joint" in main_window
    assert "void append(double timestamp, const std::vector<double> & values)" in main_window
    assert "void clear()" in main_window
    assert "void mouseMoveEvent(QMouseEvent * event) override" in main_window
    assert "void leaveEvent(QEvent *) override" in main_window
    assert 'QStringLiteral("time (s)")' in main_window
    assert "nearest_sample_index" in main_window
    assert "hovered_sample_index_" in main_window
    assert "qpos_chart_->clear();" in main_window
    assert "qvel_chart_->clear();" in main_window
    assert "effort_chart_->clear();" in main_window
    assert "shared_value_range" in main_window
    assert "value_to_y" in main_window
    assert "painter.drawText(y_tick" in main_window
    assert 'QStringLiteral("rad/s")' in main_window
    assert "QSlider" in main_window
    assert 'QStringLiteral("/api/replay/seek")' in main_window
    assert "replay_timeline_" in main_window
    assert "replay_timeline_dragging_" in main_window
    assert main_window.count("new QSlider(Qt::Horizontal") == 1
    assert "mode_layout->addWidget(mode_buttons[index].first, 5 + index, 0, 1, 2);" in main_window
    assert "mode_layout->setRowMinimumHeight(row, 20);" in main_window
    assert "mode_layout->setRowMinimumHeight(row, 30);" in main_window
    assert "mode_box->setMinimumHeight(300);" in main_window
    assert "robot_health_value_" in main_window
    assert "scene_camera_health_value_" in main_window
    assert "wrist_camera_health_value_" in main_window
    assert "writer_health_value_" in main_window
    assert "set_health_chip" in main_window
    assert 'QStringLiteral("Replay Timeline")' in main_window
    assert "replay_timeline_box" in main_window
    assert "root_layout->addWidget(replay_timeline_box);" in main_window
    assert "replace_history" in main_window
    assert "left_column = new QSplitter(Qt::Vertical, workspace)" in main_window
    assert "right_sidebar = new QScrollArea(workspace)" in main_window
    assert "workspace->addWidget(left_column);" in main_window
    assert "workspace->addWidget(right_sidebar);" in main_window
    assert "operation_layout->addWidget(telemetry_box);" in main_window
    assert "dialog_buttons->addWidget(success)" in main_window
    assert "dialog_buttons->addWidget(failure)" in main_window
    assert "dialog_buttons->addWidget(cancel)" in main_window

    main_cpp = (PANEL_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "window.show();" in main_cpp
    assert "#include <QLockFile>" in main_cpp
    assert "QLockFile instance_lock" in main_cpp
    assert "instance_lock.tryLock" in main_cpp


def test_panel_launch_wires_safe_replay_tf_without_hardware_control():
    launch_file = PANEL_ROOT / "launch" / "data_collection_rviz_panel.launch.py"
    launch_text = launch_file.read_text(encoding="utf-8")

    assert "data_collection_monitor.launch.py" in launch_text
    assert '"/data_collection/replay/joint_states"' in launch_text
    assert '"/replay/robot_description"' in launch_text
    assert '"frame_prefix": "replay/"' in launch_text
    assert '"data_collection_replay_world_transform"' in launch_text
    assert '"data_collection_rviz_panel"' in launch_text
    assert 'DeclareLaunchArgument("start_live_state_publisher", default_value="true")' in launch_text
    assert '"data_collection_live_state_publisher"' in launch_text
    assert '"robot_description": live_description' in launch_text
    assert '("joint_states", "/data_collection/robot_model/joint_states")' in launch_text
    assert "ur5e_driver" not in launch_text
