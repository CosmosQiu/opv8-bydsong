# AGENTS.md — OpenPilot 工作区（本机 `~/openpilot`）

> 本目录是这台笔记本上 **OpenPilot（PC 版）相关的全部内容**。机器本身的说明见
> `C:\Users\cosmos\Documents\DSH\AGENTS.md`（Windows 工作区）与
> `~/openpilot/AGENTS.md`（本文）。

## 一、目录结构

```
~/openpilot/
├── AGENTS.md                     # 本文：目录作用、工具、约定
├── cpv8/                         # 【源码】carrotpilot v8（带比亚迪车型），已编译
│   ├── tools/op.sh               # 编译/环境入口（已加 resolute 白名单补丁）
│   ├── .venv/                    # Python 3.12 虚拟环境（uv 生成）
│   ├── selfdrive/ system/ ...    # op 源码
│   └── build/ 或各目录 *.o/*.so   # scons 产物
├── helper/
│   └── openpilot-helper-0322/    # 【工具】官方「Openpilot 管理工具」v0.0.2（Go 静态二进制）
│       ├── openpilot-helper      # 主程序（4.3 MB，x86-64 静态链接）
│       └── config/
│           ├── config.env        # OPENPILOT_ROOT / BYD_MODELS / 串口
│           ├── cars/*.env        # 各车型运行参数（FINGERPRINT、摄像头、焦距）
│           ├── setup/byd/*.py    # BYD 注入用的 carstate/carcontroller/values 等
│           ├── setup/byd_others/ # safety_byd.h、byd_han_dmev_2020.dbc
│           ├── setup/qt_fullscreen/  # Qt 全屏补丁
│           └── setup/light_control/  # 小蓝灯串口控制
├── launch/                       # 【入口】23 款宋 Pro 专用启动脚本与参数
│   ├── run-songpro23.sh          # 启动 op（自动 source env + venv）
│   ├── env/songpro23.env         # FINGERPRINT / 摄像头 / NO_DM / BYD_RADAR
│   └── set-params.py             # 写入/查看调参预设（TrafficLightDetectMode 等）
└── docs/
    ├── 公众号教程笔记.md          # 「教你手搓 Openpilot PC 版-软件篇」要点整理
    ├── openpilot-helper-速查.md   # helper 命令速查 + V9 注入流程
    ├── 比亚迪调研-宋Pro-DMi.md    # 分支/雷达/调参/红绿灯 调研报告
    ├── 宋Pro-23款-适配与调参手册.md  # ★ 本轮改动 + 四类需求参数 + 调试流程 + ACC 按键/22-23 差异
    ├── 调参记录.md                # 上车实测记录（模板 + 基线 + 回退索引）
    ├── IMU-陀螺仪接入调研.md      # 陀螺仪支持情况 / 本机硬件实测 / JY 系列接入步骤
    └── 纵向优化-可行性与方案.md   # ★ 纵向归因、三条路（限幅/接管/只测）、调试指标
```

## 二、cpv8（carrotpilot v8）

| 项 | 值 |
| --- | --- |
| 来源 | `https://gitee.com/huheas/carrotpilot.git` |
| 分支 / 提交 | `carrot2-v8` @ `43a030a` |
| 体积 | 约 3.2 GB（含 `.venv`、`.git`、编译产物） |
| Python | `.venv` 内 3.12.3（`uv sync --frozen --all-extras`） |
| 编译 | `scons -u -j8` **已通过**（`selfdrive/ui/ui` 20 MB、`loggerd`/`sensord`/`ubloxd` 等） |
| 依赖镜像 | `UV_INDEX_URL`/`PIP_INDEX_URL` = 清华 PyPI（**阿里云 PyPI 对 uv 返回 403**） |

常用命令：

```bash
cd ~/openpilot/cpv8
source .venv/bin/activate          # 或 bash tools/op.sh venv
scons -u -j$(nproc)                # 增量编译（首次全量约 6 分钟 / 8 核）

# 运行（硬件到位后再用，见第四节）
export FINGERPRINT="BYD_TANG_DMI_23"
USE_WEBCAM=1 ROAD_CAM=0 NO_DM=1 system/manager/manager.py
```

## 三、helper（官方管理工具）

- 版本 `v0.0.2`，作者「贰拾壹」（github.com/er10yi），Go 静态编译，**无需依赖即可运行**。
- 作用：往 op 源码树里**注入/回滚** BYD 支持、改摄像头参数、全屏补丁、小蓝灯串口，并按车型 env 启动 op。
- 所有修改**自动留 `.bak`**，`rollback` 一键还原。
- ⚠️ `init byd` 只对 BYD 车用；非 BYD 跑它可能把系统搞坏。
- 详细命令见 `docs/openpilot-helper-速查.md`。

