# UR5e 真机测试指南

本指南验证 Qt/RViz 面板、真机 ROS 图、压缩相机和数据写入链路。面板本身不向真实机器人控制器发布运动命令；Capture 的 `Start Capture` 会启动数据采集器，因此必须在安全确认后执行。

## 1. 安全与前置条件

1. 真机处于安全姿态，工作空间无人员和障碍物，急停可用。
2. 已确认机器人驱动、控制器和相机驱动由专用终端启动，且只启动一份。
3. 所有终端使用同一个 ROS 2 环境和 `ROS_DOMAIN_ID`。
4. 已完成工作区构建：

```bash
source /opt/ros/humble/setup.bash
source /home/crz/src/install/setup.bash
```

不要在真机测试时启动仿真 Gazebo 或向真实控制器 remap 回放命令。

## 2. 启动真机 ROS 节点

按现场使用的 Universal Robots 驱动命令启动真机驱动。驱动需要提供 `/joint_states`、`/tf` 和 `/tf_static`。面板启动时默认会从 `my_description` 启动一个只读的 `robot_state_publisher`，为 RViz 模型提供 `/robot_description`。面板把机械臂 `/joint_states` 和 Robotiq `/robotiq_2f_gripper/joint_states` 转发到专用模型状态话题，不会向控制器写入状态。

如果项目的模式管理器尚未运行，另开终端启动：

```bash
source /opt/ros/humble/setup.bash
source /home/crz/src/install/setup.bash
ros2 run ur5e_mode_manager mode_manager
```

确认 ROS 图和机器人描述：

```bash
ros2 topic list | rg '^/(joint_states|tf|tf_static|robot_description)$'
ros2 topic echo /joint_states --once
ros2 topic echo /robotiq_2f_gripper/joint_states --once
ros2 topic echo /robot_description --once
ros2 topic echo /tf --once
```

若已有驱动侧 `robot_state_publisher`，可以在启动面板时设置 `start_live_state_publisher:=false`，避免重复发布 TF；否则保留默认值 `true`。

## 3. 验证压缩相机

真机默认话题必须是：

```text
/camera2/scene_camera/color/image_raw/compressed
/camera1/wrist_camera/color/image_raw/compressed
```

逐项检查：

```bash
ros2 topic info /camera2/scene_camera/color/image_raw/compressed
ros2 topic info /camera1/wrist_camera/color/image_raw/compressed
ros2 topic echo /camera2/scene_camera/color/image_raw/compressed --once
ros2 topic echo /camera1/wrist_camera/color/image_raw/compressed --once
ros2 topic hz /camera2/scene_camera/color/image_raw/compressed
ros2 topic hz /camera1/wrist_camera/color/image_raw/compressed
```

消息类型应为 `sensor_msgs/msg/CompressedImage`。`format` 中出现 `jpeg` 或 `rgb8; jpeg compressed` 属于兼容状态，Qt 面板和 collector 都按 JPEG 压缩流读取 `data` 字段。

## 4. 启动 Qt/RViz 面板

真机已经有真实 `robot_state_publisher` 时，仍必须保留面板自带的回放 state publisher。
它使用独立的 `replay/` TF 前缀，只订阅 `/data_collection/replay/joint_states`，不会与真实机器人 TF 或控制链路冲突：

```bash
source /opt/ros/humble/setup.bash
source /home/crz/src/install/setup.bash

QT_QPA_PLATFORM=xcb ros2 launch data_collection_rviz_panel \
  data_collection_rviz_panel.launch.py
```

面板默认会从 `/joint_states` 驱动实时 UR5e 模型。若真机已有完整模型发布器，可以关闭 live state publisher；不要关闭 replay state publisher：

```bash
QT_QPA_PLATFORM=xcb ros2 launch data_collection_rviz_panel \
  data_collection_rviz_panel.launch.py \
  start_live_state_publisher:=false
```

面板启动后检查：

1. 左侧 `Robot State (RViz2)` 显示真机 UR5e 模型。
2. 两个相机区域分别显示 scene 和 wrist 图像。
3. 右侧 qpos/qvel/effort 曲线开始更新。
4. 顶部 Robot、Scene、Wrist、Writer 健康条均为绿色；Robot 显示 joint state 消息年龄，两个相机显示最新帧年龄，Writer 显示 `ready` 或 `writing`。
5. `Window` 菜单可切换 `Full Screen`、`Maximized`、`Windowed`。
6. `Capture` 区域显示 `Write status: Idle`，此时尚未写入数据。

健康条含义：

- 红色：对应输入未见、相机不可用、写入器不可用，禁止开始真机采集并先排障。
- 黄色：输入过期或上一次写入异常；确认原因后再开始。
- 绿色：输入正在活动或写入器已就绪。

独立 RViz 可以同时打开，不需要关闭 Qt 面板：

