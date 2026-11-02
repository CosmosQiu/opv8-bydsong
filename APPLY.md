# 如何应用这些改动

`overlay/cpv8/` 下的目录层级与 openpilot 源码树**完全一致**，直接覆盖即可。

## 前置：先拿到源码树

```bash
git clone https://gitee.com/huheas/carrotpilot.git cpv8
cd cpv8
git checkout carrot2-v8          # 本仓库基于提交 43a030a
```

## 1. 备份（重要）

这些文件都要被覆盖，先留一份回滚凭证：

```bash
DATE=$(date +%Y%m%d)
for f in \
  tools/webcam/camera.py tools/webcam/camerad.py \
  system/manager/process.py \
  opendbc_repo/opendbc/car/byd/fingerprints.py \
  opendbc_repo/opendbc/car/byd/interface.py \
  opendbc_repo/opendbc/car/byd/radar_interface.py \
  opendbc_repo/opendbc/car/byd/values.py \
  opendbc_repo/opendbc/car/torque_data/substitute.toml \
  tools/op.sh ; do
  cp -p "$f" "$f.bak.$DATE"
done
```

## 2. 覆盖

```bash
cp -rv /path/to/overlay/cpv8/. /path/to/cpv8/
```

`tools/webcam/` 下会有三个**新增**文件（`camdetect.py` / `lens.py` / `calib_lens.py`），
覆盖时一并出现。

## 3. 验证

```bash
cd cpv8 && source .venv/bin/activate

# 语法
python -m py_compile tools/webcam/*.py system/manager/process.py \
  opendbc_repo/opendbc/car/byd/*.py

# 扭矩参数（原来会 KeyError）
python -c "
from opendbc.car.interfaces import get_torque_params
from opendbc.car.byd.values import CAR
t = get_torque_params()
print([c for c in map(lambda x: str(x).split('.')[-1], CAR) if c not in t] or 'OK 全部有扭矩参数')"

# 摄像头角色识别
python -m tools.webcam.camdetect

# C++/Cython 部分（本仓库没改，但确认没被带坏）
scons -u -j$(nproc)
```

## 4. 配置

启动环境变量见 `launch/env/songpro23.env`，要点：

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `USE_WEBCAM` | `1` | 走 PC 版 USB 摄像头通路 |
| `CAM_AUTODETECT` | `1` | 按画面特征自动分配路面/广角 |
| `ROAD_CAM` / `WIDE_CAM` | by-path | 自动识别失败时的兜底 |
| `ROAD_WIDTH/HEIGHT/FPS` | `1920/1080/20` | **帧率必须是 20**，低了会触发 `cameraFrameRate` |
| `WIDE_WIDTH/HEIGHT` | `1280/720` | 和路面共用一条 USB 2.0 总线，双 1080p 起不来 |
| `WIDE_UNDISTORT` | `1` | 鱼眼去畸变开关 |
| `WIDE_LENS_FILE` | `launch/env/wide_lens.json` | 镜头参数（可用 `calib_lens.py` 重新标定） |

⚠️ 别照抄文件里的绝对路径 —— 换成你自己的目录。

## 5. 跑起来

```bash
./launch/run-songpro23.sh
```

## 回滚

```bash
for f in $(find . -name "*.bak.$DATE"); do cp -p "$f" "${f%.bak.$DATE}"; done
```

---

## 附：这些改动是**必需**的吗

| 改动 | 不做的后果 |
| --- | --- |
| `substitute.toml` 补 BYD 扭矩 | 除 Han 外的所有 BYD 车型，`card` 启动即崩 → 车辆无法识别 |
| `radar_interface.py` 日志兜底 | PC 上没有 `/data` → `card` 崩 |
| `process.py` 重启修复 | 进程崩一次就再也不回来，只能重启整个 op |
| `fingerprints.py` 补地址 | 车辆指纹匹配失败 → 显示"无法识别车辆" |
| 摄像头降带宽（720p 广角） | 两路 1080p 时后开的那路 `ENOSPC`，广角起不来 |
| 鱼眼去畸变 | 广角图几何错误（openpilot 广角通路是纯针孔模型） |

前三项在**任何 BYD 车型**上都会挡路，不只是宋 Pro。
