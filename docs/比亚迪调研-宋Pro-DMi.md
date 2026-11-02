# 比亚迪（23 款宋 Pro DM-i）跑 OpenPilot 调研报告

> 调研时间：2026-10-27｜目标车：**比亚迪 2023 款宋 Pro DM-i（高配，原车带 ACC）**
> 依据：本机 `~/openpilot/cpv8` 源码（carrot2-v8 @ 43a030a）+ GitHub/Gitee 仓库元数据 + 社区教程/视频。
> 所有"代码级"结论都标了在本机源码里的位置，可自行核对。**所有数据以调研当天为准，仓库会变。**

---

## 0. 一句话结论

| 问题 | 结论 |
| --- | --- |
| 哪个分支 BYD 支持最多 | **carrot 系（carrotpilot）最全**；PC 版落地就是本机的 **cpv8（huheas/carrotpilot）**。sunnypilot 系有 `huheas/sunnypilot-pc-byd` 与 `dragonpilot/byd-sp` 两个 PC 移植，但都停在 2026-05 前后。 |
| 能否用原车雷达 | **代码上支持**：`BYD_RADAR=1` 会启用 `radar_interface.py`（读 0x374 雷达目标帧），但**仅 Han/Tang（老平台）在 PT 总线上有雷达数据**，宋 Pro 属于 SONG 平台，雷达在 **CAN-FD 私有总线**，需要 FD 能力 + 正确接线，实测未验证。 |
| 谁在持续更新 | 上游 `ajouatom/openpilot`（carrotpilot）**每天在推**，但它主打现代/起亚；BYD PC 分支基本**几个月一更**。`sunnypilot` 上游极活跃，`MM-X/sunnypilot-pc` 也活跃——**自己合并 BYD 补丁**才是可持续路线。 |
| 怎么调试调参 | 三层：① 车机 UI 开关（`TrafficLightDetectMode`、`DynamicTFollow` 等）② `opendbc/car/byd/tuning.py`（原车 long 平滑、转向角零偏）③ PlotJuggler 看 `carrotMan`/`longitudinalPlan` 曲线。 |
| 红绿灯 / 城市 NOA | **红绿灯有**：carrot 系带 `TrafficLightDetectMode`（0 关 / 1 只停 / 2 停走），本机源码里默认 2。**城市 NOA 没有**：开源生态全是高速/快速路 LKA+ACC，没有可复现的城区 NOA 分支。 |

---

## 1. 分支全景对比（2026-10-27 数据，GitHub API）

| 分支 | 仓库 | Star | 最近推送 | 默认分支 | BYD | PC 版 | 红绿灯 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **cp（上游）** | `ajouatom/openpilot` | **208** | **2026-10-26** | `carrot-wip` | 有代码、非重点 | ❌（需设备） | ✅ Traffic Signal Assist |
| **cpv8（本机）** | `huheas/carrotpilot`（Gitee 同名） | **11** | 2026-05-12 | `carrot2-v8` | ✅ 整合 yysnet 适配 | ✅ | ✅ 继承 |
| sunnypilot-pc-byd | `huheas/sunnypilot-pc-byd` | 0 | 2026-05-13 | `master-new-pc-dev` | ✅ | ✅ | 看 sunnypilot 版本 |
| dragonpilot-byd | `dragonpilot/byd-sp` | 0 | 2025-08-26 | `master` | ✅ | ✅ | 看 dp 版本 |
| sunnypilot-pc（基座） | `MM-X/sunnypilot-pc` | **52** | 2026-10-16 | `master-tici` | ❌ | ✅ | 上游特性 |
| sunnypilot | `sunnypilot/sunnypilot` | **2153** | 2026-10-26 | `master` | ❌（无 BYD） | ❌（C3/C3X） | 部分（Green Light 类） |
| dragonpilot | `dragonpilot/dragonpilot` | **636** | 2026-09-29 | `pre-build` | ❌ | ❌ | 部分 |
| FrogPilot | `FrogAi/FrogPilot` | **567** | 2026-10-23 | `FrogPilot-Staging` | ❌ | ❌ | 部分（见其 Wiki） |

**怎么读这张表**

