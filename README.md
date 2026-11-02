# opv8-bydsong

比亚迪 **23 款宋 Pro DM-i** 在 **PC 版 openpilot（carrotpilot v8）** 上的适配代码与调试记录。

> 本仓库只包含**代码改动与文档**，不包含 openpilot 源码树本身（模型文件单个 111MB，
> 超过 GitHub 100MB 限制）、模型权重、编译产物、虚拟环境，也不包含任何本机配置、
> 参数存储、行车日志或车辆标识信息。

---

## 1. 这个仓库解决什么问题

carrotpilot v8（`carrot2-v8` 分支）自带 BYD 车型，但直接跑在这台 PC 上会连续踩坑：

| # | 问题 | 后果 | 修法 |
| --- | --- | --- | --- |
| 1 | `torque_data/params.toml` 只写了 Han 两款 BYD 的扭矩数据 | 其余 9 款车型（含宋 Pro 23）`get_torque_params()` 抛 `KeyError`，`card` 进程崩 | 在 `substitute.toml` 里让缺失车型借用 `BYD_HAN_DM_20` |
| 2 | `byd/radar_interface.py` 日志路径硬编码 `/data/debug/...` | PC 上没有 `/data` → `PermissionError`，`card` 崩 | 加兜底到 `~/.comma/debug/` |
| 3 | `system/manager/process.py` 的 `PythonProcess.start()` 是 `if self.proc is not None: return` | **任何 Python 进程崩一次就永不被重启**（上游判断的是 `exitcode is None`） | 修正判断，并加 5s 重启退避（否则新旧实例抢 msgq socket 会死循环） |
| 4 | BYD 指纹地址集不全 | 实车有 23 个地址不在指纹里 → 指纹淘汰逻辑把所有候选车淘汰光 → 车辆无法识别 | 补齐 `fingerprints.py` 的地址表 |
| 5 | 双 USB 摄像头无区分能力 | 两颗摄像头 VID/PID/序列号完全相同，`/dev/v4l/by-id` 只有一条链接 | 改为按**画面特征**自动识别角色（鱼眼四角死黑 = 广角） |
| 6 | 广角鱼眼未去畸变 | openpilot 广角通路是纯针孔单应（`get_warp_matrix()` 无畸变项），原始鱼眼图几何错误 | 在 `camerad` 采集阶段用 Kannala-Brandt 模型 `remap` 去畸变 |

另外附带：

- 双路 USB 摄像头带宽限制的实测结论（同一条 USB 2.0 总线上，两路 1080p 起不来）
- 摄像头 UVC 参数读写工具（本机没装 `v4l-utils`，直接用 ioctl 实现）
- 桌面预览器（选摄像头 / 选预览模式 / 自动关锐化便于判焦）

---

## 2. 目录结构

```
overlay/cpv8/         # 需要覆盖到 carrotpilot v8 源码树里的文件（保持原始相对路径）
  tools/webcam/       #   多摄像头采集：camerad / camera / 自动识别 / 去畸变 / 标定
  system/manager/     #   进程管理（崩溃重启修复）
  opendbc_repo/       #   BYD 车型：指纹、扭矩参数、雷达接口
  tools/op.sh         #   编译入口（已加 resolute 白名单）
launch/               # 本机运行入口：启动脚本、参数预设、摄像头工具
  env/                #   songpro23.env（启动环境变量）、wide_lens.json（鱼眼参数）
docs/                 # 适配手册、调研报告、调试记录
AGENTS.md             # 工作区笔记（含踩坑记录与已知偏差）
```

`overlay/` 的目录层级与 openpilot 源码树一致，应用方法见 [APPLY.md](APPLY.md)。

---

## 3. 关键设计说明

### 3.1 摄像头角色自动识别（`tools/webcam/camdetect.py`）

两颗外置摄像头是**同一个 DECXIN 模块，只换了镜头**：VID/PID（`1bcf:2cd1`）、USB 序列号
（都是 `01.00.00`）、支持格式、UVC 控制项全部相同。所以：

- ❌ 不能用 `/dev/v4l/by-id` 区分（只有一条链接，指向后插入的那颗）
- ❌ 不能用 `/dev/videoN`（重插会漂）
- ⚠️ 用 `by-path` 按端口可以，但**换 USB 口就失效**
- ✅ 用**画面特征**：鱼眼是圆形像场、**四角死黑**；普通视角四角有内容

开启 `CAM_AUTODETECT=1` 后，`camerad` 启动时会各抓几帧判定角色，
换口甚至把两颗物理对调都不需要改配置。

### 3.2 鱼眼去畸变（`tools/webcam/lens.py`）