**当前状态：只解包、未执行任何注入命令。** `config/config.env` 里的 `OPENPILOT_ROOT` 还是工具默认的
`/home/comma/Desktop/cpv9-pc-dev_0311_test`，等真正做 V9 注入时再改成目标目录。

## 四、待办（按优先级）

1. **硬件未到，不要运行 op**：摄像头、黑熊（panda）、线束都还没接，跑 `manager.py` 只会报设备错误。
2. **CP 分支「胜达 V9」车型注入**：等确认目标 op 目录后，改 `config/config.env` 的 `OPENPILOT_ROOT`，
   再按 `docs/openpilot-helper-速查.md` 的流程 `init byd` → `enable full_screen/light_control` → 编译。
3. **Timeshift 首个快照**：装好了但没建，等选定备份盘。
4. 摄像头编号：接上后先 `ls /dev/video*` 确认 `ROAD_CAM`/`WIDE_CAM` 的真实编号。
5. **陀螺仪（可选，非阻塞）**：本机无内置 IMU。要接就上维特 JY 系列 + USB-TTL，设 `SERIAL_DEVICE`
   并把 sensord 在 PC 上拉起来（`docs/IMU-陀螺仪接入调研.md`）。纵向控制不依赖它——底盘 `yawRate`
   经 CAN 已经喂给 locationd 了，别被"必须先有陀螺仪"带偏。

## 五、纪律（踩过坑）

1. **不要跑 `apt upgrade` / 升级 26.04**：这台机器曾因 `libc6` 跨版本升级卡死导致系统不可用。
   只装点名要的包，apt 一律 `DEBIAN_FRONTEND=noninteractive` + `</dev/null`。
2. 改 `cpv8` 里的源码/脚本前先备份（`.bak.<日期>`），改完 `scons -u` 验证能编过。
3. 不要往主目录（`~`）再丢 op 相关文件，统一放 `~/openpilot/` 下。
4. 编译/注入类操作尽量用 `systemd-run` 跑，避免 SSH 断线中断。

## 六、执行边界（动手前逐条对，越界先问人）

### 6.1 文件范围
- 只在 `~/openpilot/` 内读写；`~/` 其他目录、`/etc`、`/data`、`~/.comma` 仅在明确要求时碰。
- `cpv8/` 是 3.2 GB 的**已编译 + 带未提交改动**的树：不动 git 历史（不 `reset --hard` / `rebase` /
  `clean -xdf` / `checkout` 覆盖），不删任何 `*.bak.*`（那是唯一回滚凭证）。
- 不删 `cpv8/` 下的 `.o/.so/.venv/build` —— `git status` 看不见它们，删了就得全量重编。

### 6.2 改动范围
- **一次只改一类**（指纹 / 平台 / 参数 / 启动脚本），改完立刻验证（`scons -u`、`PYTHONPATH=... python -c`，
  手册 §3 阶段 0），再进下一项；不把多个改动混在一次提交里。
- 写参数只走 `launch/set-params.py` 这一个入口，不手改 `~/.comma/params/*`。
- 不擅自改 `EXP_LONG_CAR` / `AlphaLongitudinalEnabled`（= 把纵向从原车 ACC 换成 op 长控，高危；
  加任何车型——**包括宋 Pro 自己**——都要明确授权 + 封闭场地预案 + `safety_byd.h` 放行确认）。
- 不改 `panda/` 固件、不改 safety flags、不关任何安全校验。
- helper 是第三方二进制：**不对 `cpv8` 执行 `init byd`**（cpv8 自带 BYD），只对 cpv9 目标目录用，
  且先改 `OPENPILOT_ROOT`、先 `--help` 看行为。

### 6.3 运行范围
- 硬件未到（无 `/dev/ttyACM*`、只有内置摄像头）→ **不跑 `manager.py`**，不拿"空跑出 UI"当验收。
- 长任务（编译/注入）用 `systemd-run` 或后台 job，不前台死等。

### 6.4 信息边界
- 社区/网搜结论必须标来源，并标「未实车验证」，不许写成定论。
- 手册里跟代码不一致的地方以代码为准，发现偏差就地记进本文 §八，不要"顺手"改源码去迁就文档。
- 拿不准就先查/先问，不猜着改。

## 七、安全准则