- **BYD 代码的源头**是 `yysnet` 的 opendbc PR #2058（BYD brand 初始移植）→ 各中文分支再往上叠 PC 适配。
- `carrotpilot`（208★）本身**主打现代/起亚/捷尼赛思**，README 明说 BYD 等厂商"继承自上游、未逐车验证"；但它更新最勤，是**功能与 bug 修的上游**。
- **PC 版真正能一键跑起来的**是 `cpv8`：它把 carrot2-v8 + yysnet 的 BYD 适配 + PC 摄像头/IMU/虚拟显示器整合好了，本机已编译通过。
- `sunnypilot-pc-byd` / `dragonpilot/byd-sp` 是"PC 版 sunnypilot/dragonpilot + BYD"的组合，**2025-08 ~ 2026-05 后没再动**，适合拿来对比或做二选一。

---

## 2. 比亚迪车型支持深度（代码实测）

### 2.1 支持的车型（本机 `opendbc_repo/opendbc/car/byd/values.py`）

```
BYD_HAN_DM_20      BYD_HAN_EV_20      BYD_TANG_DM        BYD_TANG_DMI_21
BYD_SONG_PLUS_DMI_21 / _22 / _23      BYD_SONG_PRO_DMI_22
BYD_QIN_PLUS_DMI_23                    BYD_YUAN_PLUS_DMI_22（Atto3）
```

**注意：没有 `SONG_PRO_DMI_23`**——只有 22 款宋 Pro。你的 23 款大概率能直接认成
`BYD_SONG_PRO_DMI_22`（同平台），认不出时要自己补 fingerprint（见 §7.2）。

### 2.2 平台分组与安全标志（`values.py` 末尾 + `interface.py`）

| 分组 | 成员 | 含义 |
| --- | --- | --- |
| `PLATFORM_HANTANG_DMEV` | Han DM/EV 20、Tang DM | 老平台（Veoneer MPC/雷达方案），`BydSafetyFlags.HAN_TANG_DMEV` |
| `PLATFORM_SONG_PLUS_DMI` | **宋 Plus 21/22/23 + 宋 Pro 22** | **宋 Pro 走这一组**，`BydSafetyFlags.SONG_PLUS_DMI` |
| `PLATFORM_QIN_PLUS_DMI` | 秦 Plus 23 | |
| `PLATFORM_YUAN_PLUS_DMI_ATTO3` | 元 Plus / Atto3 | |

`BydSafetyFlags` 注释里有一句关键提醒：**`SONG_PLUS_DMI` 与 `SONG_PRO` 相似但不是同一套**，安全逻辑按"宋 Plus"处理。

### 2.3 纵向控制能力（决定你能不能脱离原车 ACC）

```python
MPC_ACC_CAR   = {HAN_DM_20, HAN_EV_20, TANG_DM}                    # 原车 MPC 方案（老车）
PT_RADAR_CAR  = {HAN_DM_20, HAN_EV_20, TANG_DM}                    # PT 总线上有雷达
TORQUE_LAT_CAR= {HAN_*, TANG_DM, SONG_PLUS_DMI_21}                 # 力矩转向；其余用 angle/PID
EXP_LONG_CAR  = {HAN_*, TANG_DM, SONG_PLUS_DMI_21}                 # 支持 op 纵向（alpha long）
```

**对宋 Pro 的意义**：`SONG_PRO_DMI_22` **不在 `EXP_LONG_CAR` 里** → 默认**用原车 ACC 的纵向**
（openpilot 只做横向 + 通过 tuning 修正原车 long 的加减速），UI 里不会出现"Experimental Longitudinal"。
想要 op 全长控，需要把车型加进 `EXP_LONG_CAR`（改代码，属于未验证改动，见 §7.3）。

---

## 3. 原车硬件能不能复用？

### 3.1 前置雷达（毫米波）——能读，但分平台

代码事实（`opendbc/car/byd/interface.py`）：

```python
BYD_RADAR = os.getenv("BYD_RADAR") is not None
...
if BYD_RADAR: ret.radarUnavailable = False
else:         ret.radarUnavailable = True   # candidate not in PT_RADAR_CAR
```

- `BYD_RADAR=1`（环境变量）→ 启用 `byd/radar_interface.py`：它用 `CANParser(DBC[pt], ..., CanBus.MPC)` 解析
  **0x374**（雷达目标帧），内部带**一维卡尔曼滤波**（距离+相对速度，可选伪速度观测）和一阶低通。