```bash
rviz2 -d /home/crz/src/my_description/rviz/my_robot.rviz
```

两者必须使用相同的 `ROS_DOMAIN_ID`。不要同时启动两份 Qt 面板或两份 dashboard backend。

## 5. 只读链路验收

在不启动采集的情况下，依次确认：

| 项目 | 通过标准 |
| --- | --- |
| 机械臂模型 | RViz 模型完整，无 `No transform` |
| scene 相机 | 图像稳定更新，画面方向正确 |
| wrist 相机 | 图像稳定更新，画面方向正确 |
| qpos | 六个关节曲线随手动/驱动状态变化 |
| qvel | 静止时接近 0，运动时有变化 |
| effort | 有数据时显示变化，没有数据时保持等待状态 |
| Write status | 未采集时为 `Idle` |
| Drop Reason | 无丢帧时显示 `No drop events received` |
| mode manager | 面板切换按钮发布请求，状态栏能收到反馈 |
| 夹爪状态 | `/robotiq_2f_gripper/joint_states` 中有 `finger_joint`，模型指尖随开合变化 |

## 6. 真正开始写入数据

确认第 5 节全部通过后，准备数据目录。默认目录为：

```text
~/ur5e_ws/datasets/ui_capture
```

在面板 Capture 区域：

1. 选择 `Mode`，通常真机遥操作使用 `teleop`。
2. 填写任务名。
3. 点击 `New Task`。
4. 确认 Dataset Path 已更新。
5. 点击 `Start Capture`。
6. 确认 `Write status` 变为 `Writing`。
7. 进行短动作测试，建议先采集 5 到 10 秒。
8. 点击 `Stop Capture`。
9. 确认状态回到 `Idle` 或显示带返回码的停止状态。

采集器使用压缩图像格式写入数据，默认参数为 JPEG、质量 75。不要在第一次真机验证时修改采样率、同步阈值或相机话题。

## 7. 数据文件检查

根据面板显示的 Dataset Path 检查：

```bash
DATASET_DIR="<面板显示的 Dataset Path>"
find "$DATASET_DIR" -maxdepth 3 -type f | sort
python3 -m data_collection_pkg.cli quality "$DATASET_DIR" --profile basic
```

检查点：

- `meta/episodes.jsonl` 存在且包含 episode。
- episode JSONL 中包含 `qpos` 和相机 `data_path`。
- 相机文件可以被 JPEG 解码。
- 没有异常大量的 `drop_reason`。
- 如果出现丢帧，先查看面板 `Drop Reason`，再调整同步或相机发布频率。

## 8. 回放安全边界

Qt 面板的 Replay 只更新曲线、相机和 `/data_collection/replay/joint_states`，不会向真实机器人控制器发布轨迹。真机测试期间不要启动 `data_collection_replay.launch.py` 的 URSim 控制适配器，也不要把 replay 话题 remap 到真实控制器话题。

回放区的 Dataset Path 必须指向包含 `meta/episodes.jsonl` 的叶目录，例如：

```text
/home/crz/Videos/teleop_segment_01_20260804_172530/original/teleop/qpos_gripper
```

可以直接填写后按 Enter/Load，也可以用 `Browse...` 选择目录。成功加载后 Episode 下拉框会列出帧数；Replay 按钮在没有 episode 时保持禁用，加载失败原因会显示在回放区。

回放开始后，Timeline 会显示 `当前帧 / 总帧` 与 episode 相对时间。正常播放时仅 Pause、Stop 可用；暂停后仅 Resume、Stop 可用。暂停后拖动 Timeline 并释放，必须同时看到：

1. RViz 回放模型跳转到选中帧姿态；
2. scene 和 wrist 相机跳转到同一帧；
3. 三张曲线刷新到该帧，且纵轴刻度为真实共享数值范围；
4. Timeline 的帧号和相对时间更新。

该操作只调用 dashboard 的 `/api/replay/seek`，只更新
`/data_collection/replay/joint_states` 和可视化缓存，绝不会向真实控制器发布运动命令。

## 9. 故障定位

- 模型不显示：检查 `/robot_description`、`/tf`、`/tf_static` 和 RViz Fixed Frame。
- 相机无图：确认使用的是带 `/compressed` 的 `CompressedImage` 话题，而不是 raw 话题或拼写错误的话题。
- 曲线不动：检查 `/joint_states` 的发布频率和消息内容。
- Write status 一直 Unavailable：确认 dashboard backend 在 `127.0.0.1:8765` 运行。
- Drop Reason 没有内容：没有发生丢帧时显示为空是正常现象；先检查 `Quality` 页签和 collector 日志。
- Qt 与独立 RViz 冲突：确认没有残留的旧面板进程，且两个程序使用相同 `ROS_DOMAIN_ID`。
