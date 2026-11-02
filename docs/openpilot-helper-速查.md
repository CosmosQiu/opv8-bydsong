# Openpilot Helper 速查（v0.0.2）

> 二进制：`~/openpilot/helper/openpilot-helper-0322/openpilot-helper`
> 作者：贰拾壹（github.com/er10yi）｜Go 静态编译（x86-64），单文件即可运行，无需 Python 依赖。
> 原则：**所有修改都会自动生成 `.bak` 备份**，`rollback` 可整体回滚。

## 一、它干什么

往既有的 openpilot 源码树里做「适配补丁」，不用手工改代码：

| 能力 | 说明 |
| --- | --- |
| BYD 注入 | 把 `config/setup/byd/*`（carstate / carcontroller / values / fingerprints / interface / bydcan / radar_interface / tuning）覆盖进 `selfdrive/car/byd/`，并把 `safety_byd.h`、`byd_han_dmev_2020.dbc` 放到对应位置 |
| 摄像头参数 | 改 `camerad` 的分辨率 / 焦距（改完需重新编译） |
| Qt 全屏 | 打 `qt_window.cc` 补丁（需重新编译） |
| 小蓝灯 | 串口控制的蓝灯模块（`light_control`），可开可关 |
| 按车型启动 | 读 `config/cars/<车型>.env` 里的环境变量跑 `system/manager/manager.py` |
| 回滚 | 撤销上面所有改动 |

## 二、运行前必须改的配置

`config/config.env`：

```ini
# op 的绝对路径（当前还是作者默认值，必须改成你的）
OPENPILOT_ROOT=/home/comma/Desktop/cpv9-pc-dev_0311_test

# 允许注入/运行的车型列表
BYD_MODELS=BYD_HAN_DM_20,BYD_HAN_EV_20,BYD_TANG_DMI_21,BYD_TANG_DMI_23

# 串口（一般不用改）
JY62_TTY=/dev/ttyUSB0        # JY62 惯导/GNSS
BLUE_LIGHT_TTY=/dev/ttyUSB1  # 小蓝灯模块（只有蓝灯时改成 ttyUSB0）
```

`config/cars/*.env` 是各车型的运行参数，例如 `BYD_TANG_DMI_23.env`：

```ini
FINGERPRINT="BYD_TANG_DMI_23"
USE_WEBCAM=1
ROAD_CAM=0
#WIDE_CAM=2
NO_DM=1
JY62=2
ROAD_FOCAL=2320.0
ROAD_WIDTH=1920
ROAD_HEIGHT=1080
WIDE_FOCAL=605.0
WIDE_WIDTH=1920
WIDE_HEIGHT=1080
```

> 井号 = 不启用；所有键都会导出成环境变量给 `manager.py`。

## 三、命令清单

```bash
cd ~/openpilot/helper/openpilot-helper-0322
./openpilot-helper --help
```

| 命令 | 作用 |
| --- | --- |
| `init byd` | ⚠️ **仅限 BYD**：注入 BYD 基础支持（carstate/carcontroller/can 等） |
| `set cam_all` | 同时设分辨率 + 焦距 |
| `set cam_focal` | 设某个摄像头焦距（像素） |
| `set cam_res` | 设某个摄像头分辨率 |
| `set jy62` | 设 JY62 串口（默认 `/dev/ttyUSB0`） |
| `set light_port` | 设小蓝灯串口（默认 `/dev/ttyUSB1`） |
| `enable full_screen` | 启用 Qt 全屏 |
| `enable light_control` | 启用小蓝灯模块 |
| `disable full_screen` | 回滚全屏补丁 |
| `disable light_control` | 禁用小蓝灯模块 |
| `run <car_name>` | 用 `config/cars/<car_name>.env` 启动 op |
| `rollback` | 回滚全部改动（camera / 全屏 / 蓝灯 / BYD 注入） |
| `set-cam` | 旧版设焦距命令（兼容保留，将移除） |

每个子命令都支持 `--help`，例如 `./openpilot-helper set cam_focal --help`。

## 四、典型流程（胜达 V9 / cpv9-pc-dev 注入 BYD）

```bash
# 0. 前提：目标 op 目录已经 clone 好、依赖装好（tools/op.sh setup 过）
cd ~/openpilot/helper/openpilot-helper-0322

# 1. 改 config/config.env 指向目标 op 目录
sed -i 's|^OPENPILOT_ROOT=.*|OPENPILOT_ROOT=/home/cosmos/openpilot/cpv9-pc-dev|' config/config.env

# 2. 注入 BYD 支持（会自动备份原文件）
./openpilot-helper init byd

# 3. 按需设摄像头参数 / 全屏 / 蓝灯
./openpilot-helper set cam_all          # 交互式或带参数，看 --help
./openpilot-helper enable full_screen
./openpilot-helper enable light_control

# 4. 重新编译（改了 C++ 补丁必须重编）
cd /home/cosmos/openpilot/cpv9-pc-dev
source .venv/bin/activate
scons -u -j$(nproc)

# 5. 启动（用车型 env）
cd ~/openpilot/helper/openpilot-helper-0322
./openpilot-helper run BYD_TANG_DMI_23

# 出问题整体回滚
./openpilot-helper rollback
```

## 五、注意事项

1. **非 BYD 车不要跑 `init byd`**（原工具警告：可能导致系统异常）。
2. 改了摄像头参数 / 全屏补丁 / BYD 注入后，**都要重新编译**才生效；运行中的 op 需要重启。
3. `rollback` 依赖 `.bak` 文件——别手动删它们，也别在注入后又大改源码再回滚（会冲突）。
4. 本机现在的 `cpv8`（carrot2-v8）**本身就带 BYD 支持且已编译**，不要拿 helper 去注入它；
   helper 是给 **cpv9-pc-dev（胜达 V9）**那种需要注入的分支用的。
5. 工具来自第三方 QQ 群，**不是开源仓库的正式产物**；执行前先 `--help` 看清行为，用完可 `rollback`。
