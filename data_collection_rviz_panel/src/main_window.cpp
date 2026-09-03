#include "data_collection_rviz_panel/main_window.hpp"

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cmath>
#include <functional>
#include <limits>
#include <spawn.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include <QByteArray>
#include <QApplication>
#include <QComboBox>
#include <QDesktopServices>
#include <QDialog>
#include <QDir>
#include <QDockWidget>
#include <QDoubleSpinBox>
#include <QEvent>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QFrame>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QImage>
#include <QInputDialog>
#include <QAction>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPainter>
#include <QPainterPath>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QKeySequence>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QMouseEvent>
#include <QRegularExpression>
#include <QScrollArea>
#include <QScrollBar>
#include <QSignalBlocker>
#include <QSlider>
#include <QSplitter>
#include <QStringList>
#include <QStatusBar>
#include <QTabWidget>
#include <QTimer>
#include <QToolBar>
#include <QUrl>
#include <QUrlQuery>
#include <QVBoxLayout>

#include <rviz_common/display.hpp>
#include <rviz_common/properties/property.hpp>
#include <rviz_common/visualization_manager.hpp>
#include <rviz_common/visualization_frame.hpp>
#include <rviz_rendering/render_system.hpp>

namespace data_collection_rviz_panel
{
namespace
{
constexpr char kDashboardUrl[] = "http://127.0.0.1:8765";
constexpr char kExternalCameraTopic[] = "/camera2/scene_camera/color/image_raw/compressed";
constexpr char kWristCameraTopic[] = "/camera1/wrist_camera/color/image_raw/compressed";
constexpr char kJointStateTopic[] = "/joint_states";
constexpr char kGripperJointStateTopic[] = "/robotiq_2f_gripper/joint_states";
constexpr char kRobotModelJointStateTopic[] = "/data_collection/robot_model/joint_states";
constexpr char kModeRequestTopic[] = "/control_mode/request";
constexpr char kModeTopic[] = "/control_mode";
constexpr char kModeStatusTopic[] = "/control_mode/status";
constexpr char kReplayJointStateTopic[] = "/data_collection/replay/joint_states";
constexpr char kControlApiHealthUrl[] = "http://127.0.0.1:5000/api/health";
constexpr int kMaxLerobotExportStatusRetries = 5;

bool process_is_running(qint64 pid)
{
  if (pid <= 0) {
    return false;
  }
  // Reap the direct child when it exits; otherwise a stopped service remains a zombie
  // and kill(pid, 0) would incorrectly keep the Qt lifecycle state alive.
  (void)::waitpid(static_cast<pid_t>(pid), nullptr, WNOHANG);
  if (::kill(-static_cast<pid_t>(pid), 0) == 0 || errno == EPERM) {
    return true;
  }
  if (::kill(static_cast<pid_t>(pid), 0) == 0) {
    return true;
  }
  return errno == EPERM;
}

qint64 start_owned_process(const QString & program, const QStringList & arguments)
{
  std::vector<QByteArray> encoded;
  encoded.reserve(static_cast<std::size_t>(arguments.size()) + 1U);
  encoded.push_back(program.toLocal8Bit());
  for (const QString & argument : arguments) {
    encoded.push_back(argument.toLocal8Bit());
  }
  std::vector<char *> argv;
  argv.reserve(encoded.size() + 1U);
  for (QByteArray & value : encoded) {
    argv.push_back(value.data());
  }
  argv.push_back(nullptr);

  posix_spawnattr_t attributes;
  if (::posix_spawnattr_init(&attributes) != 0) {
    return 0;
  }
  const short flags = POSIX_SPAWN_SETSID;
  if (::posix_spawnattr_setflags(&attributes, flags) != 0) {
    ::posix_spawnattr_destroy(&attributes);
    return 0;
  }
  pid_t child = 0;
  const int result = ::posix_spawnp(
    &child, argv[0], nullptr, &attributes, argv.data(), environ);
  ::posix_spawnattr_destroy(&attributes);
  return result == 0 ? static_cast<qint64>(child) : 0;
}

struct ResidualControlServices
{
  qint64 mode_manager_pid{0};
  qint64 http_api_pid{0};

  bool empty() const
  {
    return mode_manager_pid <= 0 && http_api_pid <= 0;
  }
};

bool has_executable_argument(const QList<QByteArray> & arguments, const QByteArray & executable)
{
  for (const QByteArray & argument : arguments) {
    if (argument == executable || argument.endsWith(QByteArrayLiteral("/") + executable)) {
      return true;
    }
  }
  return false;
}

ResidualControlServices find_residual_control_services()
{
  ResidualControlServices residual;
  const QDir proc(QStringLiteral("/proc"));
  const uint current_uid = static_cast<uint>(::geteuid());
  for (const QString & entry : proc.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
    bool valid_pid = false;
    const qint64 pid = entry.toLongLong(&valid_pid);
    if (!valid_pid || pid <= 0 || QFileInfo(proc.filePath(entry)).ownerId() != current_uid) {
      continue;
    }
    QFile command_file(proc.filePath(entry + QStringLiteral("/cmdline")));
    if (!command_file.open(QIODevice::ReadOnly)) {
      continue;
    }
    const QByteArray command_line = command_file.readAll();
    const QList<QByteArray> arguments = command_line.split('\0');
    if (residual.mode_manager_pid == 0 &&
      command_line.contains(QByteArrayLiteral("ur5e_mode_manager")) &&
      has_executable_argument(arguments, QByteArrayLiteral("mode_manager")))
    {
      residual.mode_manager_pid = pid;
    }
    if (residual.http_api_pid == 0 &&
      command_line.contains(QByteArrayLiteral("ur5e_http_api")) &&
      has_executable_argument(arguments, QByteArrayLiteral("run_api")))
    {
      residual.http_api_pid = pid;
    }
  }
  return residual;
}

void request_process_stop(qint64 pid, int signal = SIGINT)
{
  if (pid > 0 && process_is_running(pid)) {
    if (::kill(-static_cast<pid_t>(pid), signal) != 0 && errno == ESRCH) {
      ::kill(static_cast<pid_t>(pid), signal);
    }
  }
}

void stop_process_synchronously(qint64 pid)
{
  if (pid <= 0) {
    return;
  }
  const auto wait_for_exit = [pid](int attempts) {
      for (int attempt = 0; attempt < attempts; ++attempt) {
        if (!process_is_running(pid)) {
          return true;
        }
        ::usleep(20'000);
      }
      return !process_is_running(pid);
    };

  request_process_stop(pid, SIGINT);
  if (wait_for_exit(50)) {
    return;
  }
  request_process_stop(pid, SIGTERM);
  if (wait_for_exit(50)) {
    return;
  }
  request_process_stop(pid, SIGKILL);
  (void)wait_for_exit(25);
  (void)::waitpid(static_cast<pid_t>(pid), nullptr, WNOHANG);
}

QString pretty_json(const QJsonValue & value)
{
  if (value.isUndefined() || value.isNull()) {
    return QStringLiteral("No message");
  }
  if (value.isObject()) {
    return QString::fromUtf8(QJsonDocument(value.toObject()).toJson(QJsonDocument::Indented));
  }
  if (value.isArray()) {
    return QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Indented));
  }
  return value.toVariant().toString();
}

std::vector<double> json_numbers(const QJsonValue & value)
{
  std::vector<double> values;
  for (const QJsonValue & item : value.toArray()) {
    values.push_back(item.toDouble());
  }
  return values;
}

std::vector<std::string> replay_joint_names(const QJsonArray & names)
{
  std::vector<std::string> result;
  for (const QJsonValue & name : names) {
    result.push_back(name.toString().toStdString());
  }
  return result;
}

}  // namespace

class TelemetryChart final : public QWidget
{
public:
  explicit TelemetryChart(const QString & title, QWidget * parent = nullptr)
  : QWidget(parent), title_(title)
  {
    setMinimumHeight(130);
    setMouseTracking(true);
    joint_names_ = {
      QStringLiteral("shoulder_pan_joint"), QStringLiteral("shoulder_lift_joint"),
      QStringLiteral("elbow_joint"), QStringLiteral("wrist_1_joint"),
      QStringLiteral("wrist_2_joint"), QStringLiteral("wrist_3_joint")};
  }

  void set_joint_names(const std::vector<std::string> & names)
  {
    if (names.empty()) {
      return;
    }
    joint_names_.clear();
    for (const auto & name : names) {
      joint_names_.push_back(QString::fromStdString(name));
    }
    update();
  }

  void append(double timestamp, const std::vector<double> & values)
  {
    if (!std::isfinite(timestamp)) {
      timestamp = samples_.empty() ? 0.0 : samples_.back().timestamp + 1.0;
    }
    if (!samples_.empty()) {
      timestamp = std::max(timestamp, samples_.back().timestamp);
    }
    samples_.push_back({timestamp, QVector<double>(values.begin(), values.end())});
    if (samples_.size() > 300) {
      samples_.remove(0, samples_.size() - 300);
    }
    if (hover_active_) {
      update_hovered_sample(hover_position_);
    }
    update();
  }

  void replace_history(const QJsonArray & history, const QString & field)
  {
    QVector<Sample> replacement;
    replacement.reserve(history.size());
    for (const QJsonValue & entry : history) {
      const QJsonObject sample = entry.toObject();
      const QJsonValue timestamp_value = sample.value(QStringLiteral("timestamp"));
      const QJsonArray values_json = sample.value(field).toArray();
      if (!timestamp_value.isDouble() || values_json.isEmpty()) {
        continue;
      }

      const double timestamp = timestamp_value.toDouble();
      if (!std::isfinite(timestamp)) {
        continue;
      }
      QVector<double> values;
      values.reserve(values_json.size());
      bool numeric_values = true;
      for (const QJsonValue & value : values_json) {
        if (!value.isDouble() || !std::isfinite(value.toDouble())) {
          numeric_values = false;
          break;
        }
        values.push_back(value.toDouble());
      }
      if (numeric_values) {
        replacement.push_back({timestamp, values});
      }
    }

    std::sort(replacement.begin(), replacement.end(),
      [](const Sample & left, const Sample & right) {
        return left.timestamp < right.timestamp;
      });
    if (replacement.size() > 300) {
      replacement.remove(0, replacement.size() - 300);
    }
    samples_ = std::move(replacement);
    hover_active_ = false;
    hovered_sample_index_ = -1;
    update();
  }