- 注释明确写着：*"disable simple pt radar due to mpc solver issue in official OP. It works with carrot/sunny/forg."*
  → **原车雷达在 carrot/sunny/FrogPilot 里能用，在官方 OP 里会和 MPC 求解器冲突**。
- `PT_RADAR_CAR` 只有 Han/Tang：说明**"PT 总线上直接有 MRR 雷达数据"这件事只对老平台成立**。

**宋 Pro 的雷达在哪？** 参考另一位 BYD Atto3 移植者的实测（`shemps/byd-atto3-openpilot-port`）：
BYD 新平台把**前视相机（Veoneer MVS4）+ 77GHz 雷达（Veoneer 77V12FLR）挂在一条 CAN-FD 私有总线**上
（约 2 Mbit/s 数据段），底盘控制总线才是 500k 经典 CAN。雷达目标要从**私有 CAN-FD** 读，
对应 `byd_radar_fd.dbc`。

> 结论：**理论可复用，落地要满足三个条件**：① 硬件是 CAN-FD 能力的 panda/接口板；② 接线取到私有总线；
> ③ 用对应车型的 FD radar DBC。本机 cpv8 的 `0x374` 解析是经典帧写法，宋 Pro 上是否匹配**必须实车抓包验证**。

### 3.2 原车 ACC / 巡航按键 —— 能读，且默认就用它

`carstate.py` 已经在读：

| 信号 | 帧 | 用途 |
| --- | --- | --- |
| `AccState` / `SetSpeed` / `SetDistance` | `ACC_HUD_ADAS`（相机帧） | 原车 ACC 状态、设定速度、跟车距离档 |
| `BTN_TOGGLE_ACC_OnOff` | `PCM_BUTTONS` | 巡航开关键 |
| `LKAS_Prepared` | `ACC_EPS_STATE` | EPS 侧 LKA 准备状态 |
| `LKAS_Output/Active/ReqPrepare` | `ACC_MPC_STATE` | **骗过 MPC** 用（`use to fool mpc`） |
| `SteerDriverTorque` / `MainTorque` | `ACC_EPS_STATE` | 驾驶员力矩 / EPS 电机力矩 |

> ⚠️ **2026-11-01 更正**：本节"配合 `K_ACCEL_*` 做百分比缩放"的说法**不成立**——那张表在本分支是死代码
> （全仓无消费方）。宋 Pro 的纵向实际是**透传**（`longActive` 恒 False，`bydcan.acc_cmd` 原样转发原车
> `ACC_CMD`）。以 [纵向优化-可行性与方案](纵向优化-可行性与方案.md) 为准。

### 3.3 摄像头 / IMU / 盲区

- **摄像头**：PC 版用 USB 摄像头（`USE_WEBCAM=1`），外参/内参要按 `tools/webcam/camera.py` 配（焦距 `ROAD_FOCAL`）。
- **底盘 IMU**：cpv8 2025-08-25 的更新日志里写明「**接入车辆底盘 IMU 数据**」——PC 没有 comma 的 IMU，
  这条就是为 PC 版补的（`carState` 里取 yawRate 等）。
- **盲区**：`ret.enableBsm = 0x418 in fingerprint[CanBus.ESC]` → 有 `BSD_RADAR 0x418` 就自动开 BSM。
- **智驾摄像头**（原车 MVS4）：**不参与** openpilot 的感知，op 用自己的摄像头跑模型；原车相机只提供 HUD/ACC 状态帧。

---

## 4. 各分支更新活跃度与"可持续性"判断

| 需求 | 推荐 | 理由 |
| --- | --- | --- |
| 想**最快上路** | **cpv8** | 已经整好 PC 摄像头、IMU、虚拟显示器、汉化、雷达开关，本机编译通过 |
| 想要**更多功能**（循迹、变道、UI 好看） | sunnypilot-pc-byd / MM-X/sunnypilot-pc | sunnypilot 上游每天更新；BYD 补丁可移植 |
| 想要**跟随上游修复**（bug/模型） | 自己维护：`MM-X/sunnypilot-pc` 为基座 + 定期 cherry-pick BYD car 代码 | 两条 BYD PC 分支都 5 个月没动 |
| 想用**官方模型/新特性** | 关注 `carrotpilot` 上游的 `carrot-wip` | 它是功能源头，但主打 HKG，BYD 需自测 |

