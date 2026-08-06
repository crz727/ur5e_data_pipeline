#include <QApplication>
#include <QLockFile>
#include <QMessageBox>

#include <rclcpp/rclcpp.hpp>

#include "data_collection_rviz_panel/main_window.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  QApplication application(argc, argv);
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