### 7.1 车辆与人身（最高优先级，压过一切"把功能调出来"的诉求）
1. 上车前必须过完手册 §3 阶段 0/1/2；**任何改动没在实车复现过，就当作没验证**。
2. 首次测试只在**封闭场地 / 人少路段**：副驾留人、脚悬刹车、随时能接管；不在公共道路做首次实验。
3. 红绿灯从 `TrafficLightDetectMode=1`（只停）起步，稳定后再 2（停走）；不做路口博弈（无保护左转、
   加塞、复杂路口一律人工接管）。
4. 限速相关：`AutoNaviSpeedSafetyFactor` 不超过 105，以法定限速为准，不追求"顶满"。
5. 原车 ACC 继续负责纵向，**不要在行驶中改 `EXP_LONG_CAR` / 切 op 全长控**。
6. 出现画龙、EPS 报警、刹车异常、报错刷屏：先退出 op（终端 Ctrl+C，点 × 无效）恢复原车状态，
   再回桌面排查；**不在车上现场改代码**。
7. 安全兜底永远在人：op 只是 L2 辅助，手不能长时间离方向盘。

### 7.2 主机系统
1. 不 `apt upgrade`、不升 26.04（见 §五.1）；只装点名包，`DEBIAN_FRONTEND=noninteractive` + `</dev/null`。
2. 不 `sudo` 改系统文件、不装来路不明的二进制/脚本；第三方工具先在隔离目录试，留好 `.bak`。
3. 破坏性操作（`reset --hard`、`rm -rf`、`rollback`、`init byd`、改 `~/.comma`）**先说明影响再执行**，
   并先建快照/备份；删除或移动前先 `ls -la` 确认解析后的绝对路径。
4. 不把 `sudo`、`curl | bash`、远程脚本直接当快捷方式用。
5. `~/.comma/params/d` 是**软链**，指向 `.tmp_XXXXXX` 目录——那个 `.tmp_*` **就是真参数存储**，不是垃圾。
   删之前先 `readlink`。（10-28 踩过：把 `.tmp_snE4M8` 当残留删了 = 参数全清、`d` 变悬空链，
   靠重跑 `launch/set-params.py` 让它重建存储再写回预设才恢复。）

### 7.3 数据与隐私
1. 行车日志、录像、参数快照可能含位置/人脸/车牌：**不外传、不上传**，贴日志前先脱敏。
2. `~/.comma/params`、`cpv8/.env`、`helper/config/config.env` 属本机配置，不原样贴到公开渠道。

### 7.4 回滚速查（改坏了照这个走）

```bash
# BYD 三个文件
cd ~/openpilot/cpv8/opendbc_repo/opendbc/car/byd
for f in values.py fingerprints.py interface.py; do cp -f "$f.bak.<日期>" "$f"; done
# 编译脚本补丁
cd ~/openpilot/cpv8 && cp -f tools/op.sh.bak.<日期> tools/op.sh
# 重编验证
cd ~/openpilot/cpv8 && source .venv/bin/activate && scons -u -j8
```

## 八、环境事实 & 已知偏差（2026-10-28 初始化核对 / 11-01 陀螺仪核对）

初始化核对结果（只读检查，未改动任何源码）：

| 项 | 实测 |
| --- | --- |
| 系统 | Ubuntu 24.04.5 LTS（noble），内核 7.0.0-38；**不是** resolute —— `tools/op.sh` 里加的 resolute 白名单是给未来/他机的 |
| 硬件 | 8 核 / 15 GiB 内存 / 根分区 468 G 用 21 G；GPU 仅 Intel UHD 620（**无 NVIDIA**，未装 `clinfo`） |
| 视频设备 | 只有内置摄像头 `/dev/video0`、`/dev/video1`；**无 panda**（无 `/dev/ttyACM*`） |
| IMU / 陀螺仪 | **无内置 IMU**：没有 IIO 子系统；ACPI `SMO8810`（ST 自由落体加速度计）**未绑驱动**；`dell_lis3lv02d` 加载了但 refcnt 0。`sensord` 在 PC 上 `enabled=not PC`（`process_config.py:100`），locationd 改吃 CAN 的 `aEgo`/`yawRate` |
| 编译树 | `scons -u -n` → `'.' is up to date`，177 个 `.o`、`selfdrive/ui/ui` 20 MB（10-27 02:23） |
| git | `carrot2-v8` @ `43a030a`，4 个已改文件（BYD values/fingerprints/interface + tools/op.sh）+ 4 个 `.bak.20261027` |
| 平台登记 | `CAR.BYD_SONG_PRO_DMI_23 in PLATFORM_SONG_PLUS_DMI` → `True` |
| 参数 | `~/.comma/params/d` 是**软链** → `.tmp_KhMGIq/`；5 个预设参数在位（`TrafficLightDetectMode=2` 等） |
| 工具链 | `scons`/`uv` **只在 `cpv8/.venv/bin`**，全局 PATH 没有；`git`/`jq`/`ffmpeg`/`systemd-run` 在 `/usr/bin` |