**现实结论**：BYD 的 PC 版目前是"**社区小众分支 + 自己动手**"的状态。
`huheas` 的两个仓库（cpv8、sunnypilot-pc-byd）是同一个人的两条 PC 路线，更新节奏 3~6 个月；
真正每天在动的是 `ajouatom/openpilot` 与 `sunnypilot/sunnypilot`，但都不专门支持 BYD。

---

## 5. 调试与调参（重点）

### 5.1 三层调参结构

| 层 | 位置 | 改完要做什么 |
| --- | --- | --- |
| ① 车机 UI 开关 | 设置 → 车辆/驾驶 | 立即生效（部分需重启 op） |
| ② 车型代码参数 | `opendbc_repo/opendbc/car/byd/tuning.py`、`interface.py` | **重新编译** + 重启 op |
| ③ 运行时参数 | `~/openpilot/cpv8/params/`（`Params` 键值）或 UI | 重启 op 生效 |

### 5.2 `tuning.py` —— 原车 long 的"手感"都在这里

> ⚠️ **2026-11-01 更正**：下面 `K_ACCEL_*` 四组表在本分支**没有任何消费方**（死代码），调它无效。
> 宋 Pro 当前纵向 = 原车 ACC 透传；真正可动的只有"限幅干预"或"让 op 接管纵向"，
> 见 [纵向优化-可行性与方案](纵向优化-可行性与方案.md)。

```python
STEERING_ANGLE_OFFSET = -2.01      # 转向角零偏（跑偏就调这个）
DASHSPEED_BP/FP      = 仪表速度修正（百分比）
# 原车 ACC 加减速缩放：按"跟车距离档"给不同公里数区间的百分比
K_ACCEL_BP       = [40, 50, 60, 70, 80]      # 前车距离（米）
K_ACCEL_POS_4BAR = [0.7 ...]  # 4 档距离：加速百分比
K_ACCEL_NEG_4BAR = [1.0, 0.8 ...]            # 4 档距离：减速百分比
# 1BAR/2BAR/3BAR 同理：距离越近，减速百分比越大（更跟脚）
STEER_PRESSED_THRESHOLD = 56       # 判定"人抢方向盘"的力矩阈值
DISABLE_EPS_WARNING / TEMPORARY_FAULT / PERMANENT_FAULT   # EPS 报错时临时关检查
DISABLE_PARKBRAKE = False
```

**调法**（一次只改一组，改完跑一段同路段对比）：
- 跟车太"肉"/太"窜"：调 `K_ACCEL_POS_*`（加速百分比）和 `K_ACCEL_NEG_*`（减速百分比）。
- 高速跟车距离忽远忽近：`K_ACCEL_BP` 的区间划分和对应百分比。
- 方向盘正中但不走直线：`STEERING_ANGLE_OFFSET`（单位度，±3 内试）。
- 仪表速度比 GPS 快/慢：`DASHSPEED_FP`。
- EPS 偶发报错（尤其刷过固件的车）：对应 `DISABLE_EPS_*` 打开，但**这是掩盖症状，先查硬件**。

### 5.3 carrot 运行时参数（`selfdrive/carrot/carrot_functions.py`）

| 参数 | 作用 |
| --- | --- |
`TrafficLightDetectMode` | 0 关 / 1 只停 / 2 停走（默认 2）
`TrafficStopDistanceAdjust` | 红灯停车距离调整
`DynamicTFollow` / `DynamicTFollowLC` | 动态跟车时距
`StopDistanceCarrot` | 停车距离
`MyDrivingMode` / `MyDrivingModeAuto` / `MyHighModeFactor` | 驾驶风格（舒适/标准/运动）
`CruiseEcoControl` | 经济巡航
`AutoNaviSpeedDecelRate` | **导航限速降速速率**（CarrotNavi 用）

### 5.4 CarrotNavi（导航联动，cpv8 有）

`selfdrive/carrot/carrot_man.py` 订阅读 `navRouteNavd`、`navInstruction`，发 `navRoute/ navInstructionCarrot`；
配合 `AutoNaviSpeedDecelRate` 做**按导航限速/弯道自动降速**，并在 HUD 上提示。
它不是 NOA，但能解决"高速限速变化要手动降速"的痛点。

