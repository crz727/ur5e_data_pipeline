# HDF5 转换使用与格式说明

## 1. 文档范围

本文说明数据管道中的项目自定义 HDF5 v1 转换功能，包括输入要求、Qt 界面操作、命令行/API 用法、文件 schema、校验方式、容量注意事项和故障排查。

HDF5 在本项目中是独立的二进制交换格式，不是某个模型专用的训练格式，也不承诺能够被所有机器人学习框架直接读取。下游程序应依据本文 schema 编写读取器；如果目标框架有自己的 HDF5 约定，应增加单独适配器。

## 2. 数据流边界

```text
original JSONL + 外部图像
        ↓ 质量检查、人工 outcome、清洗
cleaned/<mode>/qpos_gripper
        ↓
项目 HDF5 v1 / LeRobot v3 ACT / LeRobot v3 VLA
```

HDF5 转换只读取 cleaned 数据，不参与实时采集、相机同步、人工标注或清洗。cleaned 数据集只包含通过清洗的 accepted episode；失败或待复核 episode 不会被转换，但清洗报告仍保留其审计记录。

## 3. 前置条件

- 已安装 Python 3、`h5py`、`numpy` 和 `pillow`。
- 输入目录是 `cleaned/<mode>/qpos_gripper`。
- 输入目录包含 `meta/episodes.jsonl`。
- 每个 episode 的 `data_path` 指向目录内存在的 JSONL 文件。
- 每帧包含 7 维 `observation.state`、7 维 `action`、有限数值的时间戳和两路图像。
- 图像路径必须位于输入数据集目录内，且能够被 Pillow 解码。
- 输出文件不存在；转换器不会覆盖已有 `.h5/.hdf5` 文件。

## 4. Qt 界面操作

1. 打开 Qt/RViz 面板，点击 `Convert...`。
2. 选择一个 cleaned `qpos_gripper` 目录。
3. 选择 `HDF5`。
4. 在文件对话框中选择输出位置。未填写扩展名时，UI 自动补充 `.hdf5`。
5. 确认后观察 `HDF5 export queued...` 和 `HDF5 export running...`。
6. 完成时显示 `HDF5 export complete: ...`；失败时显示具体错误。
7. 转换期间使用不确定进度条表示任务仍在运行，不显示伪造百分比。

ACT/VLA 仍输出 LeRobot 目录；HDF5 输出单个文件，三种格式互不覆盖输出路径。

## 5. 命令行用法

```bash
ros2 run data_collection_pkg data_collection convert \
  cleaned/teleop/qpos_gripper \
  --format hdf5 \
  --output-path exports/teleop.hdf5
```

成功时输出 JSON 摘要：

```json
{
  "ok": true,
  "schema": "ur5e_data_pipeline_hdf5",
  "schema_version": 1,
  "episode_count": 10,
  "frame_count": 1767,
  "output_path": "exports/teleop.hdf5"
}
```

旧命令 `convert-jsonl-to-lerobot` 继续用于 ACT/VLA，不用于 HDF5。

## 6. Dashboard API

### 6.1 启动转换

```http
POST /api/capture/export
Content-Type: application/json
```

请求：

```json
{
  "format": "hdf5",
  "cleaned_dataset_dir": "cleaned/teleop/qpos_gripper",
  "output_path": "exports/teleop.hdf5"
}
```

响应状态为 `202`，并返回 `job_id` 和 `status=queued`。

### 6.2 查询状态

```http
GET /api/capture/export/status
```

状态依次可能为 `queued`、`running`、`done` 或 `failed`。成功结果位于 `result.output_path`，失败原因位于 `error`。

### 6.3 预检

```http
POST /api/capture/export/preflight
Content-Type: application/json
```

HDF5 预检确认 `format`、输入目录和输出路径字段存在；真正的 episode、图像和 shape 校验在转换过程中执行。ACT/VLA 预检继续复用 LeRobot 语言和 episode 检查。

## 7. HDF5 v1 文件结构

```text
<dataset>.hdf5
├── meta/
│   ├── episode_index             int64[N]
│   ├── episode_lengths           int64[N]
│   ├── episode_ends              int64[N]
│   ├── feature_manifest          UTF-8 JSON 字符串
│   ├── cleaning_summary          UTF-8 JSON 字符串，可选
│   └── tasks/
│       ├── task_id               UTF-8[N]
│       ├── language_instruction_en UTF-8[N]
│       └── language_instruction_zh UTF-8[N]
└── episodes/
    └── episode_000000/
        ├── observations/
        │   ├── state              float32[T, 7]
        │   ├── ee_pose            float32[T, 7]，可选
        │   ├── joint_velocity     float32[T, 6]，可选
        │   ├── effort              float32[T, 6]，可选
        │   └── images/
        │       ├── top             uint8[T, H, W, 3]
        │       └── wrist           uint8[T, H, W, 3]
        ├── actions                 float32[T, 7]
        ├── timestamps              float64[T]
        ├── frame_index             int64[T]
        └── attributes              episode_index、task、task_id、语言字段等
```