  void clear()
  {
    samples_.clear();
    hover_active_ = false;
    hovered_sample_index_ = -1;
    update();
  }

protected:
  void paintEvent(QPaintEvent *) override
  {
    QPainter painter(this);
    painter.fillRect(rect(), QColor("#131419"));
    painter.setPen(QColor("#f3eee2"));
    painter.drawText(10, 18, title_);
    if (samples_.empty()) {
      painter.setPen(QColor("#aaa49a"));
      painter.drawText(rect(), Qt::AlignCenter, QStringLiteral("waiting for joint state"));
      return;
    }

    const int joint_count = visible_joint_count();
    const QVector<QColor> & colors = curve_colors();
    int legend_x = 10;
    int legend_y = 34;
    const QFontMetrics metrics(painter.font());
    for (int joint = 0; joint < joint_count; ++joint) {
      const QString label = joint < joint_names_.size() ? joint_names_[joint] :
        QStringLiteral("joint_%1").arg(joint + 1);
      const int item_width = metrics.horizontalAdvance(label) + 25;
      if (legend_x > 10 && legend_x + item_width > width() - 10) {
        legend_x = 10;
        legend_y += 16;
      }
      painter.setPen(QPen(colors[joint], 2.0));
      painter.drawLine(legend_x, legend_y - 4, legend_x + 10, legend_y - 4);
      painter.setPen(colors[joint]);
      painter.drawText(legend_x + 14, legend_y, label);
      legend_x += item_width;
    }
    const QRect plot = plot_rect(joint_count);
    const QPair<double, double> range = shared_value_range(joint_count);
    const double minimum = range.first;
    const double maximum = range.second;
    painter.setPen(QColor("#343038"));
    for (int tick = 0; tick < 3; ++tick) {
      const double ratio = static_cast<double>(tick) / 2.0;
      const int y = static_cast<int>(std::lround(plot.top() + ratio * plot.height()));
      const double value = maximum - ratio * (maximum - minimum);
      const QRect y_tick(2, y - 8, plot.left() - 6, 16);
      painter.drawLine(plot.left(), y, plot.right(), y);
      painter.setPen(QColor("#aaa49a"));
      painter.drawText(y_tick, Qt::AlignRight | Qt::AlignVCenter,
        QString::number(value, 'f', 3));
      painter.setPen(QColor("#343038"));
    }
    for (int joint = 0; joint < joint_count; ++joint) {
      painter.setPen(QPen(colors[joint], 1.8));
      QPainterPath path;
      for (int index = 0; index < samples_.size(); ++index) {
        const double value = joint < samples_[index].values.size() ? samples_[index].values[joint] : 0.0;
        const double x = sample_x(index, plot);
        const double y = value_to_y(value, minimum, maximum, plot);
        if (index == 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
      }
      painter.drawPath(path);
    }

    const double elapsed = displayed_duration();
    const QRect axis_rect(plot.left(), plot.bottom() + 2, plot.width(), kAxisHeight - 2);
    painter.setPen(QColor("#aaa49a"));
    painter.drawLine(plot.left(), plot.bottom(), plot.right(), plot.bottom());
    painter.drawText(axis_rect, Qt::AlignCenter, QStringLiteral("time (s)"));
    painter.drawText(axis_rect, Qt::AlignLeft | Qt::AlignVCenter, QStringLiteral("0.00"));
    painter.drawText(axis_rect, Qt::AlignRight | Qt::AlignVCenter,
      QString::number(elapsed, 'f', 2));

    if (hover_active_ && hovered_sample_index_ >= 0 && hovered_sample_index_ < samples_.size()) {
      const double cursor_x = sample_x(hovered_sample_index_, plot);
      painter.setPen(QPen(QColor("#c8a44f"), 1.0, Qt::DashLine));
      painter.drawLine(QPointF(cursor_x, plot.top()), QPointF(cursor_x, plot.bottom()));
      draw_hover_overlay(painter, plot, joint_count, colors);
    }
  }

  void mouseMoveEvent(QMouseEvent * event) override
  {
    hover_position_ = event->pos();
    update_hovered_sample(hover_position_);
    update();
    QWidget::mouseMoveEvent(event);
  }

  void leaveEvent(QEvent *) override
  {
    hover_active_ = false;
    hovered_sample_index_ = -1;
    update();
  }

private:
  struct Sample
  {
    double timestamp{0.0};
    QVector<double> values;
  };

  static constexpr int kAxisHeight = 22;

  const QVector<QColor> & curve_colors() const
  {
    static const QVector<QColor> colors = {
      QColor("#c8a44f"), QColor("#d45264"), QColor("#f3eee2"),
      QColor("#9c5f68"), QColor("#e4c778"), QColor("#7d5560")};
    return colors;
  }

  int visible_joint_count() const
  {
    return samples_.empty() ? 0 : std::min(6, samples_.back().values.size());
  }

  int legend_bottom(int joint_count) const
  {
    int legend_x = 10;
    int legend_y = 34;
    const QFontMetrics metrics(font());
    for (int joint = 0; joint < joint_count; ++joint) {
      const QString label = joint < joint_names_.size() ? joint_names_[joint] :
        QStringLiteral("joint_%1").arg(joint + 1);
      const int item_width = metrics.horizontalAdvance(label) + 25;
      if (legend_x > 10 && legend_x + item_width > width() - 10) {
        legend_x = 10;
        legend_y += 16;
      }
      legend_x += item_width;
    }
    return legend_y;
  }

  QRect plot_rect(int joint_count) const
  {
    const int plot_top = legend_bottom(joint_count) + 8;
    return QRect(54, plot_top, std::max(1, width() - 62),
      std::max(1, height() - plot_top - kAxisHeight - 8));
  }

  QPair<double, double> shared_value_range(int joint_count) const
  {
    double minimum = std::numeric_limits<double>::max();
    double maximum = std::numeric_limits<double>::lowest();
    for (const Sample & sample : samples_) {
      for (int joint = 0; joint < joint_count; ++joint) {
        const double value = joint < sample.values.size() ? sample.values[joint] : 0.0;
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
      }
    }
    const double minimum_span = title_.contains(QStringLiteral("Velocity")) ? 0.10 :
      (title_.contains(QStringLiteral("Effort")) ? 2.0 : 0.30);
    const double center = (minimum + maximum) * 0.5;
    const double span = std::max(maximum - minimum, minimum_span);
    const double half_span = span * 0.55;
    return {center - half_span, center + half_span};
  }

  double value_to_y(double value, double minimum, double maximum, const QRect & plot) const
  {
    const double ratio = std::clamp(
      (value - minimum) / std::max(maximum - minimum, std::numeric_limits<double>::epsilon()),
      0.0, 1.0);
    return plot.bottom() - ratio * plot.height();
  }

  double displayed_duration() const
  {
    return samples_.size() < 2 ? 0.0 :
      std::max(0.0, samples_.back().timestamp - samples_.front().timestamp);
  }

  double sample_x(int index, const QRect & plot) const
  {
    const double duration = displayed_duration();
    const double ratio = duration > std::numeric_limits<double>::epsilon() ?
      (samples_[index].timestamp - samples_.front().timestamp) / duration :
      (samples_.size() == 1 ? 0.5 : static_cast<double>(index) / (samples_.size() - 1));
    return plot.left() + std::clamp(ratio, 0.0, 1.0) * plot.width();
  }

  int nearest_sample_index(double timestamp) const
  {
    int nearest = 0;
    double nearest_distance = std::numeric_limits<double>::max();
    for (int index = 0; index < samples_.size(); ++index) {
      const double distance = std::abs(samples_[index].timestamp - timestamp);
      if (distance < nearest_distance) {
        nearest = index;
        nearest_distance = distance;
      }
    }
    return nearest;
  }

  void update_hovered_sample(const QPoint & point)
  {
    if (samples_.empty()) {
      hover_active_ = false;
      hovered_sample_index_ = -1;
      return;
    }
    const QRect plot = plot_rect(visible_joint_count());
    if (!plot.contains(point)) {
      hover_active_ = false;
      hovered_sample_index_ = -1;
      return;
    }
    hover_active_ = true;
    const double duration = displayed_duration();
    if (duration <= std::numeric_limits<double>::epsilon()) {
      const double ratio = static_cast<double>(point.x() - plot.left()) / std::max(1, plot.width());
      hovered_sample_index_ = std::clamp(
        static_cast<int>(std::lround(ratio * (samples_.size() - 1))), 0, samples_.size() - 1);
      return;
    }
    const double ratio = std::clamp(
      static_cast<double>(point.x() - plot.left()) / std::max(1, plot.width()), 0.0, 1.0);
    hovered_sample_index_ = nearest_sample_index(
      samples_.front().timestamp + ratio * duration);
  }

  QString value_unit() const
  {
    if (title_.contains(QStringLiteral("Velocity"))) {
      return QStringLiteral("rad/s");
    }
    if (title_.contains(QStringLiteral("Effort"))) {
      return QStringLiteral("driver");
    }
    return QStringLiteral("rad");
  }

  void draw_hover_overlay(
    QPainter & painter, const QRect & plot, int joint_count, const QVector<QColor> & colors) const
  {
    const Sample & sample = samples_[hovered_sample_index_];
    const int info_height = 24 + joint_count * 15;
    const int info_width = std::min(std::max(220, width() / 2), std::max(220, width() - 12));
    const int info_x = std::max(6, width() - info_width - 6);
    const int info_y = std::clamp(plot.bottom() - info_height, 2, std::max(2, height() - info_height - 2));
    const QRect info_rect(info_x, info_y, info_width, info_height);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor("#1a1b21"));
    painter.drawRoundedRect(info_rect, 4, 4);
    painter.setPen(QColor("#f3eee2"));
    painter.drawText(info_rect.adjusted(6, 3, -6, -3), Qt::AlignTop | Qt::AlignLeft,
      QStringLiteral("t = %1 s").arg(sample.timestamp - samples_.front().timestamp, 0, 'f', 3));
    const QFontMetrics metrics(painter.font());
    for (int joint = 0; joint < joint_count; ++joint) {
      const QString name = joint < joint_names_.size() ? joint_names_[joint] :
        QStringLiteral("joint_%1").arg(joint + 1);
      const double value = joint < sample.values.size() ? sample.values[joint] : 0.0;
      const QRect row(info_rect.left() + 6, info_rect.top() + 20 + joint * 15,
        info_rect.width() - 12, 15);
      painter.setPen(colors[joint]);
      painter.drawLine(row.left(), row.center().y(), row.left() + 8, row.center().y());
      painter.setPen(QColor("#f3eee2"));
      painter.drawText(row.adjusted(12, 0, -75, 0), Qt::AlignVCenter | Qt::AlignLeft,
        metrics.elidedText(name, Qt::ElideRight, row.width() - 95));
      painter.drawText(row, Qt::AlignVCenter | Qt::AlignRight,
        QStringLiteral("%1 %2").arg(value, 0, 'f', 4).arg(value_unit()));
    }
  }

  QString title_;
  QVector<Sample> samples_;
  QVector<QString> joint_names_;
  QPoint hover_position_;
  int hovered_sample_index_{-1};
  bool hover_active_{false};
};

namespace
{

QLabel * make_value_label(const QString & value = QStringLiteral("waiting"))
{
  auto * label = new QLabel(value);
  label->setWordWrap(true);
  return label;
}

void configure_network_request(QNetworkRequest & request, int timeout_ms)
{
  request.setTransferTimeout(timeout_ms);
}

QLabel * make_health_label()
{
  auto * label = new QLabel;
  label->setMinimumWidth(118);
  label->setAlignment(Qt::AlignCenter);
  return label;
}

void set_health_chip(
  QLabel * label, const QString & name, bool healthy, bool stale, const QString & detail)
{
  const QString color = !healthy ? QStringLiteral("#e15b66") :
    (stale ? QStringLiteral("#e4c778") : QStringLiteral("#74c79b"));
  const QString background = !healthy ? QStringLiteral("#2a151b") :
    (stale ? QStringLiteral("#2a2417") : QStringLiteral("#132219"));
  label->setText(QStringLiteral("%1: %2").arg(name, detail));
  label->setStyleSheet(QStringLiteral(
    "border:1px solid %1; border-radius:8px; padding:4px 7px; color:%1; background:%2;")
      .arg(color, background));
}

QPlainTextEdit * make_text_panel()
{
  auto * panel = new QPlainTextEdit;
  panel->setReadOnly(true);
  panel->setMinimumHeight(160);
  panel->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn);
  panel->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
  return panel;
}

void set_text_preserving_scroll(QPlainTextEdit * panel, const QString & text)
{
  if (panel->toPlainText() == text) {
    return;
  }
  auto * scroll_bar = panel->verticalScrollBar();
  const int previous_value = scroll_bar->value();
  const bool was_at_bottom = previous_value >= scroll_bar->maximum();
  panel->setPlainText(text);
  scroll_bar->setValue(was_at_bottom ? scroll_bar->maximum() :
    std::min(previous_value, scroll_bar->maximum()));
}

QString suggest_task_id(const QString & english_instruction)
{
  QStringList tokens;
  const QRegularExpression token_pattern(QStringLiteral("[a-z0-9]+"));
  auto matches = token_pattern.globalMatch(english_instruction.toLower());
  while (matches.hasNext()) {
    tokens.push_back(matches.next().captured());
  }
  return tokens.join(QLatin1Char('-'));
}

}  // namespace

MainWindow::MainWindow(QWidget * parent)
: QMainWindow(parent)
{
  setWindowTitle(QStringLiteral("UR5e Data Collection Console"));
  resize(1500, 920);
  setMinimumSize(1200, 760);
  build_ui();
  initialize_ros();
  QTimer::singleShot(0, this, &MainWindow::initialize_rviz);

  control_services_timeout_timer_ = new QTimer(this);
  control_services_timeout_timer_->setSingleShot(true);
  connect(control_services_timeout_timer_, &QTimer::timeout, this,
    &MainWindow::handle_control_services_timeout);
  mode_status_stale_timer_ = new QTimer(this);
  mode_status_stale_timer_->setSingleShot(true);
  connect(mode_status_stale_timer_, &QTimer::timeout, this, [this]() {
    mode_status_received_ = false;
    set_mode_buttons_enabled(true);
    if (control_services_state_ == ControlServicesState::Stopped) {
      control_services_status_value_->setText(QStringLiteral("Mode Manager status unavailable"));
    }
    update_control_services_button();
  });
  update_control_services_button();

  state_timer_ = new QTimer(this);
  connect(state_timer_, &QTimer::timeout, this, &MainWindow::request_dashboard_state);
  state_timer_->start(100);
  request_dashboard_state();
}

MainWindow::~MainWindow()
{
  // The destructor cannot rely on QTimer callbacks. Only terminate services
  // spawned by this window; externally managed services remain untouched.
  if (services_owned_) {
    stop_process_synchronously(control_mode_manager_pid_);
    stop_process_synchronously(control_api_pid_);
    control_mode_manager_pid_ = 0;
    control_api_pid_ = 0;
    services_owned_ = false;
  }
  if (rviz_manager_) {
    rviz_manager_->stopUpdate();
  }
  if (executor_) {
    executor_->cancel();
  }
  if (executor_thread_.joinable()) {
    executor_thread_.join();
  }
}

