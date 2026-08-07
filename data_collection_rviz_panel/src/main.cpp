#include <QApplication>
#include <QLockFile>
#include <QMessageBox>

#include <rclcpp/rclcpp.hpp>

#include "data_collection_rviz_panel/main_window.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  QApplication application(argc, argv);
  application.setStyleSheet(QStringLiteral(R"(
    QMainWindow, QDialog { background:#0b0c10; color:#f3eee2; }
    QWidget { color:#f3eee2; }
    QWidget#console_root, QWidget#operation_column, QWidget#operation_sidebar_viewport { background:#0b0c10; }
    QScrollArea#operation_sidebar { border:0; background:#0b0c10; }
    QMenuBar { background:#0b0c10; border-bottom:1px solid #4a3a28; }
    QMenuBar::item { background:transparent; padding:6px 10px; }
    QMenuBar::item:selected, QMenu::item:selected { background:#4a1b29; color:#e4c778; }
    QMenu { background:#17151a; border:1px solid #c8a44f; }
    QGroupBox { margin-top:10px; padding:11px 8px 8px; border:1px solid #6f542b; border-radius:4px; background:#131419; font-weight:600; color:#e4c778; }
    QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; color:#e4c778; }
    QLabel { background:transparent; color:#f3eee2; }
    QPushButton { min-height:27px; padding:3px 10px; border:1px solid #8e713c; border-radius:3px; background:#351a24; color:#e4c778; font-weight:600; }
    QPushButton:hover { background:#632334; border-color:#e4c778; }
    QPushButton:pressed { background:#9c2a40; }
    QPushButton:disabled { background:#201d20; border-color:#403a35; color:#756e66; }
    QLineEdit, QComboBox, QDoubleSpinBox { min-height:26px; padding:2px 7px; border:1px solid #6f542b; border-radius:3px; background:#0d0e12; color:#f3eee2; selection-background-color:#811f32; }
    QComboBox::drop-down { width:20px; border-left:1px solid #6f542b; }
    QComboBox QAbstractItemView { background:#17151a; color:#f3eee2; border:1px solid #c8a44f; selection-background-color:#811f32; }
    QPlainTextEdit { border:1px solid #6f542b; background:#0d0e12; color:#ddd3c1; selection-background-color:#811f32; }
    QTabWidget::pane { border:1px solid #6f542b; background:#131419; }
    QTabBar::tab { padding:7px 11px; border:1px solid #6f542b; border-bottom:0; background:#17151a; color:#aaa49a; }
    QTabBar::tab:selected { background:#25191d; border-top:2px solid #c8a44f; color:#e4c778; }
    QScrollArea { border:0; background:#0b0c10; }
    QScrollBar:vertical { width:10px; background:#0b0c10; margin:0; }
    QScrollBar::handle:vertical { min-height:30px; border-radius:4px; background:#6d2635; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
    QFileDialog { background:#0b0c10; color:#f3eee2; }
    QFileDialog QWidget { background:#0d0e12; color:#f3eee2; }
    QFileDialog QPushButton { min-height:27px; padding:3px 10px; border:1px solid #8e713c; border-radius:3px; background:#351a24; color:#e4c778; font-weight:600; }
    QFileDialog QLineEdit { min-height:26px; padding:2px 7px; border:1px solid #4d4444; border-radius:3px; background:#0d0e12; color:#f3eee2; }
    QFileDialog QTreeView, QFileDialog QListView, QFileDialog QTableView { background:#0d0e12; color:#f3eee2; alternate-background-color:#17151a; border:1px solid #44392f; }
    QFileDialog QAbstractItemView::viewport { background:#0d0e12; }
    QFileDialog QAbstractScrollArea::corner { background:#0d0e12; }
    QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected { background:#811f32; color:#fff4df; }
    QFileDialog QHeaderView::section { padding:4px; background:#17151a; color:#e4c778; border:0; border-right:1px solid #44392f; border-bottom:1px solid #44392f; }
    QFileDialog QSidebar { background:#131419; color:#f3eee2; border-right:1px solid #44392f; }
    QSlider::groove:horizontal { height:6px; border-radius:3px; background:#2b2528; }
    QSlider::sub-page:horizontal { border-radius:3px; background:#811f32; }
    QSlider::handle:horizontal { width:14px; margin:-5px 0; border:2px solid #e4c778; border-radius:7px; background:#c8a44f; }
    QSplitter::handle { background:#44392f; }
    QToolTip { border:1px solid #c8a44f; background:#17151a; color:#f3eee2; }
  )"));
  QLockFile instance_lock(QStringLiteral("/tmp/data_collection_rviz_panel.lock"));
  instance_lock.setStaleLockTime(0);
  if (!instance_lock.tryLock(100)) {
    QMessageBox::information(
      nullptr,
      QStringLiteral("UR5e Data Collection Console"),
      QStringLiteral("The data collection console is already running."));
    rclcpp::shutdown();
    return 0;
  }
  {
    data_collection_rviz_panel::MainWindow window;
    window.show();
    application.exec();
  }
  rclcpp::shutdown();
  return 0;
}