为什么必须做：openpilot 的广角通路全程针孔模型 ——
`common/transformations/model.py:get_warp_matrix()` 只有
`intrinsics @ R @ 外参 @ calib_from_model` 一个 3×3 单应，**全仓没有任何畸变项**
（UI 的 `annotated_camera.cc` 里还留着 `// TODO: use proper perspective transform?`）。

实现要点：

- 使用 OpenCV fisheye（Kannala-Brandt）模型，`initUndistortRectifyMap` 预计算 + 逐帧 `remap`
- 在 **BGR 阶段**（转 NV12 之前）做，`camerad` 里只对 `wideRoadCameraState` 生效
- `D=[0,0,0,0]` 时模型正好退化为纯等距 `r = f·θ`，与实测假设自洽
- ⚠️ 不要用 `cv2.fisheye.estimateNewCameraMatrixForUndistortRectify`：在接近 180° 的鱼眼上
  它会算出退化解（主点变 5.7e16，整帧全黑），必须手工构造新内参 + `fov_scale`

标定：用 `tools/webcam/calib_lens.py` 拍棋盘格，产出 `K`/`D` 覆盖
`launch/env/wide_lens.json`。

### 3.3 双路 USB 摄像头的带宽硬约束（实测）

两颗摄像头挂在同一条 USB 2.0 总线上（整机只有一个 xHCI 控制器）。等时带宽是硬预算：

| 组合 | 结果 |
| --- | --- |
| 1080p + 1080p @20fps | ❌ `VIDIOC_STREAMON: No space left on device` |
| 1080p + 720p @30fps | ❌ 同上 |
| **1080p@20 + 720p@20** | ✅ 双路各 ~19fps |

内核日志对应 `usb 1-10.x: Not enough bandwidth for altsetting N`。
换 USB 口无效（同一条总线）。

---

## 4. 实测环境与硬件结论

测试机：Dell Latitude 5420 Rugged（4 核 8 线程 / 15GB / **Intel UHD Graphics 620**，无独显）。

**结论：这台机器的核显跑不动实时模型。**

```
modelV2.modelExecutionTime = 190 ms/帧   →  理论上限 5.3 Hz
实测 modelV2 ≈ 4.5 Hz，frameDropPerc ≈ 48%（阈值 20%）
```

openpilot 的 `modeldLagging` 事件带 `ET.NO_ENTRY`，掉帧超过 20% 会**硬性禁止激活**，
所以在这台机器上无法 engage。要真正能用需要带独显或更强 CPU 的机器。

顺带排除掉两个"取巧"思路：

- 把相机帧率降到 10fps 迁就模型 → `roadCameraState` 期望 20Hz±20%，
  会触发 `cameraFrameRate`，同样是 `NO_ENTRY`
- 降低相机分辨率 → 不减少模型推理时间

---

## 5. 排查方法论（这次踩坑总结）

| 现象 | 真正原因 | 怎么发现的 |
| --- | --- | --- |
| UI「无法使用 openpilot 等待开始」 | `selfdrived` 的 `canError` 告警，因为 `card` 没发 `carState` | 订阅 `selfdriveState` 读 `alertText1` |
| 方向盘按钮无反应 | `modeldLagging` / `canError` 都是 `NO_ENTRY` 事件 | 读 `events.py` 里事件的事件类型 |
| `card` 进程时有时无 | 崩溃后不重启（本分支 bug），以及后续的抢 socket 死循环 | `managerState` 的 `exitCode`、`ps --ppid` 监控 pid 变化 |

调试手段（都在仓库里可复现）：

```bash
# 实时订阅看谁没在发消息
python -c "import cereal.messaging as m; sm=m.SubMaster(['carParams','carState','selfdriveState']); ..."

# 用真实 CAN 复刻指纹淘汰逻辑
from opendbc.car.fingerprints import _FINGERPRINTS, eliminate_incompatible_cars

# 进程崩溃堆栈（launcher 会落盘）
cat ~/.comma/debug/<进程名>_crash.log
```

---

## 6. 状态

| 项 | 状态 |
| --- | --- |
| 车辆指纹识别 | ✅ `BYD_SONG_PRO_DMI_23`（补全地址后唯一命中） |
| CAN 解析 | ✅ `carState` 90Hz，`canValid=True` |
| panda 安全模式 | ✅ 切到 `byd` |
| 双摄同时出流 | ✅ 路面 1080p@20 + 广角 720p@20 |
| 鱼眼去畸变 | ✅ 已启用，帧率无损 |
| 实时模型 | ❌ 核显算力不足（190ms/帧），无法激活 |
| 标定 | ⏸ 需要车辆实际行驶才会收敛 |

详见 [AGENTS.md](AGENTS.md) 的「已知偏差」章节。