void MainWindow::build_ui()
{
  network_ = new QNetworkAccessManager(this);
  auto * window_menu = menuBar()->addMenu(QStringLiteral("Window"));
  auto * full_screen_action = window_menu->addAction(QStringLiteral("Full Screen"));
  full_screen_action->setShortcut(QKeySequence(Qt::Key_F11));
  auto * maximized_action = window_menu->addAction(QStringLiteral("Maximized"));
  auto * windowed_action = window_menu->addAction(QStringLiteral("Windowed"));
  windowed_action->setShortcut(QKeySequence(Qt::Key_Escape));
  connect(full_screen_action, &QAction::triggered, this, [this]() { showFullScreen(); });
  connect(maximized_action, &QAction::triggered, this, [this]() { showMaximized(); });
  connect(windowed_action, &QAction::triggered, this, [this]() { showNormal(); });

  auto * root = new QWidget(this);
  root->setObjectName(QStringLiteral("console_root"));
  auto * root_layout = new QVBoxLayout(root);
  root_layout->setContentsMargins(10, 10, 10, 10);
  root_layout->setSpacing(10);

  auto * header = new QHBoxLayout;
  auto * title = new QLabel(QStringLiteral("UR5e Data Collection Console"));
  title->setStyleSheet(QStringLiteral("font-size:22px; font-weight:bold; color:#e4c778;"));
  connection_label_ = make_value_label(QStringLiteral("connecting to dashboard backend"));
  header->addWidget(title);
  header->addStretch();
  header->addWidget(connection_label_);
  robot_health_value_ = make_health_label();
  scene_camera_health_value_ = make_health_label();
  wrist_camera_health_value_ = make_health_label();
  writer_health_value_ = make_health_label();
  set_health_chip(robot_health_value_, QStringLiteral("Robot"), false, false, QStringLiteral("waiting"));
  set_health_chip(scene_camera_health_value_, QStringLiteral("Scene"), false, false, QStringLiteral("waiting"));
  set_health_chip(wrist_camera_health_value_, QStringLiteral("Wrist"), false, false, QStringLiteral("waiting"));
  set_health_chip(writer_health_value_, QStringLiteral("Writer"), false, false, QStringLiteral("waiting"));
  header->addWidget(robot_health_value_);
  header->addWidget(scene_camera_health_value_);
  header->addWidget(wrist_camera_health_value_);
  header->addWidget(writer_health_value_);
  root_layout->addLayout(header);

  auto * visual_column = new QWidget(root);
  visual_column->setMinimumWidth(680);
  auto * visual_layout = new QVBoxLayout(visual_column);
  auto * rviz_box = new QGroupBox(QStringLiteral("Robot State (RViz2)"), visual_column);
  rviz_layout_ = new QVBoxLayout(rviz_box);
  visual_layout->addWidget(rviz_box, 7);

  auto * camera_box = new QGroupBox(QStringLiteral("Camera Views (CompressedImage)"), visual_column);
  auto * camera_layout = new QHBoxLayout(camera_box);
  external_camera_label_ = make_value_label(QStringLiteral("Scene camera unavailable"));
  wrist_camera_label_ = make_value_label(QStringLiteral("Wrist camera unavailable"));
  for (QLabel * label : {external_camera_label_, wrist_camera_label_}) {
    label->setAlignment(Qt::AlignCenter);
    label->setMinimumSize(220, 140);
    label->setStyleSheet(QStringLiteral("background:#161014; color:#f3eee2; border:1px solid #44392f;"));
    camera_layout->addWidget(label);
  }
  visual_layout->addWidget(camera_box, 3);

  auto * operation_column = new QWidget(root);
  operation_column->setObjectName(QStringLiteral("operation_column"));
  auto * operation_layout = new QVBoxLayout(operation_column);
  operation_layout->setContentsMargins(0, 0, 0, 0);
  operation_layout->setSpacing(8);
  auto * telemetry_box = new QGroupBox(QStringLiteral("Realtime Telemetry"), operation_column);
  auto * telemetry_layout = new QVBoxLayout(telemetry_box);
  qpos_chart_ = new TelemetryChart(QStringLiteral("Joint Position (qpos)"), telemetry_box);
  qvel_chart_ = new TelemetryChart(QStringLiteral("Joint Velocity (qvel)"), telemetry_box);
  effort_chart_ = new TelemetryChart(QStringLiteral("Effort / Torque"), telemetry_box);
  telemetry_layout->addWidget(qpos_chart_);
  telemetry_layout->addWidget(qvel_chart_);
  telemetry_layout->addWidget(effort_chart_);
  operation_layout->addWidget(telemetry_box);
  auto * mode_box = new QGroupBox(QStringLiteral("Mode Manager"), operation_column);
  auto * mode_layout = new QVBoxLayout(mode_box);
  auto * mode_status_frame = new QFrame(mode_box);
  mode_status_frame->setObjectName(QStringLiteral("mode_status_panel"));
  mode_status_frame->setStyleSheet(QStringLiteral("QFrame#mode_status_panel { border:1px solid #6f542b; border-radius:3px; background:#0d0e12; }"));
  auto * mode_status_layout = new QFormLayout(mode_status_frame);
  mode_status_layout->setContentsMargins(8, 7, 8, 7);
  mode_status_layout->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
  mode_status_layout->setHorizontalSpacing(16);
  mode_status_layout->setVerticalSpacing(4);
  mode_value_ = make_value_label();
  mode_state_value_ = make_value_label();
  mode_owner_value_ = make_value_label();
  mode_step_value_ = make_value_label();
  mode_fault_value_ = make_value_label(QStringLiteral("none"));
  control_services_status_value_ = make_value_label(
    QStringLiteral("Control services not started"));
  control_services_status_value_->setWordWrap(true);
  const QList<QPair<QString, QLabel *>> mode_rows = {
    {QStringLiteral("Current mode"), mode_value_}, {QStringLiteral("State"), mode_state_value_},
    {QStringLiteral("Owner"), mode_owner_value_}, {QStringLiteral("Step"), mode_step_value_},
    {QStringLiteral("Fault"), mode_fault_value_},
    {QStringLiteral("Services"), control_services_status_value_}};
  for (int index = 0; index < mode_rows.size(); ++index) {
    mode_status_layout->addRow(new QLabel(mode_rows[index].first), mode_rows[index].second);
  }
  mode_layout->addWidget(mode_status_frame);
  auto * mode_actions_frame = new QFrame(mode_box);
  mode_actions_frame->setObjectName(QStringLiteral("mode_actions_panel"));
  mode_actions_frame->setStyleSheet(QStringLiteral("QFrame#mode_actions_panel { border:1px solid #6f542b; border-radius:3px; background:#111216; }"));
  auto * mode_buttons_layout = new QGridLayout(mode_actions_frame);
  mode_buttons_layout->setContentsMargins(8, 8, 8, 8);
  mode_buttons_layout->setHorizontalSpacing(8);
  mode_buttons_layout->setVerticalSpacing(8);
  mode_buttons_layout->setColumnStretch(0, 1);
  mode_buttons_layout->setColumnStretch(1, 1);
  for (int row = 0; row < 4; ++row) {
    mode_buttons_layout->setRowMinimumHeight(row, 36);
  }
  mode_actions_frame->setMinimumHeight(188);
  control_services_button_ = new QPushButton(QStringLiteral("Start"), mode_actions_frame);
  stop_control_services_button_ = new QPushButton(QStringLiteral("Stop"), mode_actions_frame);
  idle_button_ = new QPushButton(QStringLiteral("Pause"), mode_actions_frame);
  auto_button_ = new QPushButton(QStringLiteral("AUTO"), mode_actions_frame);
  api_button_ = new QPushButton(QStringLiteral("API"), mode_actions_frame);
  teleop_button_ = new QPushButton(QStringLiteral("TELEOP"), mode_actions_frame);
  hil_button_ = new QPushButton(QStringLiteral("Hil_teleop"), mode_actions_frame);
  const QList<QPair<QPushButton *, QString>> mode_buttons = {
    {auto_button_, QStringLiteral("auto")}, {api_button_, QStringLiteral("api")},
    {teleop_button_, QStringLiteral("teleop")}, {hil_button_, QStringLiteral("hil_teleop")}};
  connect(control_services_button_, &QPushButton::clicked, this, &MainWindow::start_control_services);
  connect(stop_control_services_button_, &QPushButton::clicked, this, &MainWindow::stop_control_services);
  connect(idle_button_, &QPushButton::clicked, this, [this]() { request_mode(QStringLiteral("idle")); });
  mode_buttons_layout->addWidget(control_services_button_, 0, 0);
  mode_buttons_layout->addWidget(stop_control_services_button_, 0, 1);
  for (int index = 0; index < mode_buttons.size(); ++index) {
    mode_buttons[index].first->setMinimumHeight(36);
    mode_buttons_layout->addWidget(mode_buttons[index].first, index / 2 + 1, index % 2);
    connect(mode_buttons[index].first, &QPushButton::clicked, this,
      [this, mode = mode_buttons[index].second]() { request_mode(mode); });
  }
  idle_button_->setMinimumHeight(36);
  mode_buttons_layout->addWidget(idle_button_, 3, 0, 1, 2);
  mode_layout->addWidget(mode_actions_frame);
  mode_box->setMinimumHeight(420);
  operation_layout->addWidget(mode_box);

  auto * capture_box = new QGroupBox(QStringLiteral("Capture"), operation_column);
  auto * capture_layout = new QGridLayout(capture_box);
  capture_mode_ = new QComboBox(capture_box);
  capture_mode_->addItems({QStringLiteral("teleop"), QStringLiteral("http"), QStringLiteral("act"), QStringLiteral("vla")});
  capture_task_ = new QLineEdit(QStringLiteral("teleop_segment_01"), capture_box);
  dataset_path_value_ = make_value_label(QStringLiteral("Dataset Path -"));
  auto * new_task = new QPushButton(QStringLiteral("New Task"), capture_box);
  language_instruction_button_ = new QPushButton(QStringLiteral("Language: not set"), capture_box);
  language_instruction_button_->setToolTip(QStringLiteral("Language Instruction"));
  capture_toggle_button_ = new QPushButton(QStringLiteral("Start Capture"), capture_box);
  clean_dataset_button_ = new QPushButton(QStringLiteral("Clean Data"), capture_box);
  continue_dataset_button_ = new QPushButton(QStringLiteral("Continue Dataset..."), capture_box);
  convert_lerobot_button_ = new QPushButton(QStringLiteral("Convert LeRobot..."), capture_box);
  capture_status_value_ = make_value_label(QStringLiteral("Idle"));
  lerobot_export_progress_ = new QProgressBar(capture_box);
  lerobot_export_progress_->setTextVisible(false);
  lerobot_export_progress_->hide();
  capture_layout->addWidget(new QLabel(QStringLiteral("Mode")), 0, 0);
  capture_layout->addWidget(capture_mode_, 0, 1);
  capture_layout->addWidget(new QLabel(QStringLiteral("Task")), 1, 0);
  capture_layout->addWidget(capture_task_, 1, 1);
  capture_layout->addWidget(language_instruction_button_, 1, 2);
  capture_layout->addWidget(new_task, 2, 0);
  capture_layout->addWidget(capture_toggle_button_, 2, 1);
  capture_layout->addWidget(clean_dataset_button_, 2, 2);
  capture_layout->addWidget(continue_dataset_button_, 3, 1);
  capture_layout->addWidget(convert_lerobot_button_, 3, 2);
  capture_layout->addWidget(new QLabel(QStringLiteral("Write status")), 4, 0);
  capture_layout->addWidget(capture_status_value_, 4, 1, 1, 2);
  capture_layout->addWidget(lerobot_export_progress_, 5, 0, 1, 3);
  capture_layout->addWidget(dataset_path_value_, 6, 0, 1, 3);
  connect(new_task, &QPushButton::clicked, this, [this]() {
    post_json(QStringLiteral("/api/capture/new-task"), {{QStringLiteral("task"), capture_task_->text()}});
  });
  connect(
    language_instruction_button_, &QPushButton::clicked,
    this, &MainWindow::request_language_instruction_editor);
  connect(capture_toggle_button_, &QPushButton::clicked, this, [this]() {
    if (capture_running_) {
      request_capture_stop_and_annotation();
      return;
    }
    post_json(QStringLiteral("/api/capture/start"), {
      {QStringLiteral("runtime_mode"), capture_mode_->currentText()},
      {QStringLiteral("task"), capture_task_->text()},
      {QStringLiteral("task_id"), capture_task_id_},
      {QStringLiteral("language_instruction_en"), capture_language_instruction_en_},
      {QStringLiteral("language_instruction_zh"), capture_language_instruction_zh_},
      {QStringLiteral("sample_rate_hz"), 15.0},
      {QStringLiteral("sampling_clock"), QStringLiteral("scene_camera_header")},
      {QStringLiteral("camera_sync_tolerance_s"), 0.02},
      {QStringLiteral("joint_state_sync_tolerance_s"), 0.02},
      {QStringLiteral("gripper_sync_tolerance_s"), 0.03}});
  });
  connect(clean_dataset_button_, &QPushButton::clicked, this, [this]() {
    if (capture_running_ || capture_dataset_path_.isEmpty()) {
      return;
    }
    QDialog clean_dialog(this);
    clean_dialog.setWindowTitle(QStringLiteral("Confirm Data Cleaning"));
    clean_dialog.setModal(true);
    auto * clean_layout = new QVBoxLayout(&clean_dialog);
    auto * clean_message = new QLabel(
      QStringLiteral("Cleaning will read original data at:\n%1\n\nand replace its sibling cleaned dataset. Original files are unchanged.")
        .arg(capture_dataset_path_),
      &clean_dialog);
    clean_message->setWordWrap(true);
    clean_layout->addWidget(clean_message);
    auto * clean_dialog_buttons = new QHBoxLayout;
    auto * clean_yes = new QPushButton(QStringLiteral("Yes"), &clean_dialog);
    auto * clean_no = new QPushButton(QStringLiteral("No"), &clean_dialog);
    clean_dialog_buttons->addWidget(clean_yes);
    clean_dialog_buttons->addWidget(clean_no);
    clean_layout->addLayout(clean_dialog_buttons);
    connect(clean_yes, &QPushButton::clicked, &clean_dialog, &QDialog::accept);
    connect(clean_no, &QPushButton::clicked, &clean_dialog, &QDialog::reject);
    if (clean_dialog.exec() == QDialog::Accepted) {
      request_dataset_cleaning();
    }
  });
  connect(continue_dataset_button_, &QPushButton::clicked, this, &MainWindow::request_existing_dataset);
  connect(convert_lerobot_button_, &QPushButton::clicked, this,
    &MainWindow::request_standalone_lerobot_export);
  operation_layout->addWidget(capture_box);

  auto * replay_box = new QGroupBox(QStringLiteral("Episode Replay (read-only)"), operation_column);
  auto * replay_layout = new QGridLayout(replay_box);
  replay_dataset_path_ = new QLineEdit(replay_box);
  replay_episode_ = new QComboBox(replay_box);
  replay_rate_ = new QDoubleSpinBox(replay_box);
  replay_rate_->setRange(0.1, 60.0);
  replay_rate_->setValue(10.0);
  auto * load = new QPushButton(QStringLiteral("Load"), replay_box);
  auto * browse = new QPushButton(QStringLiteral("Browse..."), replay_box);
  replay_button_ = new QPushButton(QStringLiteral("Replay"), replay_box);
  replay_pause_button_ = new QPushButton(QStringLiteral("Pause"), replay_box);
  replay_resume_button_ = new QPushButton(QStringLiteral("Resume"), replay_box);
  replay_stop_button_ = new QPushButton(QStringLiteral("Stop"), replay_box);
  replay_timeline_ = new QSlider(Qt::Horizontal, root);
  replay_timeline_->setRange(0, 0);
  replay_timeline_->setEnabled(false);
  replay_progress_value_ = make_value_label(QStringLiteral("Frame - / - · t = -"));
  replay_status_value_ = make_value_label(QStringLiteral("Select a qpos_gripper dataset"));
  replay_layout->addWidget(new QLabel(QStringLiteral("Dataset Path")), 0, 0);
  replay_layout->addWidget(replay_dataset_path_, 0, 1, 1, 3);
  replay_layout->addWidget(browse, 0, 4);
  replay_layout->addWidget(new QLabel(QStringLiteral("Episode")), 1, 0);
  replay_layout->addWidget(replay_episode_, 1, 1);
  replay_layout->addWidget(new QLabel(QStringLiteral("Rate Hz")), 1, 2);
  replay_layout->addWidget(replay_rate_, 1, 3);
  replay_layout->addWidget(load, 2, 0);
  replay_layout->addWidget(replay_button_, 2, 1);
  replay_layout->addWidget(replay_pause_button_, 2, 2);
  replay_layout->addWidget(replay_resume_button_, 2, 3);
  replay_layout->addWidget(replay_stop_button_, 2, 4);
  replay_layout->addWidget(replay_status_value_, 3, 0, 1, 5);
  replay_button_->setEnabled(false);
  connect(browse, &QPushButton::clicked, this, [this]() {
    auto * dialog = new QFileDialog(this, QStringLiteral("Select qpos_gripper dataset"));
    dialog->setFileMode(QFileDialog::Directory);
    dialog->setOption(QFileDialog::ShowDirsOnly, true);
    dialog->setOption(QFileDialog::DontUseNativeDialog, true);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    if (!replay_dataset_path_->text().isEmpty()) {
      dialog->setDirectory(replay_dataset_path_->text());
    }
    connect(dialog, &QFileDialog::fileSelected, this, [this](const QString & dataset_dir) {
      replay_dataset_path_->setText(dataset_dir);
      request_replay_episodes();
    });
    dialog->open();
  });
  connect(load, &QPushButton::clicked, this, &MainWindow::request_replay_episodes);
  connect(replay_dataset_path_, &QLineEdit::editingFinished, this, &MainWindow::request_replay_episodes);
  connect(replay_button_, &QPushButton::clicked, this, [this]() {
    if (replay_episode_->currentIndex() < 0) {
      replay_status_value_->setText(QStringLiteral("Load an episode before replaying"));
      return;
    }
    replay_status_value_->setText(QStringLiteral("Replay requested"));
    post_json(QStringLiteral("/api/replay/start"), {
      {QStringLiteral("dataset_dir"), replay_dataset_path_->text()},
      {QStringLiteral("episode_index"), replay_episode_->currentData().toInt()},
      {QStringLiteral("rate_hz"), replay_rate_->value()}});
  });
  connect(replay_pause_button_, &QPushButton::clicked, this, [this]() {
    post_json(QStringLiteral("/api/replay/pause"), {});
  });
  connect(replay_resume_button_, &QPushButton::clicked, this, [this]() {
    post_json(QStringLiteral("/api/replay/resume"), {});
  });
  connect(replay_stop_button_, &QPushButton::clicked, this, [this]() {
    post_json(QStringLiteral("/api/replay/stop"), {});
  });
  connect(replay_timeline_, &QSlider::sliderPressed, this, [this]() {
    replay_timeline_dragging_ = true;
  });
  connect(replay_timeline_, &QSlider::sliderMoved, this, [this](int frame_index) {
    replay_progress_value_->setText(QStringLiteral("Seek frame %1 / %2")
      .arg(frame_index + 1).arg(replay_timeline_->maximum() + 1));
  });
  connect(replay_timeline_, &QSlider::sliderReleased, this, [this]() {
    const int frame_index = replay_timeline_->value();
    replay_timeline_dragging_ = false;
    request_replay_seek(frame_index);
  });
  operation_layout->addWidget(replay_box);
  operation_layout->addStretch();

  auto * tabs = new QTabWidget(root);
  topics_text_ = make_text_panel();
  topology_text_ = make_text_panel();
  quality_text_ = make_text_panel();
  drop_reason_text_ = make_text_panel();
  replay_status_text_ = make_text_panel();
  tabs->addTab(topics_text_, QStringLiteral("Key Topics"));
  tabs->addTab(topology_text_, QStringLiteral("Topology"));
  tabs->addTab(quality_text_, QStringLiteral("Quality"));
  tabs->addTab(drop_reason_text_, QStringLiteral("Drop Reason"));
  tabs->addTab(replay_status_text_, QStringLiteral("Replay Status"));
  tabs->setMinimumHeight(140);
  tabs->setDocumentMode(true);

  auto * workspace = new QSplitter(Qt::Horizontal, root);
  auto * left_column = new QSplitter(Qt::Vertical, workspace);
  auto * right_sidebar = new QScrollArea(workspace);
  right_sidebar->setObjectName(QStringLiteral("operation_sidebar"));
  right_sidebar->setFrameShape(QFrame::NoFrame);
  right_sidebar->setWidgetResizable(true);
  right_sidebar->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
  right_sidebar->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn);
  right_sidebar->viewport()->setObjectName(QStringLiteral("operation_sidebar_viewport"));
  right_sidebar->setWidget(operation_column);
  left_column->addWidget(visual_column);
  left_column->addWidget(tabs);
  left_column->setChildrenCollapsible(false);
  left_column->setStretchFactor(0, 8);
  left_column->setStretchFactor(1, 3);
  workspace->addWidget(left_column);
  workspace->addWidget(right_sidebar);
  workspace->setChildrenCollapsible(false);
  workspace->setStretchFactor(0, 12);
  workspace->setStretchFactor(1, 8);
  auto * replay_timeline_box = new QGroupBox(QStringLiteral("Replay Timeline"), root);
  replay_timeline_box->setFixedHeight(72);
  auto * replay_timeline_layout = new QHBoxLayout(replay_timeline_box);
  replay_timeline_layout->addWidget(new QLabel(QStringLiteral("Progress"), replay_timeline_box));
  replay_timeline_layout->addWidget(replay_timeline_, 1);
  replay_timeline_layout->addWidget(replay_progress_value_);
  root_layout->addWidget(replay_timeline_box);
  root_layout->addWidget(workspace, 1);
  setCentralWidget(root);
}

