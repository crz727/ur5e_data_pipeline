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
    capture_selector = main_window[main_window.index("capture_mode_->addItems"):
                                   main_window.index("capture_task_", main_window.index("capture_mode_->addItems"))]
    assert 'QStringLiteral("teleop")' in capture_selector
    assert 'QStringLiteral("http")' in capture_selector
    assert 'QStringLiteral("act")' in capture_selector
    assert 'QStringLiteral("vla")' in capture_selector
    assert 'QStringLiteral("policy")' not in capture_selector
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
    assert '{QStringLiteral("sample_rate_hz"), 15.0}' in main_window
    assert '{QStringLiteral("sampling_clock"), QStringLiteral("scene_camera_header")}' in main_window
    assert '{QStringLiteral("camera_sync_tolerance_s"), 0.02}' in main_window
    assert '{QStringLiteral("joint_state_sync_tolerance_s"), 0.02}' in main_window
    assert '{QStringLiteral("gripper_sync_tolerance_s"), 0.03}' in main_window
    assert '{QStringLiteral("target_fps"), 15.0}' in main_window
    assert '{QStringLiteral("max_sync_delta_s"), 0.02}' in main_window
    assert '{QStringLiteral("fps"), 15.0}' in main_window
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
    assert "LeRobot export already running" in main_window
    assert "while (QDir(output_parent).exists(suggested_output_name))" in main_window
    assert "output already exists; choose a new name" in main_window
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
    assert "mode_status_layout->addRow" in main_window
    assert "mode_box->setMinimumHeight(315);" in main_window
    assert 'operation_column->setObjectName(QStringLiteral("operation_column"));' in main_window
    assert "robot_health_value_" in main_window
    assert "scene_camera_health_value_" in main_window
    assert "wrist_camera_health_value_" in main_window
    assert "writer_health_value_" in main_window
    assert "set_health_chip" in main_window
    assert 'QStringLiteral("Replay Timeline")' in main_window
    assert "replay_timeline_box" in main_window
    assert "replay_timeline_box->setFixedHeight(72);" in main_window
    assert "root_layout->setSpacing(10);" in main_window
    assert "root_layout->addWidget(replay_timeline_box);" in main_window
    assert "auto * mode_status_layout = new QFormLayout(mode_status_frame);" in main_window
    assert "auto * mode_buttons_layout = new QGridLayout(mode_actions_frame);" in main_window
    assert "mode_buttons_layout->addWidget(mode_buttons[index].first, index / 2, index % 2);" in main_window
    assert 'mode_status_frame->setObjectName(QStringLiteral("mode_status_panel"));' in main_window
    assert 'mode_status_frame->setStyleSheet(QStringLiteral("QFrame#mode_status_panel' in main_window
    assert "right_sidebar->setFrameShape(QFrame::NoFrame);" in main_window
    assert 'right_sidebar->setObjectName(QStringLiteral("operation_sidebar"));' in main_window
    assert "right_sidebar->setStyleSheet" not in main_window
    assert "replace_history" in main_window
    assert "left_column = new QSplitter(Qt::Vertical, workspace)" in main_window
    assert "right_sidebar = new QScrollArea(workspace)" in main_window
    assert "workspace->addWidget(left_column);" in main_window
    assert "workspace->addWidget(right_sidebar);" in main_window
    assert "operation_layout->addWidget(telemetry_box);" in main_window
    assert "dialog_buttons->addWidget(success)" in main_window
    assert "dialog_buttons->addWidget(failure)" in main_window
    assert "dialog_buttons->addWidget(cancel)" in main_window
    assert "capture_annotation_in_progress_" in main_window
    assert "capture_annotation_in_progress_ = true;" in main_window
    assert "capture_annotation_in_progress_ = false;" in main_window
    assert "!capture_annotation_in_progress_" in main_window

    main_cpp = (PANEL_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "window.show();" in main_cpp
    assert "#include <QLockFile>" in main_cpp
    assert "QLockFile instance_lock" in main_cpp
    assert "instance_lock.tryLock" in main_cpp
    assert "background:#0b0c10" in main_cpp
    assert "QGroupBox" in main_cpp
    assert "QSlider::groove:horizontal" in main_cpp
    assert "#c8a44f" in main_cpp
    assert "QFileDialog QTreeView" in main_cpp
    assert "QFileDialog QListView" in main_cpp
    assert "QFileDialog QWidget { background:#0d0e12; color:#f3eee2; }" in main_cpp
    assert "QFileDialog QAbstractItemView::viewport" in main_cpp
    assert "QScrollArea#operation_sidebar" in main_cpp
    assert "#6f542b" in main_cpp
    assert 'QColor("#131419")' in main_window
    assert 'QColor("#f3eee2")' in main_window
    assert 'QColor("#c8a44f")' in main_window


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


def test_export_status_transport_failures_keep_workflow_guard_and_retry():
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(
        encoding="utf-8"
    )
    status_method = main_window.index("void MainWindow::request_lerobot_export_status()")
    status_method_end = main_window.index(
        "void MainWindow::request_replay_episodes()", status_method
    )
    status_source = main_window[status_method:status_method_end]
    transient_start = main_window.index(
        "if (!transport_ok || !document.isObject()) {", status_method
    )
    transient_end = main_window.index(
        "const QString status = response.value", transient_start
    )
    transient_branch = main_window[transient_start:transient_end]

    assert "lerobot_export_in_progress_ = false" not in transient_branch
    assert "QTimer::singleShot(1000" in transient_branch
    assert "request_lerobot_export_status" in transient_branch
    assert 'QStringLiteral("invalid backend response")' in transient_branch
    assert 'if (status == QStringLiteral("failed"))' in status_source
    assert status_source.count("lerobot_export_in_progress_ = false") == 2
    assert status_source.count("QTimer::singleShot(1000") == 2


def test_export_click_while_busy_reports_status_instead_of_silent_return():
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(
        encoding="utf-8"
    )
    request_method = main_window[main_window.index("void MainWindow::request_lerobot_export("):]
    busy_guard = request_method[:request_method.index("const QString normalized_profile")]

    assert "if (lerobot_export_in_progress_)" in busy_guard
    assert "show_temporary_capture_status" in busy_guard
    assert "LeRobot export already running" in busy_guard


def test_lerobot_export_uses_indeterminate_activity_indicator():
    header = (PANEL_ROOT / "include" / "data_collection_rviz_panel" / "main_window.hpp").read_text(
        encoding="utf-8"
    )
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(
        encoding="utf-8"
    )
    start_method = main_window[
        main_window.index("void MainWindow::start_lerobot_export("):
        main_window.index("void MainWindow::request_lerobot_export_status()")
    ]
    status_method = main_window[
        main_window.index("void MainWindow::request_lerobot_export_status()"):
        main_window.index("void MainWindow::request_replay_episodes()")
    ]

    assert "class QProgressBar;" in header
    assert "QProgressBar * lerobot_export_progress_" in header
    assert "void set_lerobot_export_activity(bool active);" in header
    assert "#include <QProgressBar>" in main_window
    assert "lerobot_export_progress_ = new QProgressBar(capture_box);" in main_window
    assert "void MainWindow::set_lerobot_export_activity(bool active)" in main_window
    assert "lerobot_export_progress_->setRange(0, 0);" in main_window
    assert "lerobot_export_progress_->hide();" in main_window
    assert "set_lerobot_export_activity(true);" in start_method
    assert "set_lerobot_export_activity(false);" in start_method
    assert status_method.count("set_lerobot_export_activity(false);") == 2


def test_panel_control_services_manage_only_owned_api_and_mode_manager():
    header = (PANEL_ROOT / "include" / "data_collection_rviz_panel" / "main_window.hpp").read_text(
        encoding="utf-8"
    )
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(
        encoding="utf-8"
    )

    assert "void start_control_services();" in header
    assert "void stop_control_services();" in header
    assert "qint64 control_api_pid_" in header
    assert "qint64 control_mode_manager_pid_" in header
    assert "QPushButton * control_services_button_" in header
    assert "void MainWindow::start_control_services()" in main_window
    assert "void MainWindow::stop_control_services()" in main_window
    assert 'QStringLiteral("Start control services")' in main_window
    assert 'QStringLiteral("Stop control services")' in main_window
    assert 'QStringLiteral("ur5e_http_api")' in main_window
    assert 'QStringLiteral("run_api")' in main_window
    assert 'QStringLiteral("ur5e_mode_manager")' in main_window
    assert 'QStringLiteral("mode_manager")' in main_window
    assert "QProcess::startDetached" in main_window

    stop_method = main_window[main_window.index("void MainWindow::stop_control_services()") :]
    lifecycle_source = main_window[main_window.index("void MainWindow::start_control_services()") :]
    assert 'request_mode(QStringLiteral("idle"))' in stop_method
    assert 'state == QStringLiteral("IDLE")' in main_window
    assert 'owner == QStringLiteral("none")' in main_window
    assert "services_owned_" in main_window

    for forbidden_command in (
        'QStringLiteral("ur_robot_driver")',
        'QStringLiteral("ur_control.launch.py")',
        'QStringLiteral("ros2_control")',
        'QStringLiteral("camera")',
        'QStringLiteral("gripper")',
        'QStringLiteral("run_autonomous.py")',
    ):
        assert forbidden_command not in lifecycle_source


def test_panel_can_resume_original_data_and_convert_selected_cleaned_data():
    main_window = (PANEL_ROOT / "src" / "main_window.cpp").read_text(encoding="utf-8")

    assert 'QStringLiteral("Continue Dataset...")' in main_window
    assert 'QStringLiteral("/api/capture/select-existing-dataset")' in main_window
    assert "void MainWindow::request_existing_dataset()" in main_window
    assert 'QStringLiteral("Convert LeRobot...")' in main_window
    assert "void MainWindow::request_standalone_lerobot_export()" in main_window
    assert 'QStringLiteral("LeRobot Profile")' in main_window
    assert 'QStringLiteral("cleaned")' in main_window
    assert "request_lerobot_export(dataset_dir, profile.toLower())" in main_window