已知偏差（照文档做会踩到）：

1. ~~`launch/set-params.sh`~~ **已修正（10-28）**：手册 §3 与 `set-params.py` docstring 都改成 `.py` 了；
   实际文件一直是 [set-params.py](launch/set-params.py)（可执行、有 shebang）。
2. `helper/config/config.env` 的 `OPENPILOT_ROOT` 仍是作者默认值 `/home/comma/Desktop/cpv9-pc-dev_0311_test`，
   用 helper 前必须改。
3. ~~`docs/调参记录.md` 未建~~ **已建（10-28）**：[调参记录](docs/调参记录.md) 含模板、基线条目、回退索引。
4. `selfdrive/manager/manager.py` **不存在**，入口是 `system/manager/manager.py`（`run-songpro23.sh` 已用对）。
5. **手册 §2.2 旧版说错了（11-01 已订正）**：`tuning.py` 的 `K_ACCEL_*` 表是**死代码**，全仓无消费方；
   宋 Pro 的纵向是「透传」（`longActive` 恒 False，`bydcan.acc_cmd` 原样转发原车 `ACC_CMD`）。
   同理 `MyDrivingMode`/`JerkStartLimit`/`LongTuning*` 这些 op 纵向参数当前都不生效。
   详见 [纵向优化-可行性与方案](docs/纵向优化-可行性与方案.md)。
6. **判 panda 的方法错了（11-02 订正）**：§八上表写「无 panda（无 `/dev/ttyACM*`）」——但 **panda 走 libusb，
   根本不创建 `/dev/ttyACM*`**。11-02 实测已接上一只 panda，`/dev/ttyACM*` 依然为空。
   正确判法：`lsusb | grep 3801:ddcc`，或
   `cd cpv8 && ./.venv/bin/python -c "from panda import Panda; p=Panda(); print(bytes(p.get_type()).hex(), p.get_version())"`。
   实测：RED_PANDA（type `0x07`），固件 `DEV-43a030a5-DEBU`，libusb 免 sudo 可开。
7. **两颗 USB 摄像头是同一模块、只换镜头（11-02）**：VID/PID/序列号全相同（`1bcf:2cd1` / `01.00.00`），
   `/dev/v4l/by-id` 只有一条链接（指向后插入那颗）。只能用 `/dev/v4l/by-path` **按 USB 端口**绑定；
   **换 USB 口后 by-path 会变**（11-02 实测鱼眼从 `10.2` 挪到 `10.4`，env 里的旧路径直接失效）。
   换口后必须先 `ls -l /dev/v4l/by-path/ | grep index0` 再改 `launch/env/songpro23.env`。
8. **两路 1080p 起不来是硬约束（11-02）**：两颗都挂同一条 USB 2.0 总线（唯一 xHCI），两路都申请
   1920x1080 会 `VIDIOC_STREAMON: No space left on device`，内核日志是
   `usb 1-10.x: Not enough bandwidth for altsetting N`。换端口无用。
   必须「路面 1920x1080@20 + 广角 1280x720@20」；**30fps 时连 1080p+720p 都会挂**，20fps 不是可选项。
   详见 [超广角-鱼眼-调试参数](docs/超广角-鱼眼-调试参数.md)。
9. **摄像头角色已改成自动识别（11-02）**：`CAM_AUTODETECT=1`（在 `launch/env/songpro23.env`）时，
   `camerad` 启动会用画面特征判断哪颗是路面/广角——鱼眼是圆形像场、**四角死黑**，普通视角四角有内容。
   因此**换 USB 口、甚至把两颗物理对调都不用改配置**；`ROAD_CAM`/`WIDE_CAM` 退化为兜底（识别失败时才用）。
   逻辑：`cpv8/tools/webcam/camdetect.py`（可单独跑 `./.venv/bin/python -m tools.webcam.camdetect`）。
   ⚠️ 预览程序占着摄像头时识别会失败并回落到 by-path，日志里有明确提示。
10. **对焦/曝光控制项是存在的，但基本不能用（11-02 实测订正）**：camera class 段 `0x009a09xx` 有
   `focus_absolute`(0..1023)、`focus_auto`、`exposure_auto`(0..3)、`exposure_absolute`(1..10000)。
   - 手动扫 `focus_absolute` 全范围，画面清晰度只变 1.0 倍 → **固焦镜头，控制项是假的，只能拧镜头**
   - `exposure_auto` 只有 MANUAL(1) / APERTURE_PRIORITY(3) 可写，**AUTO(0) 返回 EINVAL**
   - 之前判断"设备没有曝光/对焦控制"是错的——漏了 `0x009A09xx` 这一段（早先扫描上界卡在 `0x009A0000`）
   详见 [超广角-鱼眼-调试参数](docs/超广角-鱼眼-调试参数.md)。