void MainWindow::initialize_ros()
{
  node_ = std::make_shared<rclcpp::Node>("data_collection_rviz_panel");
  mode_request_publisher_ = node_->create_publisher<std_msgs::msg::String>(kModeRequestTopic, 10);
  robot_model_joint_state_publisher_ = node_->create_publisher<sensor_msgs::msg::JointState>(
    kRobotModelJointStateTopic, 30);
  replay_joint_state_publisher_ = node_->create_publisher<sensor_msgs::msg::JointState>(kReplayJointStateTopic, 10);
  mode_subscription_ = node_->create_subscription<std_msgs::msg::String>(kModeTopic, 10,
    [this](const std_msgs::msg::String::SharedPtr message) {
      QMetaObject::invokeMethod(this, [this, value = QString::fromStdString(message->data)]() {
        mode_value_->setText(value);
      }, Qt::QueuedConnection);
    });
  mode_status_subscription_ = node_->create_subscription<std_msgs::msg::String>(kModeStatusTopic, 10,
    [this](const std_msgs::msg::String::SharedPtr message) {
      const QJsonDocument document = QJsonDocument::fromJson(QByteArray::fromStdString(message->data));
      if (!document.isObject()) { return; }
      const QJsonObject status = document.object();
      QMetaObject::invokeMethod(this, [this, status]() {
        const QString state = status.value(QStringLiteral("state")).toString();
        const QString owner = status.value(QStringLiteral("owner")).toString();
        mode_status_received_ = true;
        mode_status_stale_timer_->start(1500);
        mode_value_->setText(status.value(QStringLiteral("current_mode")).toString());
        mode_state_value_->setText(state);
        mode_owner_value_->setText(owner);
        mode_step_value_->setText(status.value(QStringLiteral("step")).toString());
        mode_fault_value_->setText(status.value(QStringLiteral("fault")).toString(QStringLiteral("none")));
        const bool switching = state == QStringLiteral("SWITCHING");
        set_mode_buttons_enabled(!switching);
        if (control_services_state_ == ControlServicesState::StartingModeManager) {
          control_services_timeout_timer_->stop();
          control_services_state_ = ControlServicesState::Running;
          control_services_status_value_->setText(QStringLiteral("Control services running"));
          update_control_services_button();
        } else if (control_services_state_ == ControlServicesState::WaitingForIdle &&
          state == QStringLiteral("IDLE") && owner == QStringLiteral("none"))
        {
          stop_owned_mode_manager();
        }
      }, Qt::QueuedConnection);
    });
  joint_state_subscription_ = node_->create_subscription<sensor_msgs::msg::JointState>(kJointStateTopic, 30,
    [this](const sensor_msgs::msg::JointState::SharedPtr message) {
      robot_model_joint_state_publisher_->publish(*message);
      const auto names = message->name;
      const auto position = message->position;
      const auto velocity = message->velocity;
      const auto effort = message->effort;
      double timestamp = static_cast<double>(message->header.stamp.sec) +
        static_cast<double>(message->header.stamp.nanosec) * 1e-9;
      if (timestamp <= 0.0) {
        timestamp = node_->now().seconds();
      }
      QMetaObject::invokeMethod(this, [this, names, position, velocity, effort, timestamp]() {
        if (replay_mode_active_) {
          return;
        }
        qpos_chart_->set_joint_names(names);
        qvel_chart_->set_joint_names(names);
        effort_chart_->set_joint_names(names);
        qpos_chart_->append(timestamp, position);
        qvel_chart_->append(timestamp, velocity);
        effort_chart_->append(timestamp, effort);
      }, Qt::QueuedConnection);
    });
  gripper_joint_state_subscription_ = node_->create_subscription<sensor_msgs::msg::JointState>(
    kGripperJointStateTopic, 30,
    [this](const sensor_msgs::msg::JointState::SharedPtr message) {
      robot_model_joint_state_publisher_->publish(*message);
    });
  external_camera_subscription_ = node_->create_subscription<sensor_msgs::msg::CompressedImage>(
    kExternalCameraTopic, rclcpp::SensorDataQoS(),
    [this](const sensor_msgs::msg::CompressedImage::SharedPtr message) { update_camera(external_camera_label_, *message); });
  wrist_camera_subscription_ = node_->create_subscription<sensor_msgs::msg::CompressedImage>(
    kWristCameraTopic, rclcpp::SensorDataQoS(),
    [this](const sensor_msgs::msg::CompressedImage::SharedPtr message) { update_camera(wrist_camera_label_, *message); });

  executor_ = std::make_shared<rclcpp::executors::MultiThreadedExecutor>();
  executor_->add_node(node_);
  executor_thread_ = std::thread([this]() { executor_->spin(); });
}

void MainWindow::initialize_rviz()
{
  try {
    rviz_rendering::RenderSystem::get();
    rviz_node_ = std::make_shared<rviz_common::ros_integration::RosNodeAbstraction>("data_collection_rviz_panel_rviz");
    rviz_frame_ = new rviz_common::VisualizationFrame(rviz_node_);
    rviz_frame_->setApp(qobject_cast<QApplication *>(QApplication::instance()));
    rviz_frame_->setSplashPath(QString());
    rviz_layout_->setContentsMargins(0, 0, 0, 0);
    rviz_layout_->addWidget(rviz_frame_);
    rviz_frame_->initialize(rviz_node_);
    rviz_frame_->setHideButtonVisibility(false);
    rviz_frame_->menuBar()->hide();
    rviz_frame_->statusBar()->hide();
    for (QDockWidget * dock : rviz_frame_->findChildren<QDockWidget *>()) {
      dock->hide();
    }
    for (QToolBar * toolbar : rviz_frame_->findChildren<QToolBar *>()) {
      toolbar->hide();
    }
    rviz_manager_ = rviz_frame_->getManager();
    rviz_manager_->setFixedFrame(QStringLiteral("base_link"));
    rviz_manager_->createDisplay(QStringLiteral("rviz_default_plugins/Grid"), QStringLiteral("Grid"), true);
    live_model_ = rviz_manager_->createDisplay(
      QStringLiteral("rviz_default_plugins/RobotModel"), QStringLiteral("UR5e RobotModel"), true);
    if (auto * live_description_topic = live_model_->subProp(QStringLiteral("Description Topic"))) {
      live_description_topic->setValue(QStringLiteral("/robot_description"));
    }
    replay_model_ = rviz_manager_->createDisplay(
      QStringLiteral("rviz_default_plugins/RobotModel"), QStringLiteral("Replay RobotModel"), false);
    if (auto * tf_prefix = replay_model_->subProp(QStringLiteral("TF Prefix"))) {
      tf_prefix->setValue(QStringLiteral("replay"));
    }
    if (auto * description_topic = replay_model_->subProp(QStringLiteral("Description Topic"))) {
      description_topic->setValue(QStringLiteral("/replay/robot_description"));
    }
  } catch (const std::exception & error) {
    if (rviz_frame_ != nullptr) {
      delete rviz_frame_;
      rviz_frame_ = nullptr;
    }
    rviz_manager_ = nullptr;
    auto * message = new QLabel(
      QStringLiteral("RViz unavailable: %1").arg(QString::fromLocal8Bit(error.what())),
      rviz_layout_->parentWidget());
    message->setWordWrap(true);
    message->setAlignment(Qt::AlignCenter);
    rviz_layout_->addWidget(message);
  }
}