### 5.5 标准调试流程（建议照做）

1. **静态检查**：`scons -u -j$(nproc)` 通过；`python -c "from openpilot.common.params import Params"`。
2. **空跑**：`USE_WEBCAM=1 ROAD_CAM=0 NO_DM=1 system/manager/manager.py`，看 UI 是否出画面、
   `carState` 是否读到速度/转向角/ACC 状态（**不要在路上第一次跑**）。
3. **桌面回放/看曲线**：PlotJuggler 打开 `tools/plotjuggler`，订阅 `carState / controlsState / longitudinalPlan /
   carrotMan / modelV2`，重点看：`aEgo`（实际加速度）vs `aReq`、`steeringAngleDeg`、`trafficLight` 状态。
4. **上车**：先只开横向（`ExperimentalMode` 关、不接管油门刹车），确认 LKA 不画龙、不抢方向；
   再验证原车 ACC 联动（跟车/停车/起步）。
5. **记录**：`params` 里改过的键记到 `docs/` 下，方便回滚；每次改动只动一个参数。

### 5.6 常见现象 → 排查

| 现象 | 先查 |
| --- | --- |
| 画龙 / 抢方向 | `STEERING_ANGLE_OFFSET`、`steerRatio`（values.py CarSpecs）、摄像头外参 |
| 跟车顿挫 | `K_ACCEL_*`、`DynamicTFollow` |
| 仪表速度不对 | `DASHSPEED_*` |
| 摄像头不出图 | `ls /dev/video*`、`ROAD_CAM`、USB 带宽（双摄走不同控制器） |
| 一启动就报一堆设备错 | 正常——没接黑熊/没接车时必然；先 `NO_DM=1` 桌面空跑 |
| EPS 报错/降级 | `DISABLE_EPS_*`（临时）、查 EPS 固件与接线 |

---

## 6. 红绿灯识别 & 城市 NOA 现状

### 6.1 红绿灯：有，且是本机这套的核心卖点之一

代码实证（`selfdrive/carrot/carrot_functions.py`）：

```python
# 0: None, 1:Stop, 2:Stop&Go
self.trafficLightDetectMode = self.params.get_int("TrafficLightDetectMode")
if self.myDrivingMode == DrivingMode.High or self.trafficLightDetectMode == 0: ...
if self.trafficState == TrafficState.green and not self.carrot_stay_stop ...:
```

UI 里有对应开关（`settings.cc`）：`TrafficLight DetectMode — 0:None, 1:Stopping only, 2: Stop & Go`。

- 能力边界：**红灯停、绿灯起步**（跟停/跟走），属于"信号灯停走辅助"。
- **不是**路口博弈：不处理无保护左转、加塞、复杂路口通行；仍需要驾驶员随时接管。
- 上游 `ajouatom/openpilot` 里这块叫 **Traffic Signal Assist**（DeepWiki 有条目），cpv8 继承。

### 6.2 城市 NOA：开源生态目前没有

- 搜遍 carrot / sunnypilot / dragonpilot / FrogPilot 的公开说明，**没有**"城区 NOA"能力声明；
  它们的定位都是**高速/快速路 LKA + ACC/NOA-lite**。
- B 站有"2 个摄像头让旧车升城区 NOA"这类视频，属于营销/演示，**没有可复现的开源分支**。
- 真正的城市 NOA 需要：车道级地图/在线建图 + 红绿灯/路口感知 + 博弈规划 + 更强的算力平台，
  openpilot 的端到端模型（supercombo）不做这些。
- 生态里能沾边的只有：
  - `CarrotNavi`（导航限速/弯道降速提醒）
  - cpv8 更新日志里的"导航超速闪烁提醒"
  - sunnypilot 的 Green Light 类提示（部分版本）

> 所以对 23 款宋 Pro：**不要指望城区 NOA**；现实目标是"高速/快速路稳、跟车顺、红绿灯能停走"。

---

## 7. 23 款宋 Pro DM-i 的落地路线

### 7.1 推荐顺序

