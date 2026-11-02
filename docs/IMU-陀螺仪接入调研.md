# IMU / 陀螺仪接入调研（2026-11-01）

> 目的：为后续 **纵向控制** 做准备，先搞清楚「这套代码能否吃外部陀螺仪数据」「本机有没有内置 IMU」。
> 所有结论都在本机代码/硬件上核对过；标注「未验证」的是作者自己也没测的部分。

---

## 0. 结论（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 这套代码支持外部陀螺仪吗 | **支持**。`sensord` 里有维特智能（WitMotion）串口 IMU 的 PC 分支，发 `gyroscope` / `accelerometer` 两路服务 |
| 默认会启动吗 | **不会**。`process_config.py:100` 是 `enabled=not PC`，PC 上 sensord 被关掉 |
| 那 PC 版现在靠什么喂 locationd | **用 CAN 合成**：`aEgo` 当加速度、`yawRate` 当角速度（`locationd.cc:456-475`），且 1 秒收不到 IMU 数据就自动回退到这条路 |
| 本机有内置陀螺仪吗 | **没有**。无 IIO 子系统；ACPI `SMO8810`（加速度计）**没绑驱动**；没有任何陀螺 |
| 能接入吗 | **能**：USB-TTL + JY 系列模块（JY61/JY62/JY901），`SERIAL_DEVICE=/dev/ttyUSB0`，再把 sensord 打开 |
| 纵向控制必须要它吗 | **不是硬需求**。BYD 纵向 = 原车 ACC，靠 CAN 的 `aEgo`/`vEgo`/`yawRate`；IMU 影响的是定位/姿态质量，属"锦上添花" |

---

## 1. 代码证据（本机实测）

| 位置 | 内容 |
| --- | --- |
| `system/sensord/SConscript` | sensord 在 x86 也编译（`i2c` 库只对 larch64 追加）；产物 `system/sensord/sensord` 3.4 MB，**已编译好** |
| `system/sensord/sensors_qcom2.cc:376-395` | `Hardware::PC()` 分支：默认 `/dev/ttyUSB0`，可用 `argv[1]` 或环境变量 `SERIAL_DEVICE` 覆盖 |
| 同文件 `:48` | 波特率自动扫描 `2400 … 921600`（共 10 档），`AutoScanSensor()` 逐个试 |
| 同文件 `:58-96` | 把维特原始值换算后发标准 sensorEvent：`gyroUncalibrated`(2000 dps)、`acceleration`(16 g)，source 填 `LSM6DS3TRC` |
| 同文件 `:176` | `PubMaster pm({"gyroscope", "accelerometer"})` |
| `system/manager/process_config.py:100` | `NativeProcess("sensord", …, enabled=not PC)` ← **PC 上不启动** |
| `selfdrive/locationd/locationd.cc:452-475` | IMU 超时 1 s → `imu_sensors_available=false` → 用 `log.getAEgo()` / `log.getYawRate()` 合成观测 |
| `selfdrive/locationd/locationd.h:98-100` | `IMU_TIMEOUT = 1.0` 秒 |
| `opendbc_repo/opendbc/car/byd/carstate.py:119` | `ret.yawRate = YAW_RATE.YawRate - YawRateOffset`（底盘 IMU 经 CAN 送上来） |
| `cpv8/README.md` 2025-08-25 更新日志 | 「接入车辆底盘IMU数据」「纵向接入byd汉前置雷达数据」「**增加维特串口陀螺仪适配（未测试）**」 |

**冒烟测试**（本机执行，无硬件）：

```
$ timeout 5 ./system/sensord/sensord /dev/ttyUSB9
Failed to open /dev/ttyUSB9
Failed to open serial sensor at /dev/ttyUSB9
```

→ 说明 PC 串口分支确实在编译产物里、逻辑正确：打不开就干净退出，不崩。

**结论**：链路 = `维特 IMU → 串口 /dev/ttyUSB? → sensord(PC 分支) → gyroscope/accelerometer 服务 → locationd`。
缺的只有"把 sensord 在 PC 上拉起来"这一步。

---

## 2. 本机硬件实测（Dell Latitude 5420 Rugged）

| 检查 | 结果 |
| --- | --- |
| `/sys/bus/iio/devices/` | **不存在**（整个 IIO 子系统都没启用） |
| `lsmod \| grep -i sensor/iio` | 无 hid-sensor；仅 `dell_lis3lv02d` 已加载但 **refcnt 0，无设备** |
| ACPI `SMO8810:00` | 设备存在，`modalias=acpi:SMO8810:`，**`driver` 为空 → 没绑驱动** |
| 唯一 i2c-HID 设备 `DELL0879:00`（Alps 044E:120A） | 是触摸板，不是 IMU |
| `/dev/hidraw*`、`/dev/input/event*` | 只有触摸板/键盘/热键等，没有 Accelerometer/Gyro |
| `/dev/ttyACM*`、`/dev/ttyUSB*` | **均不存在**（panda、串口 IMU 都没插） |