void MainWindow::update_camera(QLabel * label, const sensor_msgs::msg::CompressedImage & image)
{
  const QByteArray encoded(reinterpret_cast<const char *>(image.data.data()), static_cast<int>(image.data.size()));
  QImage decoded;
  decoded.loadFromData(encoded);
  if (decoded.isNull()) { return; }
  QMetaObject::invokeMethod(this, [label, decoded]() {
    label->setPixmap(QPixmap::fromImage(decoded).scaled(label->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
  }, Qt::QueuedConnection);
}

void MainWindow::request_dashboard_state()
{
  if (dashboard_state_request_in_flight_) {
    return;
  }
  dashboard_state_request_in_flight_ = true;
  QNetworkRequest request(QUrl(QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/state")));
  configure_network_request(request, 1500);
  const auto reply = network_->get(request);
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const QByteArray payload = reply->readAll();
    const bool ok = reply->error() == QNetworkReply::NoError;
    reply->deleteLater();
    dashboard_state_request_in_flight_ = false;
    if (!ok) {
      connection_label_->setText(QStringLiteral("dashboard backend disconnected"));
      return;
    }
    const QJsonDocument document = QJsonDocument::fromJson(payload);
    if (!document.isObject()) { return; }
    connection_label_->setText(QStringLiteral("dashboard backend connected"));
    update_dashboard_state(document.object());
  });
}

void MainWindow::post_json(const QString & path, const QJsonObject & payload)
{
  QNetworkRequest request(QUrl(QString::fromLatin1(kDashboardUrl) + path));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  configure_network_request(request, 5000);
  const auto reply = network_->post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
  connect(reply, &QNetworkReply::finished, this, [this, path, reply]() {
    const QByteArray response = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    const QJsonDocument document = QJsonDocument::fromJson(response);
    const QJsonObject response_object = document.object();
    if (path == QStringLiteral("/api/capture/select-existing-dataset")) {
      if (!transport_ok || !document.isObject() ||
        !response_object.value(QStringLiteral("ok")).toBool())
      {
        const QString error = document.isObject() ?
          response_object.value(QStringLiteral("error")).toString() : transport_error;
        show_temporary_capture_status(QStringLiteral("Could not select dataset: %1").arg(
          error.isEmpty() ? QStringLiteral("backend unavailable") : error));
        return;
      }
      apply_existing_dataset_selection(response_object);
    }
    if (path == QStringLiteral("/api/capture/new-task")) {
      if (!transport_ok || !document.isObject() ||
        !response_object.value(QStringLiteral("ok")).toBool())
      {
        const QString error = document.isObject() ?
          response_object.value(QStringLiteral("error")).toString() : transport_error;
        show_temporary_capture_status(QStringLiteral("Could not create task: %1").arg(
          error.isEmpty() ? QStringLiteral("backend unavailable") : error));
        return;
      }
      clear_capture_dataset_selection();
    }
    if (path == QStringLiteral("/api/capture/start") &&
      (!transport_ok || !document.isObject() ||
      !response_object.value(QStringLiteral("ok")).toBool()))
    {
      const QString error = document.isObject() ?
        response_object.value(QStringLiteral("error")).toString() : transport_error;
      show_temporary_capture_status(QStringLiteral("Capture could not start: %1").arg(
        error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      return;
    }
    if (path.startsWith(QStringLiteral("/api/replay/"))) {
      if (!transport_ok || (document.isObject() && !document.object().value(QStringLiteral("ok")).toBool())) {
        const QString error = document.isObject() ?
          document.object().value(QStringLiteral("error")).toString() : transport_error;
        replay_status_value_->setText(QStringLiteral("Replay command rejected: %1").arg(
          error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      }
    }
    request_dashboard_state();
  });
}

void MainWindow::clear_capture_dataset_selection()
{
  capture_dataset_path_.clear();
  dataset_path_value_->setText(QStringLiteral("Dataset Path -"));
  capture_task_id_.clear();
  capture_language_instruction_en_.clear();
  capture_language_instruction_zh_.clear();
  capture_task_id_is_suggested_ = false;
  continued_dataset_annotation_dirty_ = false;
  capture_task_->setEnabled(true);
  language_instruction_button_->setText(QStringLiteral("Language: not set"));
}

void MainWindow::apply_existing_dataset_selection(const QJsonObject & capture)
{
  continued_dataset_annotation_dirty_ = false;
  const QString selected_dataset = capture.value(QStringLiteral("dataset_dir")).toString();
  if (!selected_dataset.isEmpty()) {
    capture_dataset_path_ = selected_dataset;
    dataset_path_value_->setText(QStringLiteral("Dataset Path %1").arg(capture_dataset_path_));
  }
  capture_mode_->setEnabled(true);
  capture_task_->setEnabled(false);
  const QString selected_mode = capture.value(QStringLiteral("runtime_mode")).toString();
  const int mode_index = capture_mode_->findText(selected_mode, Qt::MatchFixedString);
  if (mode_index >= 0) {
    capture_mode_->setCurrentIndex(mode_index);
  }
  const QString selected_task = capture.value(QStringLiteral("task")).toString();
  if (!selected_task.isEmpty()) {
    capture_task_->setText(selected_task);
  }
  const QJsonObject annotation = capture.value(QStringLiteral("task_annotation")).toObject();
  capture_task_id_ = annotation.value(QStringLiteral("task_id")).toString();
  capture_language_instruction_en_ = annotation.value(QStringLiteral("language_instruction_en")).toString();
  capture_language_instruction_zh_ = annotation.value(QStringLiteral("language_instruction_zh")).toString();
  capture_task_id_is_suggested_ = !capture_task_id_.isEmpty() &&
    capture_task_id_ == suggest_task_id(capture_language_instruction_en_);
  language_instruction_button_->setText(
    capture_task_id_.isEmpty() && capture_language_instruction_en_.isEmpty() &&
    capture_language_instruction_zh_.isEmpty() ?
    QStringLiteral("Language: not set") : QStringLiteral("Language: ready"));
}

void MainWindow::show_temporary_capture_status(const QString & status)
{
  capture_status_override_active_ = true;
  const int generation = ++capture_status_override_generation_;
  capture_status_value_->setText(status);
  QTimer::singleShot(3000, this, [this, generation]() {
    if (generation != capture_status_override_generation_) {
      return;
    }
    capture_status_override_active_ = false;
    request_dashboard_state();
  });
}

void MainWindow::request_capture_stop_and_annotation()
{
  if (capture_stop_in_progress_) {
    return;
  }
  capture_stop_in_progress_ = true;
  update_capture_toggle();
  QNetworkRequest request(QUrl(QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/stop")));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  configure_network_request(request, 10000);
  const auto reply = network_->post(request, QByteArrayLiteral("{}"));
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const QByteArray payload = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    capture_stop_in_progress_ = false;
    update_capture_toggle();
    const QJsonDocument document = QJsonDocument::fromJson(payload);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      capture_status_value_->setText(QStringLiteral("Stop failed: %1").arg(
        error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      return;
    }
    capture_running_ = false;
    update_capture_toggle();
    request_dashboard_state();

    QDialog dialog(this);
    dialog.setWindowTitle(QStringLiteral("Capture Outcome"));
    dialog.setModal(true);
    auto * dialog_layout = new QVBoxLayout(&dialog);
    dialog_layout->addWidget(new QLabel(
      QStringLiteral("Select the outcome for the completed episode."), &dialog));
    auto * dialog_buttons = new QHBoxLayout;
    auto * success = new QPushButton(QStringLiteral("Success"), &dialog);
    auto * failure = new QPushButton(QStringLiteral("Failure"), &dialog);
    auto * cancel = new QPushButton(QStringLiteral("Cancel"), &dialog);
    dialog_buttons->addWidget(success);
    dialog_buttons->addWidget(failure);
    dialog_buttons->addWidget(cancel);
    dialog_layout->addLayout(dialog_buttons);

    QString outcome;
    connect(success, &QPushButton::clicked, &dialog, [&dialog, &outcome]() {
      outcome = QStringLiteral("success");
      dialog.accept();
    });
    connect(failure, &QPushButton::clicked, &dialog, [&dialog, &outcome]() {
      outcome = QStringLiteral("failure");
      dialog.accept();
    });
    connect(cancel, &QPushButton::clicked, &dialog, &QDialog::reject);
    dialog.exec();
    if (outcome == QStringLiteral("success")) {
      request_capture_annotation(QStringLiteral("success"));
    } else if (outcome == QStringLiteral("failure")) {
      request_capture_annotation(QStringLiteral("failure"));
    } else {
      capture_status_value_->setText(QStringLiteral("Capture stopped: outcome unreviewed"));
    }
  });
}

void MainWindow::request_capture_annotation(const QString & outcome)
{
  if (capture_annotation_in_progress_) {
    return;
  }
  capture_annotation_in_progress_ = true;
  update_capture_toggle();
  capture_status_value_->setText(QStringLiteral("Saving capture outcome..."));
  QNetworkRequest request(QUrl(QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/annotate")));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  configure_network_request(request, 10000);
  const QJsonObject annotation_payload{{QStringLiteral("outcome"), outcome}};
  const auto reply = network_->post(
    request, QJsonDocument(annotation_payload).toJson(QJsonDocument::Compact));
  connect(reply, &QNetworkReply::finished, this, [this, outcome, reply]() {
    const QByteArray payload = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    capture_annotation_in_progress_ = false;
    const QJsonDocument document = QJsonDocument::fromJson(payload);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      capture_status_value_->setText(QStringLiteral("Outcome not saved: %1").arg(
        error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      update_capture_toggle();
      return;
    }
    capture_status_value_->setText(QStringLiteral("Outcome saved: %1 (%2 episode(s))").arg(
      outcome, QString::number(response.value(QStringLiteral("episode_indices")).toArray().size())));
    update_capture_toggle();
    request_dashboard_state();
  });
}

void MainWindow::request_language_instruction_editor()
{
  if (capture_running_ || language_editor_request_in_progress_) {
    return;
  }
  language_editor_request_in_progress_ = true;
  update_capture_toggle();
  QNetworkRequest request(QUrl(
    QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/task-labels")));
  configure_network_request(request, 5000);
  const auto reply = network_->get(request);
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const QByteArray body = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    language_editor_request_in_progress_ = false;
    update_capture_toggle();
    if (capture_running_) {
      return;
    }
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      QMessageBox::warning(
        this, QStringLiteral("Language Instruction"),
        QStringLiteral("Task labels unavailable: %1").arg(
          error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      return;
    }
    show_language_instruction_editor(response.value(QStringLiteral("labels")).toArray());
  });
}

void MainWindow::show_language_instruction_editor(const QJsonArray & labels)
{
  QDialog dialog(this);
  dialog.setWindowTitle(QStringLiteral("Language Instruction"));
  dialog.setModal(true);
  auto * dialog_layout = new QVBoxLayout(&dialog);
  auto * form_layout = new QFormLayout;
  auto * task_id = new QComboBox(&dialog);
  task_id->setEditable(true);
  task_id->setInsertPolicy(QComboBox::NoInsert);
  task_id->addItem(QString());
  for (const QJsonValue & value : labels) {
    const QJsonObject label = value.toObject();
    const QString id = label.value(QStringLiteral("task_id")).toString();
    if (!id.isEmpty()) {
      task_id->addItem(id, label.toVariantMap());
    }
  }
  auto * english = new QPlainTextEdit(&dialog);
  auto * chinese = new QPlainTextEdit(&dialog);
  english->setMinimumHeight(90);
  chinese->setMinimumHeight(90);
  english->setPlainText(capture_language_instruction_en_);
  chinese->setPlainText(capture_language_instruction_zh_);
  form_layout->addRow(QStringLiteral("Task ID"), task_id);
  form_layout->addRow(QStringLiteral("English instruction"), english);
  form_layout->addRow(QStringLiteral("中文指令"), chinese);
  dialog_layout->addLayout(form_layout);

  const auto fill_known_label = [task_id, english, chinese]() {
    const QVariant data = task_id->currentData();
    if (!data.isValid()) {
      return;
    }
    const QVariantMap label = data.toMap();
    english->setPlainText(label.value(QStringLiteral("language_instruction_en")).toString());
    chinese->setPlainText(label.value(QStringLiteral("language_instruction_zh")).toString());
  };
  if (!capture_task_id_.isEmpty()) {
    const int index = task_id->findText(capture_task_id_, Qt::MatchFixedString);
    if (index >= 0) {
      task_id->setCurrentIndex(index);
    } else {
      task_id->setEditText(capture_task_id_);
    }
  }

  connect(task_id, &QComboBox::currentTextChanged, &dialog,
    [task_id, fill_known_label](const QString & text) {
      const int index = task_id->findText(text, Qt::MatchFixedString);
      if (index >= 0) {
        task_id->setCurrentIndex(index);
        fill_known_label();
      }
    });

  auto previous_suggestion = std::make_shared<QString>(
    capture_task_id_is_suggested_ ? capture_task_id_ : QString());
  connect(english, &QPlainTextEdit::textChanged, &dialog,
    [task_id, english, previous_suggestion]() {
      const QString current_id = task_id->currentText().trimmed();
      if (!current_id.isEmpty() && current_id != *previous_suggestion) {
        return;
      }
      *previous_suggestion = suggest_task_id(english->toPlainText());
      task_id->setEditText(*previous_suggestion);
    });

  auto * actions = new QHBoxLayout;
  actions->addStretch(1);
  auto * save = new QPushButton(QStringLiteral("Save"), &dialog);
  auto * cancel = new QPushButton(QStringLiteral("Cancel"), &dialog);
  actions->addWidget(save);
  actions->addWidget(cancel);
  dialog_layout->addLayout(actions);
  connect(save, &QPushButton::clicked, &dialog, &QDialog::accept);
  connect(cancel, &QPushButton::clicked, &dialog, &QDialog::reject);
  if (dialog.exec() != QDialog::Accepted) {
    return;
  }

  capture_task_id_ = task_id->currentText().trimmed();
  capture_language_instruction_en_ = english->toPlainText().trimmed();
  capture_language_instruction_zh_ = chinese->toPlainText().trimmed();
  if (capture_task_id_.isEmpty() && !capture_language_instruction_en_.isEmpty()) {
    capture_task_id_ = suggest_task_id(capture_language_instruction_en_);
  }
  capture_task_id_is_suggested_ = !capture_task_id_.isEmpty() &&
    capture_task_id_ == suggest_task_id(capture_language_instruction_en_);
  continued_dataset_annotation_dirty_ = true;
  const bool language_ready = !capture_task_id_.isEmpty() ||
    !capture_language_instruction_en_.isEmpty() || !capture_language_instruction_zh_.isEmpty();
  language_instruction_button_->setText(language_ready ?
    QStringLiteral("Language: ready") : QStringLiteral("Language: not set"));
}

void MainWindow::update_capture_toggle()
{
  if (capture_toggle_button_ == nullptr) {
    return;
  }
  capture_toggle_button_->setText(capture_running_ ?
    QStringLiteral("Stop Capture") : QStringLiteral("Start Capture"));
  capture_toggle_button_->setEnabled(
    !capture_stop_in_progress_ && !capture_annotation_in_progress_ &&
    !cleaning_in_progress_ && !lerobot_export_in_progress_);
  capture_toggle_button_->setStyleSheet(capture_running_ ?
    QStringLiteral("color:#fff4df; border-color:#e4c778; background:#9c2a40;") : QString());
  if (clean_dataset_button_ != nullptr) {
    clean_dataset_button_->setEnabled(
      !capture_running_ && !capture_dataset_path_.isEmpty() && !cleaning_in_progress_);
  }
  if (language_instruction_button_ != nullptr) {
    language_instruction_button_->setEnabled(
      !capture_running_ && !language_editor_request_in_progress_);
  }
}

void MainWindow::request_dataset_cleaning()
{
  if (capture_dataset_path_.isEmpty()) {
    return;
  }
  cleaning_in_progress_ = true;
  update_capture_toggle();
  capture_status_value_->setText(QStringLiteral("Cleaning original dataset..."));
  QNetworkRequest request(QUrl(QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/clean")));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  const QJsonObject payload{
    {QStringLiteral("dataset_dir"), capture_dataset_path_},
    {QStringLiteral("target_fps"), 15.0},
    {QStringLiteral("max_sync_delta_s"), 0.02},
    {QStringLiteral("fps_tolerance_ratio"), 0.5},
  };
  configure_network_request(request, 120000);
  const auto reply = network_->post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const QByteArray body = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    cleaning_in_progress_ = false;
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      capture_status_value_->setText(QStringLiteral("Cleaning failed: %1").arg(
        error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      update_capture_toggle();
      return;
    }
    const int accepted = response.value(QStringLiteral("accepted_episode_indices")).toArray().size();
    const int rejected = response.value(QStringLiteral("rejected_episode_indices")).toArray().size();
    const int review = response.value(QStringLiteral("needs_review_episode_indices")).toArray().size();
    capture_status_value_->setText(QStringLiteral("Cleaning complete: %1 accepted, %2 rejected, %3 review").arg(
      QString::number(accepted), QString::number(rejected), QString::number(review)));
    update_capture_toggle();
    const QString report_path = response.value(QStringLiteral("report_path")).toString();
    if (!report_path.isEmpty()) {
      auto * result_dialog = new QDialog(this);
      result_dialog->setAttribute(Qt::WA_DeleteOnClose);
      result_dialog->setModal(false);
      result_dialog->setWindowTitle(QStringLiteral("Data Cleaning Complete"));
      auto * result_layout = new QVBoxLayout(result_dialog);
      result_layout->addWidget(new QLabel(
        QStringLiteral("The cleaning report lists every rejected or unreviewed episode and its reason."),
        result_dialog));
      auto * result_actions = new QHBoxLayout();
      auto * open_report = new QPushButton(QStringLiteral("Open Report"), result_dialog);
      auto * export_act = accepted > 0 ?
        new QPushButton(QStringLiteral("Export ACT"), result_dialog) : nullptr;
      auto * export_vla = accepted > 0 ?
        new QPushButton(QStringLiteral("Export VLA"), result_dialog) : nullptr;
      auto * close_result = new QPushButton(QStringLiteral("Close"), result_dialog);
      result_actions->addWidget(open_report);
      if (export_act != nullptr && export_vla != nullptr) {
        result_actions->addWidget(export_act);
        result_actions->addWidget(export_vla);
      }
      result_actions->addStretch(1);
      result_actions->addWidget(close_result);
      result_layout->addLayout(result_actions);
      connect(open_report, &QPushButton::clicked, this, [report_path]() {
        QDesktopServices::openUrl(QUrl::fromLocalFile(report_path));
      });
      if (export_act != nullptr && export_vla != nullptr) {
        const QString cleaned_dataset_dir = response.value(QStringLiteral("cleaned_dataset_dir")).toString();
        connect(export_act, &QPushButton::clicked, this, [this, cleaned_dataset_dir]() {
          request_lerobot_export(cleaned_dataset_dir, QStringLiteral("act"));
        });
        connect(export_vla, &QPushButton::clicked, this, [this, cleaned_dataset_dir]() {
          request_lerobot_export(cleaned_dataset_dir, QStringLiteral("vla"));
        });
      }
      connect(close_result, &QPushButton::clicked, result_dialog, &QDialog::close);
      result_dialog->show();
    }
    request_dashboard_state();
  });
}

void MainWindow::request_lerobot_export(
  const QString & cleaned_dataset_dir, const QString & profile)
{
  if (cleaned_dataset_dir.isEmpty()) {
    capture_status_value_->setText(QStringLiteral("LeRobot export unavailable: cleaned dataset path missing"));
    return;
  }
  if (lerobot_export_in_progress_) {
    show_temporary_capture_status(QStringLiteral("LeRobot export already running (%1)")
      .arg(lerobot_export_profile_.toUpper()));
    return;
  }
  const QString normalized_profile = profile.trimmed().toLower();
  if (normalized_profile != QStringLiteral("act") && normalized_profile != QStringLiteral("vla")) {
    capture_status_value_->setText(QStringLiteral("LeRobot export unavailable: unknown profile"));
    return;
  }
  const QString profile_label = normalized_profile.toUpper();
  lerobot_export_in_progress_ = true;
  lerobot_export_profile_ = normalized_profile;
  auto * dialog = new QFileDialog(
    this, QStringLiteral("Select %1 Output Parent Directory").arg(profile_label));
  dialog->setFileMode(QFileDialog::Directory);
  dialog->setOption(QFileDialog::ShowDirsOnly, true);
  dialog->setOption(QFileDialog::DontUseNativeDialog, true);
  dialog->setAttribute(Qt::WA_DeleteOnClose);
  connect(dialog, &QDialog::rejected, this, [this, profile_label]() {
    lerobot_export_in_progress_ = false;
    show_temporary_capture_status(QStringLiteral("%1 export output directory selection cancelled").arg(
      profile_label));
  });
  connect(dialog, &QDialog::accepted, this,
    [this, dialog, cleaned_dataset_dir, normalized_profile, profile_label]() {
    const QStringList selected_files = dialog->selectedFiles();
    if (selected_files.isEmpty()) {
      lerobot_export_in_progress_ = false;
      show_temporary_capture_status(QStringLiteral("%1 export output directory selection missing").arg(
        profile_label));
      return;
    }
    const QString output_parent = selected_files.constFirst();
    QTimer::singleShot(0, this,
      [this, cleaned_dataset_dir, normalized_profile, profile_label, output_parent]() {
      bool accepted = false;
      const QString default_output_name = normalized_profile == QStringLiteral("vla") ?
        QStringLiteral("lerobot_vla_v3") : QStringLiteral("lerobot_act_v3");
      QString suggested_output_name = default_output_name;
      int suffix = 1;
      while (QDir(output_parent).exists(suggested_output_name)) {
        suggested_output_name = QStringLiteral("%1_%2").arg(default_output_name).arg(suffix++);
      }
      const QString output_name = QInputDialog::getText(
        this, QStringLiteral("%1 Output Name").arg(profile_label), QStringLiteral("Directory name"),
        QLineEdit::Normal, suggested_output_name, &accepted).trimmed();
      if (!accepted || output_name.isEmpty()) {
        lerobot_export_in_progress_ = false;
        show_temporary_capture_status(QStringLiteral("%1 export output name selection cancelled").arg(
          profile_label));
        return;
      }
      if (output_name.contains(QLatin1Char('/'))) {
        lerobot_export_in_progress_ = false;
        show_temporary_capture_status(
          QStringLiteral("%1 export output name cannot contain '/'").arg(profile_label));
        return;
      }
      const QString output_dir = QDir(output_parent).filePath(output_name);
      if (QDir(output_dir).exists()) {
        lerobot_export_in_progress_ = false;
        show_temporary_capture_status(
          QStringLiteral("%1 export output already exists; choose a new name").arg(profile_label));
        return;
      }
      if (normalized_profile == QStringLiteral("vla")) {
        request_lerobot_export_preflight(cleaned_dataset_dir, normalized_profile, output_dir);
        return;
      }
      start_lerobot_export(cleaned_dataset_dir, normalized_profile, output_dir);
    });
  });
  dialog->open();
}

void MainWindow::request_lerobot_export_preflight(
  const QString & cleaned_dataset_dir, const QString & profile, const QString & output_dir)
{
  capture_status_value_->setText(QStringLiteral("VLA export preflight..."));
  QNetworkRequest request(QUrl(
    QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/export-lerobot/preflight")));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  const QJsonObject payload{
    {QStringLiteral("cleaned_dataset_dir"), cleaned_dataset_dir},
    {QStringLiteral("output_dir"), output_dir},
    {QStringLiteral("profile"), profile},
  };
  configure_network_request(request, 120000);
  const auto reply = network_->post(
    request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
  connect(reply, &QNetworkReply::finished, this,
    [this, cleaned_dataset_dir, profile, output_dir, reply]() {
    const QByteArray body = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      lerobot_export_in_progress_ = false;
      show_temporary_capture_status(QStringLiteral("VLA export preflight failed: %1").arg(
        error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      return;
    }
    const int eligible_count = response.value(QStringLiteral("eligible")).toArray().size();
    const int skipped_count = response.value(QStringLiteral("skipped")).toArray().size();
    const QString planned_report_path =
      response.value(QStringLiteral("planned_report_path")).toString(
      QDir(output_dir).filePath(QStringLiteral("meta/vla_export_report.json")));
    const QString message = QStringLiteral(
      "Eligible episodes: %1\nSkipped episodes: %2\n\nPlanned report:\n%3\n\nStart VLA export?")
      .arg(eligible_count).arg(skipped_count).arg(planned_report_path);
    QDialog vla_confirm_dialog(this);
    vla_confirm_dialog.setWindowTitle(QStringLiteral("Confirm VLA Export"));
    auto * vla_confirm_layout = new QVBoxLayout(&vla_confirm_dialog);
    auto * vla_confirm_message = new QLabel(message, &vla_confirm_dialog);
    vla_confirm_message->setWordWrap(true);
    vla_confirm_layout->addWidget(vla_confirm_message);
    auto * vla_confirm_buttons = new QHBoxLayout;
    auto * vla_confirm_yes = new QPushButton(QStringLiteral("Yes"), &vla_confirm_dialog);
    auto * vla_confirm_no = new QPushButton(QStringLiteral("No"), &vla_confirm_dialog);
    vla_confirm_yes->setDefault(true);
    vla_confirm_buttons->addWidget(vla_confirm_yes);
    vla_confirm_buttons->addWidget(vla_confirm_no);
    vla_confirm_layout->addLayout(vla_confirm_buttons);
    connect(vla_confirm_yes, &QPushButton::clicked, &vla_confirm_dialog, &QDialog::accept);
    connect(vla_confirm_no, &QPushButton::clicked, &vla_confirm_dialog, &QDialog::reject);
    if (vla_confirm_dialog.exec() != QDialog::Accepted) {
      lerobot_export_in_progress_ = false;
      show_temporary_capture_status(QStringLiteral("VLA export cancelled"));
      return;
    }
    start_lerobot_export(cleaned_dataset_dir, profile, output_dir);
  });
}

void MainWindow::start_lerobot_export(
  const QString & cleaned_dataset_dir, const QString & profile, const QString & output_dir)
{
  const QString profile_label = profile.toUpper();
  lerobot_export_profile_ = profile;
  lerobot_export_in_progress_ = true;
  lerobot_export_status_retry_count_ = 0;
  set_lerobot_export_activity(true);
  capture_status_value_->setText(QStringLiteral("%1 export queued...").arg(profile_label));
  QNetworkRequest request(QUrl(
    QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/export-lerobot")));
  request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
  const QJsonObject payload{
    {QStringLiteral("cleaned_dataset_dir"), cleaned_dataset_dir},
    {QStringLiteral("output_dir"), output_dir},
    {QStringLiteral("profile"), profile},
    {QStringLiteral("fps"), 15.0},
    {QStringLiteral("cameras"), QJsonArray{QStringLiteral("external"), QStringLiteral("wrist")}},
  };
  configure_network_request(request, 5000);
  const auto reply = network_->post(
    request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
  connect(reply, &QNetworkReply::finished, this, [this, profile_label, reply]() {
    const QByteArray body = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject() || !response.value(QStringLiteral("ok")).toBool()) {
      const QString error = document.isObject() ?
        response.value(QStringLiteral("error")).toString() : transport_error;
      lerobot_export_in_progress_ = false;
      set_lerobot_export_activity(false);
      show_temporary_capture_status(QStringLiteral("%1 export could not start: %2").arg(
        profile_label, error.isEmpty() ? QStringLiteral("backend unavailable") : error));
      return;
    }
    capture_status_value_->setText(QStringLiteral("%1 export running...").arg(profile_label));
    request_lerobot_export_status();
  });
}

void MainWindow::request_lerobot_export_status()
{
  const QString profile_label = lerobot_export_profile_.toUpper();
  QNetworkRequest request(QUrl(
    QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/capture/export-lerobot/status")));
  configure_network_request(request, 3000);
  const auto reply = network_->get(request);
  connect(reply, &QNetworkReply::finished, this, [this, profile_label, reply]() {
    const QByteArray body = reply->readAll();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    const QString transport_error = reply->errorString();
    reply->deleteLater();
    const QJsonDocument document = QJsonDocument::fromJson(body);
    const QJsonObject response = document.object();
    if (!transport_ok || !document.isObject()) {
      ++lerobot_export_status_retry_count_;
      if (lerobot_export_status_retry_count_ >= kMaxLerobotExportStatusRetries) {
        lerobot_export_in_progress_ = false;
        set_lerobot_export_activity(false);
        show_temporary_capture_status(QStringLiteral(
          "%1 export status unavailable after retries: %2").arg(profile_label,
          transport_ok ? QStringLiteral("invalid backend response") : transport_error));
        return;
      }
      const QString status_error = transport_ok ?
        QStringLiteral("invalid backend response") : transport_error;
      show_temporary_capture_status(QStringLiteral("%1 export status unavailable: %2").arg(
        profile_label, status_error));
      QTimer::singleShot(1000, this, &MainWindow::request_lerobot_export_status);
      return;
    }
    const QString status = response.value(QStringLiteral("status")).toString();
    if (status == QStringLiteral("queued") || status == QStringLiteral("running")) {
      lerobot_export_status_retry_count_ = 0;
      capture_status_value_->setText(QStringLiteral("%1 export %2...").arg(profile_label, status));
      QTimer::singleShot(500, this, &MainWindow::request_lerobot_export_status);
      return;
    }
    if (status == QStringLiteral("done")) {
      lerobot_export_status_retry_count_ = 0;
      lerobot_export_in_progress_ = false;
      set_lerobot_export_activity(false);
      const QJsonObject result = response.value(QStringLiteral("result")).toObject();
      show_temporary_capture_status(QStringLiteral("%1 export complete: %2").arg(
        profile_label, result.value(QStringLiteral("output_dir")).toString()));
      const QString report_path = result.value(QStringLiteral("verification_report_path")).toString();
      if (!report_path.isEmpty()) {
        QDesktopServices::openUrl(QUrl::fromLocalFile(report_path));
      }
      return;
    }
    if (status == QStringLiteral("failed")) {
      lerobot_export_status_retry_count_ = 0;
      lerobot_export_in_progress_ = false;
      set_lerobot_export_activity(false);
      show_temporary_capture_status(QStringLiteral("%1 export failed: %2").arg(
        profile_label,
        response.value(QStringLiteral("error")).toString(QStringLiteral("unknown error"))));
      return;
    }
    ++lerobot_export_status_retry_count_;
    if (lerobot_export_status_retry_count_ >= kMaxLerobotExportStatusRetries) {
      lerobot_export_in_progress_ = false;
      set_lerobot_export_activity(false);
      show_temporary_capture_status(QStringLiteral(
        "%1 export status unavailable after retries: unknown status").arg(profile_label));
      return;
    }
    show_temporary_capture_status(QStringLiteral(
      "%1 export status unavailable: invalid backend response").arg(profile_label));
    QTimer::singleShot(1000, this, &MainWindow::request_lerobot_export_status);
  });
}

void MainWindow::set_lerobot_export_activity(bool active)
{
  if (lerobot_export_progress_ == nullptr) {
    return;
  }
  if (active) {
    lerobot_export_progress_->setRange(0, 0);
    lerobot_export_progress_->show();
    return;
  }
  lerobot_export_progress_->setRange(0, 1);
  lerobot_export_progress_->setValue(0);
  lerobot_export_progress_->hide();
}

void MainWindow::request_replay_episodes()
{
  const QString dataset_dir = replay_dataset_path_->text().trimmed();
  replay_episode_->clear();
  replay_button_->setEnabled(false);
  if (dataset_dir.isEmpty()) {
    replay_status_value_->setText(QStringLiteral("Select a qpos_gripper dataset"));
    return;
  }
  replay_status_value_->setText(QStringLiteral("Loading episodes..."));
  QUrl url(QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/replay/episodes"));
  QUrlQuery query;
  query.addQueryItem(QStringLiteral("dataset_dir"), dataset_dir);
  url.setQuery(query);
  QNetworkRequest request(url);
  configure_network_request(request, 10000);
  const auto reply = network_->get(request);
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const QByteArray payload = reply->readAll();
    const QString transport_error = reply->errorString();
    const bool transport_ok = reply->error() == QNetworkReply::NoError;
    reply->deleteLater();
    if (!transport_ok) {
      replay_status_value_->setText(QStringLiteral("Cannot load episodes: %1").arg(transport_error));
      return;
    }
    const QJsonDocument document = QJsonDocument::fromJson(payload);
    if (!document.isObject()) {
      replay_status_value_->setText(QStringLiteral("Cannot load episodes: invalid backend response"));
      return;
    }
    const QJsonObject response = document.object();
    if (!response.value(QStringLiteral("ok")).toBool()) {
      replay_status_value_->setText(QStringLiteral("Cannot load episodes: %1").arg(
        response.value(QStringLiteral("error")).toString(QStringLiteral("unknown error"))));
      return;
    }
    replay_episode_->clear();
    for (const QJsonValue & item : response.value(QStringLiteral("episodes")).toArray()) {
      const QJsonObject episode = item.toObject();
      const int index = episode.value(QStringLiteral("episode_index")).toInt();
      const int frames = episode.value(QStringLiteral("frame_count")).toInt();
      replay_episode_->addItem(QStringLiteral("Episode %1 (%2 frames)").arg(index, 6, 10, QLatin1Char('0')).arg(frames), index);
    }
    const int count = replay_episode_->count();
    replay_button_->setEnabled(count > 0);
    replay_status_value_->setText(count > 0 ? QStringLiteral("Loaded %1 episodes").arg(count) :
      QStringLiteral("No episodes found in this dataset"));
  });
}

void MainWindow::request_replay_seek(int frame_index)
{
  if (replay_timeline_ == nullptr || !replay_timeline_->isEnabled()) {
    return;
  }
  replay_status_value_->setText(QStringLiteral("Seeking frame %1...").arg(frame_index + 1));
  post_json(QStringLiteral("/api/replay/seek"), {
    {QStringLiteral("frame_index"), frame_index}});
}

void MainWindow::update_dashboard_state(const QJsonObject & state)
{
  const QJsonObject capture = state.value(QStringLiteral("capture_status")).toObject();
  const bool capture_available = capture.value(QStringLiteral("available")).toBool(true);
  const bool capture_running = capture.value(QStringLiteral("running")).toBool(false);
  QString capture_status = QStringLiteral("Idle");
  if (!capture_available) {
    capture_status = QStringLiteral("Unavailable");
  } else if (capture_running) {
    capture_status = QStringLiteral("Writing");
  } else if (!capture.value(QStringLiteral("returncode")).isNull() &&
             capture.value(QStringLiteral("returncode")).isDouble()) {
    capture_status = QStringLiteral("Stopped (code %1)").arg(capture.value(QStringLiteral("returncode")).toInt());
  }
  if (!lerobot_export_in_progress_ && !capture_status_override_active_) {
    capture_status_value_->setText(capture_status);
  }
  capture_running_ = capture_running;
  update_capture_toggle();
  const QString capture_dataset_path = capture.value(QStringLiteral("dataset_dir")).toString();
  if (!capture_dataset_path.isEmpty()) {
    capture_dataset_path_ = capture_dataset_path;
  } else if (!capture_running && !capture.value(QStringLiteral("selected_existing_dataset")).toBool(false)) {
    capture_dataset_path_.clear();
  }
  dataset_path_value_->setText(QStringLiteral("Dataset Path %1").arg(
    capture_dataset_path_.isEmpty() ? QStringLiteral("-") : capture_dataset_path_));
  const bool selected_existing = capture.value(QStringLiteral("selected_existing_dataset")).toBool(false);
  capture_mode_->setEnabled(!capture_running_);
  if (selected_existing && !capture_running_ && capture_task_->isEnabled() &&
    !continued_dataset_annotation_dirty_)
  {
    apply_existing_dataset_selection(capture);
  }
  update_capture_toggle();
  if (replay_dataset_path_->text().isEmpty() && !capture_dataset_path_.isEmpty()) {
    replay_dataset_path_->setText(capture_dataset_path_);
    request_replay_episodes();
  }
  const QJsonObject flow = state.value(QStringLiteral("flow_status")).toObject();
  set_text_preserving_scroll(topics_text_, pretty_json(flow.value(QStringLiteral("topics"))));
  set_text_preserving_scroll(topology_text_, pretty_json(state.value(QStringLiteral("topology_graph"))));
  set_text_preserving_scroll(quality_text_, pretty_json(state.value(QStringLiteral("quality_status"))));
  const QJsonValue drop_reason = state.value(QStringLiteral("drop_reason"));
  const QString drop_reason_text = pretty_json(drop_reason);
  set_text_preserving_scroll(drop_reason_text_, drop_reason_text);
  set_text_preserving_scroll(replay_status_text_, pretty_json(state.value(QStringLiteral("replay_status"))));

  const QJsonObject telemetry = state.value(QStringLiteral("telemetry")).toObject();
  const QJsonObject latest = telemetry.value(QStringLiteral("latest")).toObject();
  const QJsonArray telemetry_history = telemetry.value(QStringLiteral("history")).toArray();
  const QString telemetry_mode = telemetry.value(QStringLiteral("mode")).toString();
  const bool replay_mode = telemetry_mode == QStringLiteral("replay");
  const QJsonObject cameras = state.value(QStringLiteral("cameras")).toObject();
  const QJsonObject joint_flow = flow.value(QStringLiteral("topics")).toObject().value(
    QStringLiteral("/joint_states")).toObject();
  const bool joint_seen = joint_flow.value(QStringLiteral("seen")).toBool(false);
  const bool joint_active = joint_flow.value(QStringLiteral("active")).toBool(false);
  const double joint_age = joint_flow.value(QStringLiteral("age_s")).toDouble(-1.0);
  const QString joint_detail = joint_active ?
    QStringLiteral("active · %1 s").arg(joint_age, 0, 'f', 2) :
    (joint_seen ? QStringLiteral("stale · %1 s").arg(joint_age, 0, 'f', 2) :
    QStringLiteral("unseen"));
  set_health_chip(robot_health_value_, QStringLiteral("Robot"), joint_seen, !joint_active, joint_detail);
  const auto update_camera_health = [replay_mode, &cameras](
    const QString & name, const QString & label, QLabel * value) {
      const QJsonObject camera = cameras.value(name).toObject();
      const bool valid = camera.value(QStringLiteral("valid")).toBool(false);
      const double age = camera.value(QStringLiteral("age_s")).toDouble(-1.0);
      const bool stale = valid && !replay_mode && age > 0.50;
      const QString detail = !valid ? QStringLiteral("unavailable") :
        (replay_mode ? QStringLiteral("replay") :
        QStringLiteral("%1 s").arg(age, 0, 'f', 2));
      set_health_chip(value, label, valid, stale, detail);
    };
  update_camera_health(QStringLiteral("external"), QStringLiteral("Scene"), scene_camera_health_value_);
  update_camera_health(QStringLiteral("wrist"), QStringLiteral("Wrist"), wrist_camera_health_value_);
  const bool capture_finished_with_error = capture.value(QStringLiteral("returncode")).isDouble() &&
    capture.value(QStringLiteral("returncode")).toInt() != 0;
  const QString writer_detail = !capture_available ? QStringLiteral("unavailable") :
    (capture_running ? QStringLiteral("writing") :
    (capture_finished_with_error ? QStringLiteral("stopped with error") : QStringLiteral("ready")));
  set_health_chip(
    writer_health_value_, QStringLiteral("Writer"), capture_available,
    capture_finished_with_error, writer_detail);
  if (replay_mode != replay_mode_active_) {
    replay_mode_active_ = replay_mode;
    qpos_chart_->clear();
    qvel_chart_->clear();
    effort_chart_->clear();
  }
  if (live_model_ && replay_model_) {
    live_model_->setEnabled(!replay_mode);
    replay_model_->setEnabled(replay_mode);
  }
  const QJsonObject replay_status = state.value(QStringLiteral("replay_status")).toObject();
  const QString replay_status_name = replay_status.value(QStringLiteral("status")).toString();
  const int replay_episode_index = replay_status.value(QStringLiteral("episode_index")).toInt(-1);
  const int replay_published_frames = replay_status.value(QStringLiteral("published_frames")).toInt(-1);
  const int replay_frame_count = replay_status.value(QStringLiteral("frame_count")).toInt(0);
  const int replay_frame_index = replay_status.value(QStringLiteral("frame_index")).toInt(-1);
  const double replay_frame_timestamp = replay_status.value(QStringLiteral("timestamp")).toDouble(-1.0);
  const double replay_start_timestamp = replay_status.value(QStringLiteral("start_timestamp")).toDouble(-1.0);
  const bool replay_running = replay_status_name == QStringLiteral("running");
  const bool replay_paused = replay_status_name == QStringLiteral("paused");
  replay_pause_button_->setEnabled(replay_running);
  replay_resume_button_->setEnabled(replay_paused);
  replay_stop_button_->setEnabled(replay_running || replay_paused);
  const bool timeline_enabled = (replay_running || replay_paused) && replay_frame_count > 0;
  replay_timeline_->setEnabled(timeline_enabled);
  {
    const QSignalBlocker blocker(replay_timeline_);
    replay_timeline_->setRange(0, std::max(0, replay_frame_count - 1));
    if (!replay_timeline_dragging_ && replay_frame_index >= 0) {
      replay_timeline_->setValue(std::clamp(replay_frame_index, 0, replay_timeline_->maximum()));
    }
  }
  if (!replay_timeline_dragging_) {
    const QString frame_text = replay_frame_index >= 0 ?
      QStringLiteral("Frame %1 / %2").arg(replay_frame_index + 1).arg(replay_frame_count) :
      QStringLiteral("Frame - / %1").arg(replay_frame_count);
    const QString time_text = replay_frame_timestamp >= 0.0 && replay_start_timestamp >= 0.0 ?
      QStringLiteral("t = %1 s").arg(replay_frame_timestamp - replay_start_timestamp, 0, 'f', 3) :
      QStringLiteral("t = -");
    replay_progress_value_->setText(QStringLiteral("%1 · %2").arg(frame_text, time_text));
  }
  const bool replay_started = replay_status_name == QStringLiteral("started") ||
    (replay_status_name == QStringLiteral("running") &&
    last_replay_status_name_ != QStringLiteral("running") &&
    last_replay_status_name_ != QStringLiteral("paused"));
  if (replay_started || replay_episode_index != replay_episode_index_) {
    replay_timestamp_ = -1.0;
    external_replay_camera_timestamp_ = -1.0;
    wrist_replay_camera_timestamp_ = -1.0;
    replay_episode_index_ = replay_episode_index;
    replay_frame_index_ = -1;
    qpos_chart_->clear();
    qvel_chart_->clear();
    effort_chart_->clear();
  }
  last_replay_status_name_ = replay_status_name;
  const double timestamp = latest.value(QStringLiteral("timestamp")).toDouble(-1.0);
  const bool replay_frame_jump = replay_frame_index_ >= 0 && replay_frame_index >= 0 &&
    (replay_frame_index < replay_frame_index_ || replay_frame_index > replay_frame_index_ + 1);
  if (replay_frame_jump) {
    qpos_chart_->replace_history(telemetry_history, QStringLiteral("qpos"));
    qvel_chart_->replace_history(telemetry_history, QStringLiteral("qvel"));
    effort_chart_->replace_history(telemetry_history, QStringLiteral("effort"));
    external_replay_camera_timestamp_ = -1.0;
    wrist_replay_camera_timestamp_ = -1.0;
  }
  if (replay_mode && (timestamp != replay_timestamp_ || replay_frame_index != replay_frame_index_)) {
    replay_timestamp_ = timestamp;
    replay_frame_index_ = replay_frame_index;
    const std::vector<double> qpos = json_numbers(latest.value(QStringLiteral("qpos")));
    const std::vector<double> qvel = json_numbers(latest.value(QStringLiteral("qvel")));
    const std::vector<double> effort = json_numbers(latest.value(QStringLiteral("effort")));
    const std::vector<std::string> names = replay_joint_names(
      latest.value(QStringLiteral("joint_names")).toArray());
    if (names.size() == qpos.size() && !names.empty()) {
      qpos_chart_->set_joint_names(names);
      qvel_chart_->set_joint_names(names);
      effort_chart_->set_joint_names(names);
    }
    if (!replay_frame_jump) {
      qpos_chart_->append(timestamp, qpos);
      qvel_chart_->append(timestamp, qvel);
      effort_chart_->append(timestamp, effort);
    }
    if (names.size() != qpos.size() || names.empty()) {
      replay_status_value_->setText(
        QStringLiteral("Replay pose blocked: recording has no joint_names"));
    } else {
      sensor_msgs::msg::JointState replay_state;
      replay_state.header.stamp = node_->now();
      replay_state.name = names;
      replay_state.position = qpos;
      replay_state.velocity = qvel;
      replay_state.effort = effort;
      const QJsonValue gripper = latest.value(QStringLiteral("gripper"));
      if (gripper.isDouble()) {
        replay_state.name.push_back("finger_joint");
        replay_state.position.push_back(gripper.toDouble());
        replay_state.velocity.push_back(0.0);
        replay_state.effort.push_back(0.0);
      }
      replay_joint_state_publisher_->publish(replay_state);
    }
  }

  const auto load_replay_camera = [this, &cameras](const QString & name, QLabel * label, double & last_timestamp) {
    const QJsonObject camera = cameras.value(name).toObject();
    const double timestamp = camera.value(QStringLiteral("last_timestamp")).toDouble(-1.0);
    if (!camera.value(QStringLiteral("valid")).toBool() || timestamp <= last_timestamp) { return; }
    last_timestamp = timestamp;
    QNetworkRequest request(QUrl(
      QString::fromLatin1(kDashboardUrl) + QStringLiteral("/api/camera/") + name));
    configure_network_request(request, 3000);
    const auto reply = network_->get(request);
    connect(reply, &QNetworkReply::finished, this, [reply, label]() {
      QImage image;
      image.loadFromData(reply->readAll());
      reply->deleteLater();
      if (!image.isNull()) {
        label->setPixmap(QPixmap::fromImage(image).scaled(label->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
      }
    });
  };
  if (replay_mode) {
    load_replay_camera(QStringLiteral("external"), external_camera_label_, external_replay_camera_timestamp_);
    load_replay_camera(QStringLiteral("wrist"), wrist_camera_label_, wrist_replay_camera_timestamp_);
  }
}

void MainWindow::request_existing_dataset()
{
  if (capture_running_) {
    return;
  }
  auto * dialog = new QFileDialog(this, QStringLiteral("Select original qpos_gripper dataset"));
  dialog->setFileMode(QFileDialog::Directory);
  dialog->setOption(QFileDialog::ShowDirsOnly, true);
  dialog->setOption(QFileDialog::DontUseNativeDialog, true);
  dialog->setAttribute(Qt::WA_DeleteOnClose);
  connect(dialog, &QFileDialog::fileSelected, this, [this](const QString & dataset_dir) {
    post_json(QStringLiteral("/api/capture/select-existing-dataset"),
      {{QStringLiteral("dataset_dir"), dataset_dir}});
  });
  dialog->open();
}

void MainWindow::request_standalone_lerobot_export()
{
  if (capture_running_ || lerobot_export_in_progress_) {
    return;
  }
  auto * dialog = new QFileDialog(this, QStringLiteral("Select cleaned qpos_gripper dataset"));
  dialog->setFileMode(QFileDialog::Directory);
  dialog->setOption(QFileDialog::ShowDirsOnly, true);
  dialog->setOption(QFileDialog::DontUseNativeDialog, true);
  dialog->setAttribute(Qt::WA_DeleteOnClose);
  connect(dialog, &QDialog::rejected, this, [this]() {
    show_temporary_capture_status(QStringLiteral("LeRobot export dataset selection cancelled"));
  });
  connect(dialog, &QDialog::accepted, this, [this, dialog]() {
    const QStringList selected_files = dialog->selectedFiles();
    if (selected_files.isEmpty()) {
      show_temporary_capture_status(QStringLiteral("LeRobot export dataset selection missing"));
      return;
    }
    const QString dataset_dir = selected_files.constFirst();
    QTimer::singleShot(0, this, [this, dataset_dir]() {
      QDir parent(dataset_dir);
      parent.cdUp();
      QDir stage(parent);
      stage.cdUp();
      if (QFileInfo(dataset_dir).fileName() != QStringLiteral("qpos_gripper") ||
        stage.dirName() != QStringLiteral("cleaned") ||
        !QFileInfo(QDir(dataset_dir).filePath(QStringLiteral("meta/episodes.jsonl"))).isFile())
      {
        QMessageBox::warning(this, QStringLiteral("Invalid Export Dataset"),
          QStringLiteral("Select cleaned/<mode>/qpos_gripper with episode metadata.\n\nSelected:\n%1")
            .arg(dataset_dir));
        return;
      }
      bool accepted = false;
      const QString profile = QInputDialog::getItem(
        this, QStringLiteral("LeRobot Profile"), QStringLiteral("Profile"),
        {QStringLiteral("ACT"), QStringLiteral("VLA")}, 0, false, &accepted);
      if (accepted) {
        request_lerobot_export(dataset_dir, profile.toLower());
      } else {
        show_temporary_capture_status(QStringLiteral("LeRobot export profile selection cancelled"));
      }
    });
  });
  dialog->open();
}

void MainWindow::start_control_services()
{
  if (control_services_state_ != ControlServicesState::Stopped) {
    return;
  }
  if (mode_status_received_) {
    control_services_status_value_->setText(
      QStringLiteral("Mode Manager is externally managed; start unavailable"));
    update_control_services_button();
    return;
  }

  control_services_state_ = ControlServicesState::CheckingExternalApi;
  control_services_status_value_->setText(QStringLiteral("Checking HTTP API ownership..."));
  control_services_timeout_timer_->start(1500);
  update_control_services_button();
  check_control_api_health();
}

void MainWindow::check_control_api_health()
{
  QNetworkRequest request(QUrl(QString::fromLatin1(kControlApiHealthUrl)));
  configure_network_request(request, 1500);
  const auto reply = network_->get(request);
  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    const bool healthy = reply->error() == QNetworkReply::NoError;
    reply->deleteLater();
    if (control_services_state_ == ControlServicesState::CheckingExternalApi) {
      control_services_timeout_timer_->stop();
      if (healthy) {
        control_services_state_ = ControlServicesState::Stopped;
        control_services_status_value_->setText(
          QStringLiteral("HTTP API is externally managed; start unavailable"));
        update_control_services_button();
        return;
      }

      control_api_pid_ = 0;
      control_api_pid_ = start_owned_process(
        QStringLiteral("ros2"),
        {QStringLiteral("run"), QStringLiteral("ur5e_http_api"), QStringLiteral("run_api")});
      if (control_api_pid_ <= 0)
      {
        fail_control_services_start(QStringLiteral("Could not start HTTP API"));
        return;
      }
      services_owned_ = true;
      control_services_state_ = ControlServicesState::StartingApi;
      control_services_status_value_->setText(QStringLiteral("Starting HTTP API..."));
      control_services_timeout_timer_->start(10000);
      update_control_services_button();
      QTimer::singleShot(250, this, &MainWindow::check_control_api_health);
      return;
    }

    if (control_services_state_ != ControlServicesState::StartingApi) {
      return;
    }
    if (healthy) {
      start_control_mode_manager();
      return;
    }
    QTimer::singleShot(250, this, &MainWindow::check_control_api_health);
  });
}

void MainWindow::start_control_mode_manager()
{
  if (control_services_state_ != ControlServicesState::StartingApi) {
    return;
  }
  if (!process_is_running(control_api_pid_)) {
    fail_control_services_start(QStringLiteral("HTTP API exited before becoming ready"));
    return;
  }
  control_mode_manager_pid_ = 0;
  control_mode_manager_pid_ = start_owned_process(
    QStringLiteral("ros2"),
    {QStringLiteral("run"), QStringLiteral("ur5e_mode_manager"), QStringLiteral("mode_manager")});
  if (control_mode_manager_pid_ <= 0)
  {
    fail_control_services_start(QStringLiteral("Could not start Mode Manager"));
    return;
  }
  control_services_state_ = ControlServicesState::StartingModeManager;
  control_services_status_value_->setText(QStringLiteral("Starting Mode Manager..."));
  control_services_timeout_timer_->start(10000);
  update_control_services_button();
}

void MainWindow::stop_control_services()
{
  if (!services_owned_) {
    if (recover_residual_control_services()) {
      return;
    }
    control_services_status_value_->setText(
      QStringLiteral("No Qt-owned control services to stop"));
    update_control_services_button();
    return;
  }
  if (control_services_state_ == ControlServicesState::StartingApi) {
    control_services_timeout_timer_->stop();
    control_services_state_ = ControlServicesState::StoppingApi;
    control_services_status_value_->setText(QStringLiteral("Stopping owned HTTP API..."));
    owned_process_stop_attempts_ = 0;
    request_process_stop(control_api_pid_);
    check_owned_control_processes_stopped();
    return;
  }
  if (control_services_state_ == ControlServicesState::StartingModeManager) {
    control_services_timeout_timer_->stop();
    control_services_state_ = ControlServicesState::StoppingModeManager;
    control_services_status_value_->setText(QStringLiteral("Stopping owned Mode Manager..."));
    owned_process_stop_attempts_ = 0;
    request_process_stop(control_mode_manager_pid_);
    check_owned_control_processes_stopped();
    return;
  }
  if (control_services_state_ != ControlServicesState::Running) {
    control_services_status_value_->setText(QStringLiteral("Stop already in progress"));
    return;
  }
  control_services_state_ = ControlServicesState::WaitingForIdle;
  control_services_status_value_->setText(QStringLiteral("Requesting IDLE before shutdown..."));
  control_services_timeout_timer_->start(10000);
  update_control_services_button();
  request_mode(QStringLiteral("idle"));
}

bool MainWindow::recover_residual_control_services()
{
  const ResidualControlServices residual = find_residual_control_services();
  if (residual.empty()) {
    return false;
  }
  QStringList services;
  if (residual.mode_manager_pid > 0) {
    services.push_back(QStringLiteral("Mode Manager (PID %1)").arg(residual.mode_manager_pid));
  }
  if (residual.http_api_pid > 0) {
    services.push_back(QStringLiteral("HTTP API (PID %1)").arg(residual.http_api_pid));
  }
  QDialog recover_dialog(this);
  recover_dialog.setWindowTitle(QStringLiteral("Recover Residual Services"));
  auto * recover_dialog_layout = new QVBoxLayout(&recover_dialog);
  auto * recover_message = new QLabel(
    QStringLiteral("Stop residual control services started by an earlier UI session?\n\n%1")
      .arg(services.join(QLatin1Char('\n'))), &recover_dialog);
  recover_message->setWordWrap(true);
  recover_dialog_layout->addWidget(recover_message);

  auto * recover_dialog_buttons = new QHBoxLayout;
  auto * recover_yes = new QPushButton(QStringLiteral("Yes"), &recover_dialog);
  auto * recover_no = new QPushButton(QStringLiteral("No"), &recover_dialog);
  recover_yes->setDefault(true);
  recover_dialog_buttons->addWidget(recover_yes);
  recover_dialog_buttons->addWidget(recover_no);
  recover_dialog_layout->addLayout(recover_dialog_buttons);
  QObject::connect(recover_yes, &QPushButton::clicked, &recover_dialog, &QDialog::accept);
  QObject::connect(recover_no, &QPushButton::clicked, &recover_dialog, &QDialog::reject);

  if (recover_dialog.exec() != QDialog::Accepted) {
    control_services_status_value_->setText(QStringLiteral("Residual control services not stopped"));
    update_control_services_button();
    return true;
  }

  control_mode_manager_pid_ = residual.mode_manager_pid;
  control_api_pid_ = residual.http_api_pid;
  services_owned_ = true;
  control_services_timeout_timer_->stop();
  owned_process_stop_attempts_ = 0;
  if (control_mode_manager_pid_ > 0) {
    control_services_state_ = ControlServicesState::StoppingModeManager;
    control_services_status_value_->setText(QStringLiteral("Stopping residual Mode Manager..."));
    request_process_stop(control_mode_manager_pid_);
  } else {
    control_services_state_ = ControlServicesState::StoppingApi;
    control_services_status_value_->setText(QStringLiteral("Stopping residual HTTP API..."));
    request_process_stop(control_api_pid_);
  }
  update_control_services_button();
  check_owned_control_processes_stopped();
  return true;
}

void MainWindow::stop_owned_mode_manager()
{
  if (control_services_state_ != ControlServicesState::WaitingForIdle) {
    return;
  }
  control_services_state_ = ControlServicesState::StoppingModeManager;
  control_services_status_value_->setText(QStringLiteral("Stopping owned Mode Manager..."));
  update_control_services_button();
  owned_process_stop_attempts_ = 0;
  request_process_stop(control_mode_manager_pid_);
  check_owned_control_processes_stopped();
}

void MainWindow::stop_owned_control_api()
{
  control_services_state_ = ControlServicesState::StoppingApi;
  control_services_status_value_->setText(QStringLiteral("Stopping owned HTTP API..."));
  update_control_services_button();
  owned_process_stop_attempts_ = 0;
  request_process_stop(control_api_pid_);
  check_owned_control_processes_stopped();
}

void MainWindow::check_owned_control_processes_stopped()
{
  if (control_services_state_ == ControlServicesState::StoppingModeManager) {
    if (process_is_running(control_mode_manager_pid_)) {
      ++owned_process_stop_attempts_;
      if (owned_process_stop_attempts_ == 30) {
        request_process_stop(control_mode_manager_pid_, SIGTERM);
      } else if (owned_process_stop_attempts_ == 60) {
        request_process_stop(control_mode_manager_pid_, SIGKILL);
      }
      QTimer::singleShot(100, this, &MainWindow::check_owned_control_processes_stopped);
      return;
    }
    control_mode_manager_pid_ = 0;
    stop_owned_control_api();
    return;
  }
  if (control_services_state_ == ControlServicesState::StoppingApi) {
    if (process_is_running(control_api_pid_)) {
      ++owned_process_stop_attempts_;
      if (owned_process_stop_attempts_ == 30) {
        request_process_stop(control_api_pid_, SIGTERM);
      } else if (owned_process_stop_attempts_ == 60) {
        request_process_stop(control_api_pid_, SIGKILL);
      }
      QTimer::singleShot(100, this, &MainWindow::check_owned_control_processes_stopped);
      return;
    }
    control_api_pid_ = 0;
    finish_control_services_stop(QStringLiteral("Control services stopped"));
  }
}

void MainWindow::fail_control_services_start(const QString & reason)
{
  control_services_timeout_timer_->stop();
  owned_process_stop_attempts_ = 0;
  if (control_mode_manager_pid_ > 0) {
    services_owned_ = true;
    control_services_state_ = ControlServicesState::StoppingModeManager;
    control_services_status_value_->setText(QStringLiteral(
      "Control-service start failed; stopping Mode Manager: %1").arg(reason));
    request_process_stop(control_mode_manager_pid_);
    update_control_services_button();
    check_owned_control_processes_stopped();
    return;
  }
  if (control_api_pid_ > 0) {
    services_owned_ = true;
    control_services_state_ = ControlServicesState::StoppingApi;
    control_services_status_value_->setText(QStringLiteral(
      "Control-service start failed; stopping HTTP API: %1").arg(reason));
    request_process_stop(control_api_pid_);
    update_control_services_button();
    check_owned_control_processes_stopped();
    return;
  }
  finish_control_services_stop(QStringLiteral("Control-service start failed: %1").arg(reason));
}

void MainWindow::finish_control_services_stop(const QString & status)
{
  control_mode_manager_pid_ = 0;
  control_api_pid_ = 0;
  services_owned_ = false;
  mode_status_received_ = false;
  control_services_timeout_timer_->stop();
  control_services_state_ = ControlServicesState::Stopped;
  control_services_status_value_->setText(status);
  update_control_services_button();
}

void MainWindow::update_control_services_button()
{
  if (control_services_button_ == nullptr) {
    return;
  }
  control_services_button_->setText(QStringLiteral("Start"));
  control_services_button_->setEnabled(control_services_state_ == ControlServicesState::Stopped);
  if (stop_control_services_button_ != nullptr) {
    stop_control_services_button_->setText(QStringLiteral("Stop"));
    stop_control_services_button_->setEnabled(true);
  }
}

void MainWindow::set_mode_buttons_enabled(bool enabled)
{
  for (QPushButton * button : {idle_button_, auto_button_, api_button_, teleop_button_, hil_button_}) {
    if (button != nullptr) {
      button->setEnabled(enabled);
    }
  }
}

void MainWindow::handle_control_services_timeout()
{
  if (control_services_state_ == ControlServicesState::CheckingExternalApi) {
    control_services_state_ = ControlServicesState::Stopped;
    control_services_status_value_->setText(QStringLiteral("HTTP API ownership check timed out"));
  } else if (
    control_services_state_ == ControlServicesState::StartingApi ||
    control_services_state_ == ControlServicesState::StartingModeManager)
  {
    fail_control_services_start(QStringLiteral("startup timed out"));
    return;
  } else if (control_services_state_ == ControlServicesState::WaitingForIdle) {
    control_services_state_ = ControlServicesState::StoppingModeManager;
    owned_process_stop_attempts_ = 0;
    control_services_status_value_->setText(
      QStringLiteral("Forcing Mode Manager shutdown (IDLE not confirmed)..."));
    control_services_timeout_timer_->stop();
    request_process_stop(control_mode_manager_pid_);
    check_owned_control_processes_stopped();
    return;
  } else if (
    control_services_state_ == ControlServicesState::StoppingModeManager ||
    control_services_state_ == ControlServicesState::StoppingApi)
  {
    control_services_status_value_->setText(
      QStringLiteral("Stop escalation still in progress..."));
    control_services_timeout_timer_->stop();
    if (control_services_state_ == ControlServicesState::StoppingModeManager) {
      request_process_stop(control_mode_manager_pid_, SIGKILL);
    } else {
      request_process_stop(control_api_pid_, SIGKILL);
    }
  }
  update_control_services_button();
}

void MainWindow::request_mode(const QString & mode)
{
  std_msgs::msg::String request;
  request.data = mode.toStdString();
  mode_request_publisher_->publish(request);
}

}  // namespace data_collection_rviz_panel