11. **桌面预览器（11-02）**：`~/Desktop/摄像头预览.desktop` → `launch/preview-cam.py`。
   现场选摄像头（显示识别结果/端口）和预览模式（1080p/4K/中心2x/4x），开预览前自动把 `sharpness` 归零、
   退出还原，便于判焦。注意 guvcview 内部路径缓冲只有 ~30 字符，脚本会自动把 by-path 转成 `/dev/videoN`。
12. **鱼眼去畸变已实现（11-02）**：`cpv8/tools/webcam/lens.py`（Kannala-Brandt + remap），
   `camera.py` 在 BGR 阶段做、`camerad.py` 只对广角生效。开关 `WIDE_UNDISTORT=1` +
   `WIDE_LENS_FILE=launch/env/wide_lens.json`。**帧率无损**（广角仍 19.0fps）。
   依据是代码结构：`get_warp_matrix()` 是纯 3x3 针孔单应、全仓无畸变项，官方文档没写但事实上必需。
   ⚠️ 别用 `cv2.fisheye.estimateNewCameraMatrixForUndistortRectify`，近 180° 鱼眼上会出退化解。
   标定工具：`tools/webcam/calib_lens.py`。详见 [超广角-鱼眼-调试参数](docs/超广角-鱼眼-调试参数.md) §七。
13. **指纹必须补地址，否则认不出车（11-02）**：op 的 `eliminate_incompatible_cars()` 遇到"任何指纹
   都没有的 CAN 地址"会把所有候选车淘汰掉。实测本车 bus0 有 118 个地址，而 `BYD_SONG_PRO_DMI_23`
   原指纹只有 101 个，**23 个缺失地址导致候选车淘汰到 0 台**（进 op 会显示无法识别车辆）。
   已把这 23 个 8 字节地址补进 `opendbc_repo/opendbc/car/byd/fingerprints.py`（备份 `.bak.20261102`），
   复核：真实 CAN 跑淘汰逻辑现在唯一命中 `BYD_SONG_PRO_DMI_23`。
   ⚠️ 换车/换固件/加装 ECU 后要重新核对；判定脚本思路见本次会话（抓 2 秒 bus0 → 跑
   `eliminate_incompatible_cars`）。另外指纹里 6 个地址本次没抓到（`0x33B/33C/33D/34B/374/3FC`，
   含雷达 0x374），推测要雷达上电或走 bus1 才出现。
14. **panda 已接实车 CAN（11-02）**：RED_PANDA 收到 bus0/bus2 各 118 个地址、2.5 秒约 2 万帧，
   `can_speed=500`、**`canfd_enabled=0`**（经典 CAN，不是 CAN-FD），bus_off/error 均为 0。
   两个 bus 地址集合完全相同，说明接的是同一条物理总线（冗余）。
15. **分支自带的三个会「让车认不出来 / 按钮无法激活」的 bug（11-02 已修）**：
    - `torque_data/params.toml` 只有 Han 两款 BYD 的扭矩数据，其余 9 款（含宋 Pro 23）调
      `get_torque_params()` 直接 `KeyError` → card 崩溃。已补进 `substitute.toml`（借用 BYD_HAN_DM_20）。
    - `opendbc/car/byd/radar_interface.py` 硬写日志路径 `/data/debug/...`，PC 上无 `/data` →
      `PermissionError` 崩 card。已加兜底到 `~/.comma/debug/`。
    - `system/manager/process.py` 的 `PythonProcess.start()` 是 `if self.proc is not None: return`，
      **任何 Python 进程崩一次就永不重启**（上游是判断 `exitcode is None`）。已修，并加了 5s 重启退避
      （否则新旧实例抢 msgq socket 会变成 MultiplePublishersError 死循环）。
    另外 `launcher()` 现在会把崩溃堆栈写到 `~/.comma/debug/<name>_crash.log`
    （PC 版 op 的 stdout/stderr 全在终端窗口里，很容易被刷掉）。
    症状对应关系：UI 显示「无法使用 openpilot 等待开始」= `selfdrived` 的 `canError` 告警，
    根因是 card 没发 `carState`（`CS.canValid` 恒为 False）。排查顺序：card 是否在跑 →
    `carParams`/`carState` 有没有 → panda 是否还是 `elm327`。