### 7.1 数值字段

- `state` 为 6 个关节位置加 1 个夹爪值，shape 固定为 `[T, 7]`。
- `actions` 为 qpos_gripper action，shape 固定为 `[T, 7]`。
- `timestamps` 单位为秒，保留输入 JSONL 的 observation 时间。
- `frame_index` 保留输入帧索引，不强制从零连续递增。
- 数值字段使用有限值；NaN、Inf、错误维度会使转换失败。

### 7.2 图像字段

- `top` 对应输入 JSONL 的 `images.external`。
- `wrist` 对应输入 JSONL 的 `images.wrist`。
- 转换器从外部 JPEG/PNG 逐帧解码为 RGB。
- HDF5 内部统一为 `uint8`、THWC，即 `[时间, 高度, 宽度, 通道]`。
- 同一路相机在同一 episode 内尺寸变化会失败，不自动 resize。
- 使用 chunk 和 gzip 压缩；不会同时保存 RGB 数组和 JPEG 副本。

### 7.3 可选字段一致性

`ee_pose`、`joint_velocity`、`effort` 如果存在，必须在所有 episode、所有帧中存在且 shape 一致；只在部分数据中出现时转换失败，避免静默补零造成语义错误。

## 8. 校验

可在 Python 中执行：

```python
from data_collection_pkg.dataset.hdf5_verify import verify_hdf5_export

result = verify_hdf5_export("exports/teleop.hdf5", expected_episode_count=10)
assert result["ok"]
assert result["issues"] == []
```

校验包括：schema 名称和版本、meta 索引、episode 数量、必需 dataset、state/action shape、数组长度和 feature manifest JSON。校验通过只表示文件符合项目 HDF5 v1，不表示它自动兼容其他训练框架。

## 9. 容量与性能

RGB 数组比 JPEG 文件大很多。例如 640×480×3 的单帧约 0.88 MiB，两路相机和较长 episode 会快速增加输出体积。转换器采用逐帧读取和追加写入，不把完整数据集加载到内存，但磁盘空间仍应至少预留输出文件大小的 1.2 倍。

如果下游训练器支持外部 JPEG 或视频，LeRobot v3 通常更节省磁盘；HDF5 适合需要数组随机访问、统一交换 schema 或自定义 PyTorch 读取器的场景。

## 10. 常见错误

| 错误 | 原因 | 处理 |
| --- | --- | --- |
| `cleaned dataset must contain meta/episodes.jsonl` | 选中了 original、上级目录或错误目录 | 选择 `cleaned/<mode>/qpos_gripper` |
| `output file already exists` | 输出文件已存在 | 更换文件名，不覆盖旧结果 |
| `data file does not exist` | metadata 中的 `data_path` 无效 | 检查 cleaned 目录是否完整 |
| `missing top/wrist image` | 帧中缺少两路必需图像 | 重新清洗或修复数据后再转换 |
| `image shape changed` | 同一路相机分辨率不一致 | 统一相机输出尺寸后重新生成 cleaned 数据 |
| `optional feature ... only present in some episodes` | 可选字段不完整 | 补齐字段或从 schema 中统一移除 |
| UI 状态 404 | Qt 和 Dashboard 安装版本不一致 | 重新构建两个包并重启 Dashboard/UI |

## 11. 已完成验证

使用真机 cleaned 数据集抽取 10 个 episode 进行转换验证：

- episode 数量：10；
- 总帧数：1767；
- 两路图像 shape：`[T, 480, 640, 3]`；
- state/action/timestamps/图像长度逐 episode 一致；
- `verify_hdf5_export(..., expected_episode_count=10)` 返回 `ok=true`、`issues=[]`；
- Dashboard 异步导出状态从 `queued`、`running` 到 `done` 正常完成。

测试产生的临时 HDF5 文件已删除，原始和 cleaned 数据集未被修改。

## 12. 相关实现

- `data_collection_pkg/dataset/hdf5_schema.py`：schema 常量和 manifest；
- `data_collection_pkg/dataset/hdf5_converter.py`：流式转换；
- `data_collection_pkg/dataset/hdf5_verify.py`：输出校验；
- `visualization/capture_manager.py`：异步任务分发；
- `visualization/web_dashboard.py`：通用导出 API；
- `data_collection_rviz_panel/src/main_window.cpp`：Qt 三格式选择和进度状态。