**判断**：这台机**没有可用的内置陀螺仪**，连内置加速度计都读不出来
（`SMO8810` 是 ST 的自由落体传感器，理论上可 `modprobe lis3lv02d_i2c` 绑上，但只有 3 轴加速度、
且 openpilot 在 PC 上只认 I2C 芯片驱动或串口，拿到也用不上 → **不做**）。

---

## 3. 三条可选路线

| 方案 | 成本 | 能拿到什么 | 代价 / 风险 |
| --- | --- | --- | --- |
| **A. USB 串口 IMU**（JY61P / JY62 / JY901 等维特模块 + USB-TTL） | 低（模块+转接板） | 3 轴陀螺 + 3 轴加速度（9 轴款还带磁力计/角度） | 需改 `process_config` 或手动起 sensord；作者标「未测试」，轴向/量程要自己校 |
| **B. 继续用底盘 CAN yawRate**（现状，零成本） | 0 | yaw 角速度（单轴）+ aEgo | 没有 pitch/roll 角速度；静止零漂靠 EKF 处理 |
| **C. 绑内核驱动的内置加速度计** | 0 | 只有 3 轴加速度 | 要 root 改驱动，且 openpilot 读不到；**不建议** |

> 补充：即使不接 IMU，`locationd` 也不会挂——`filterInitialized` 那段代码明确**跳过**加速度计/陀螺仪
> 的服务有效性检查（`locationd.cc` 内注释「过滤器初始化检查 - 跳过GPS和IMU传感器」）。

---

## 4. 接 JY62 的步骤草案（**未执行，等硬件**）

1. **硬件**：JY62（TTL 电平）+ USB-TTL（CH340/CP2102，注意模块是 5V 还是 3.3V），TX/RX 交叉。
2. **先用厂家上位机确认能出数**（默认 9600 8N1），别一上来就排查 openpilot。
3. 插上后 `ls /dev/ttyUSB*` 确认编号；建议加 udev 规则固定成 `/dev/imu`。
4. 在 `launch/env/songpro23.env` 打开 `SERIAL_DEVICE=/dev/ttyUSB0`（本次已加注释行）。
5. **让 sensord 在 PC 上跑**，二选一：
   - 改 `system/manager/process_config.py:100` 的 `enabled=not PC`（Python 改动，备份即可，不用重编译）；
   - 或手动 `./system/sensord/sensord /dev/ttyUSB0`（manager 之外跑，独立进程）。
6. **验证顺序**：
   - 裸跑 `./system/sensord/sensord /dev/ttyUSB0` → 应打印 `Found sensor at 9600 baud`；
   - 起 op 后 PlotJuggler 看 `/gyroscope` 频率是否 ~100 Hz、`liveLocationKalman.sensorsOK` 是否为真；
   - 静止时 gyro 应接近 0，转动模块 Z 轴看符号方向是否与车一致。
7. **轴向**：代码里已做 `{x, y, z} = {y, -x, z}`（加速度同理）——这是按 comma 车体坐标系转的，
   装到车上后**先静态验证符号**，不要直接信。

---

## 5. 为什么现在可以先不接（和纵向的关系）

- 宋 Pro 的纵向**不是 op 在做**：`EXP_LONG_CAR` 里没有宋 Pro，op 是「改原车 ACC 的指令」，
  输入是车速、`aEgo`、前车距离（CAN + 雷达）。
- IMU 主要影响 `locationd` 的定位/姿态质量 → 影响 `liveParameters`、曲率估计 → 主要服务**横向**。
- 真上 op 全长控（把车型加进 `EXP_LONG_CAR`）时，`aEgo` 依然来自 CAN，陀螺只影响坡道/姿态类估计。
- 所以优先级：**底盘 yawRate（已有）> 前雷达（待抓包）> 外接陀螺（可选增强）**。

---

## 6. 风险与未验证项

1. 作者原话是「增加维特串口陀螺仪适配（**未测试**）」——坐标系、量程、零偏、采样率都没有实测数据。
2. 换算写死：`gyro = raw/32768*2000`（dps）、`accel = raw/32768*16`（g）。若模块量程不是 2000dps/16g，**数值会错**。
3. 串口读循环没有时间戳对齐保护，IMU 与相机时延差太多会让 EKF 抖动；`SERIAL_DEVICE` 已存在时 `sensord` 与 manager 可能重复拉起。
4. 1 秒超时回退 CAN 是好事：拔掉/坏掉 IMU 不会让 op 崩，只会退回现状。

---

## 7. 参考资料

- 本机代码：`system/sensord/sensors_qcom2.cc`、`system/manager/process_config.py`、`selfdrive/locationd/locationd.cc`
- 本机 `cpv8/README.md` 更新日志（2025-08-25 / 2025-07-31）
- [JY62 产品规格书 · 深圳维特智能](https://wit-motion.yuque.com/wumwnr/docs/youtyc)
- [维特智能 快速上手](https://wit-motion.yuque.com/wumwnr/docs/wy23zrl80ovwv9g0)
- （社区向）公众号《教你手搓 Openpilot PC 版-硬件篇》——本机 `docs/公众号教程笔记.md` 有整理