1. **本机 cpv8 起步**（已编译）：先桌面空跑，确认摄像头、`carState`。
2. 实车接 panda（**在相机接插件处串接**，参考 Atto3 手册 P13 定义：经典 CAN 是 4/8 脚，私有 CAN 是 3/7 脚）。
3. **先横向**：LKA 稳定、不画龙。
4. **再接原车 ACC**：`tuning.py` 微调跟车手感。
5. 想要更多功能，再评估 `sunnypilot-pc-byd`。

### 7.2 如果 23 款认不出车型

- 先看 `selfdrive/car/byd/fingerprints.py`：里面按 `CAR.BYD_SONG_PRO_DMI_22` 配了 ESC 的 FW 指纹。
- 认不出时：① 在 `values.py` 加 `BYD_SONG_PRO_DMI_23 = BydPlatformConfig(...)`（`CarSpecs` 抄 22 款或按整备质量改）；
  ② 在 `fingerprints.py` 加对应 FW 指纹；③ 把新车型加进 `PLATFORM_SONG_PLUS_DMI` 分组；④ 重新编译。
- 临时办法：`export FINGERPRINT="BYD_SONG_PRO_DMI_22"` 或 `FINGERPRINT="BYD_SONG_PLUS_DMI_23"` 强制指定。

### 7.3 想开 op 全长控（可选，风险自负）

`interface.py` 的 `EXP_LONG_CAR` 加 `CAR.BYD_SONG_PRO_DMI_22`，重编译后 UI 才会出现实验性纵向。
但宋 Pro 的 long 报文未验证，**先备份、先在封闭场地试**，随时准备 `Ctrl+C`。

---

## 8. 风险与限制（务必看）

1. **法规模糊**：国内对改装辅助驾驶的合法性/年检/保险责任没有明确说法，自行评估。
2. **车型未验证**：宋 Pro 22 在代码里，23 款属"同平台推测"，**安全逻辑按宋 Plus 处理**，行为需实车验证。
3. **雷达不确定**：宋 Pro 雷达在 CAN-FD 私有总线，本机 `0x374` 是经典帧解析，**大概率要改 DBC/抓包**。
4. **纵向依赖原车 ACC**：默认不改写加速/刹车，好处是安全边界清晰，坏处是"跟车手感受原车限制"。
5. **PC 版无冗余**：没有 comma 的看门狗/双 IMU，摄像头/串口掉线就是直接失效，**线束与供电要做扎实**。
6. **分支停更风险**：BYD PC 分支几个月一更，模型/上游安全修复不会自动来。

---

## 9. 参考资料

**代码（本机）**
- `~/openpilot/cpv8/opendbc_repo/opendbc/car/byd/`：`values.py`（车型/分组/能力集）、`interface.py`（雷达开关）、
  `radar_interface.py`（0x374 + 卡尔曼）、`carstate.py`（ACC/HUD/EPS 信号）、`tuning.py`（调参）、`fingerprints.py`
- `~/openpilot/cpv8/selfdrive/carrot/carrot_functions.py`（红绿灯/跟车参数）、`carrot_man.py`（CarrotNavi）

**仓库**
- carrotpilot 上游：https://github.com/ajouatom/openpilot （208★，日更）
- cpv8（本机）：https://github.com/huheas/carrotpilot ／ https://gitee.com/huheas/carrotpilot
- sunnypilot PC + BYD：https://github.com/huheas/sunnypilot-pc-byd
- dragonpilot + BYD：https://github.com/dragonpilot/byd-sp
- sunnypilot PC 基座：https://github.com/MM-X/sunnypilot-pc
- BYD Atto3 移植手册（总线/雷达/接插件，实测数据最全）：https://github.com/shemps/byd-atto3-openpilot-port
- BYD + Geely DBC 集合：https://github.com/yuluoqingcheng/openpilot-mypilot-community-dbcall
- opendbc BYD 初始 PR：https://github.com/commaai/opendbc/pull/2058 （yysnet）

**社区/教程**
- 公众号《教你手搓 Openpilot PC 版 · 软件篇》（本目录 `公众号教程笔记.md` 有整理）
- B 站：「Openpilot 在比亚迪上进行测试」「Openpilot 比亚迪适配移植中的那些坑」
  「比亚迪 Carrotpilot 参数调整」（2025-10）
- 「天神之眼-D」（Helper 工具注入比亚迪车型的流程说明，见本目录 `openpilot-helper-速查.md`）
