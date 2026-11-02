# 23 款宋 Pro DM-i · 适配与调参手册

> 目标车：比亚迪 2023 款宋 Pro DM-i（冠军版，高配自带 ACC）
> 主机：`~/openpilot/cpv8`（carrotpilot v8 PC 版，已编译）
> 本文是**操作手册**，后续 agent 直接照做；所有代码位置都可核对。

---

## 1. 本轮做了什么（可回滚）

| 改动 | 文件 | 内容 | 备份 |
| --- | --- | --- | --- |
| 新增平台 | `opendbc_repo/opendbc/car/byd/values.py` | 加 `CAR.BYD_SONG_PRO_DMI_23`（CarSpecs 抄 22 款：mass 1700 / wheelbase 2.712 / steerRatio 15.0），并把它加进 `PLATFORM_SONG_PLUS_DMI`（决定 safety flag 按宋 Plus 处理） | `values.py.bak.20261027` |
| 新增指纹 | `.../byd/fingerprints.py` | 复制 `BYD_SONG_PRO_DMI_22` 的整组 CAN ID 作为 23 款指纹 | `fingerprints.py.bak.20261027` |
| 模型参数分支 | `.../byd/interface.py` | 车型元组里加入 23 款（minSteerSpeed=0、autoResumeSng 等参数组） | `interface.py.bak.20261027` |
| 运行入口 | `~/openpilot/launch/` | `run-songpro23.sh` + `env/songpro23.env` + `set-params.py` | 新增 |

**验证结果**：`scons -u` 无报错；`CAR.BYD_SONG_PRO_DMI_23 in PLATFORM_SONG_PLUS_DMI → True`；指纹条目 1 组。

**回滚**：

```bash
cd ~/openpilot/cpv8/opendbc_repo/opendbc/car/byd
for f in values.py fingerprints.py interface.py; do cp -f "$f.bak.20261027" "$f"; done
cd ~/openpilot/cpv8 && source .venv/bin/activate && scons -u -j8
```

### 1.1 指纹为什么"照抄 22 款"就行

openpilot 的车型识别是**子集匹配**：车里观测到的 CAN ID 集合 **包含** 平台指纹表里的那一组，就判定为该平台。
所以复制 22 款的集合给 23 款是安全的——只要 23 款实车"不缺这些帧"。如果实车多出若干 ID 不影响匹配；
如果**少了**某个帧就会认不出，那时才需要按实车抓包裁剪指纹。

**认不出时的处理顺序**：
1. 先强制指定：`FINGERPRINT="BYD_SONG_PRO_DMI_23"`（`launch/env/songpro23.env` 里已写好）。
2. 仍不对，试 `FINGERPRINT="BYD_SONG_PRO_DMI_22"`（22 款平台，同为 SONG 组）。
3. 还不行 → 抓实车总线日志，按实际 ID 集重写 23 款指纹。

---

## 2. 你的四个需求 → 对应参数（含建议起点）

### 2.1 红绿灯启停

| 项 | 值/位置 |
| --- | --- |
| 开关 | `TrafficLightDetectMode`：**0 关 / 1 只停 / 2 停走**（`launch/set-params.py` 已预设 **2**） |
| UI | 设置 → 车辆 → `TrafficLight DetectMode` |
| 代码 | `selfdrive/carrot/carrot_functions.py`（读参数、判绿灯起步） |
| 停车距离 | `TrafficStopDistanceAdjust` —— **注意：本分支代码里被硬编码为 1.5，参数没接上**（`carrot_functions.py:82` 那行是注释掉的）。要改只能改代码。 |

**建议**：先 `2`（停走）在**封闭场地/人少路口**验证"红灯能停住、绿灯会起步"；如果出现"红灯前犹豫/急停"，
先降到 `1`（只停不自动起步），确认感知稳定后再回 `2`。

**边界**：这是"信号灯停走辅助"，不做路口博弈（无保护左转、加塞、复杂路口都要人接管）。

### 2.2 让原车 ACC 的加减速别那么冲 —— ⚠️ 本节已按代码订正（2026-11-01）

**旧版本节说错了**：`tuning.py` 里的 `K_ACCEL_*` 表在本分支是**死代码**——全仓 grep 只有定义处，
没有任何消费方（编译产物里也搜不到）。改它不会产生任何效果。

真实机制：

| 位置 | 事实 |
| --- | --- |
| `byd/values.py:158` | `EXP_LONG_CAR` 不含宋 Pro → `openpilotLongitudinalControl = False` |
| `selfdrive/controls/controlsd.py:109` | `CC.longActive` 因此恒为 `False` |
| `byd/carcontroller.py:137 / 229` | `if CC.longActive:` 整段跳过 → `final_accel = 0` |
| `byd/bydcan.py:65-109` | 把相机总线上读到的**原车** `ACC_CMD` 原样转发到 ESC 总线（只重算 `CheckSum`） |

也就是说：**宋 Pro 的纵向现在是「透传」，op 既不算也不改。** 起步迟钝 / 加塞犹豫 / 急加速 / 急减速，
都是原车 DiPilot ACC 自己的行为。

想动它只有两条路（细节、代码草案与风险见 [纵向优化-可行性与方案](纵向优化-可行性与方案.md)）：

1. **有限干预**：在 `bydcan.acc_cmd()` 的透传分支里给 `AccelCmd` 加有界限幅 + 斜率限制
   （能改善"太冲/太狠"，改不了"起步迟钝/加塞"）；Python 改动，不用重编译，`.bak` 备份即可回退。
2. **接管纵向**：把宋 Pro 加进 `EXP_LONG_CAR` 并设 `AlphaLongitudinalEnabled=1`
   （高收益高风险：需要 panda、需要确认 `safety_byd.h` 放行、必须封闭场地验证）。

> ⚠️ 同理，`MyDrivingMode` / `MyEcoModeFactor` / `JerkStartLimit` / `LongTuningKpV` 这些都属于
> **op 纵向自己的参数**，`longActive=False` 时同样不生效——别在这些上面花时间。
> 旧版“调 `K_ACCEL_*` 要重编译”的说法作废。

### 2.3 跟车距离优化

| 参数 | UI 名称 | 范围/步长 | 作用 |
| --- | --- | --- | --- |
| `TFollowSpeedAdd` | GAP: Additional TFs 100km/h ×0.01s | -100 ~ 200，步 5 | 高速时额外跟车时距（正=更远） |
| `TFollowSpeedAddM` | GAP: Additional TFs 40km/h ×0.01s | 同上 | 低速时额外跟车时距 |
| `DynamicTFollow` | Dynamic GAP control | 0/1 | 动态时距（快时拉远、慢时收近） |
| `DynamicTFollowLC` | Dynamic GAP control (LaneChange) | 0/1 | 变道时也应用 |
| `StopDistanceCarrot` | 停车距离 | 整型 | 停稳后与前车保持的距离 |

**建议起点**：`TFollowSpeedAdd = +10`（0.1s 更远）、`DynamicTFollow = 1`，先观察一周再微调 ±5。
原车 ACC 的车距档（方向盘按钮）**仍然生效**，op 的时距是在原车档位基础上叠加。

### 2.4 导航限速接入

本分支自带 **CarrotNavi**（`selfdrive/carrot/carrot_man.py`：订阅 `navRouteNavd` / `navInstruction`，
发布 `navRoute` / `navInstructionCarrot`），配合这几个参数使用：

| 参数 | UI | 范围 | 作用 |
| --- | --- | --- | --- |
| `AutoSpeedUptoRoadSpeedLimit` | CRUISE: Auto speed up (0%) | 0 ~ 200，步 10 | 按**当前道路限速**自动把巡航速度顶上去（百分比） |
| `AutoRoadSpeedLimitOffset` | RoadSpeedLimitOffset(-1) | -1 ~ 100 | `-1`=不用；否则 = 限速 + 偏移（km/h） |
| `AutoNaviSpeedSafetyFactor` | SpeedCameraSafetyFactor(105%) | 80 ~ 120 | 导航限速的安全系数（105% ≈ 允许略超） |
| `AutoNaviSpeedDecelRate`（carrot 参数） | — | 整型×0.01 | 导航降速的减速速率 |
| `UseLaneLineSpeed` | Laneline mode speed(0) | 整型 km/h | 无导航时按车道线速度 |

**接入步骤（需要导航源）**：
1. 车机/主机上要有能产出 `navRouteNavd` 的导航节点（本 fork 的 CarrotNavi 从 `selfdrive/carrot` 侧的
   navd 通道取；PC 版需要额外起导航服务，见 `selfdrive/carrot` 里 nav 相关代码）。
2. 打开 `AutoSpeedUptoRoadSpeedLimit`（如 10% → 限速上浮 10%），`AutoRoadSpeedLimitOffset=-1`（用百分比而非固定偏移）。
3. `AutoNaviSpeedSafetyFactor` 先 105，觉得太冲就 100。
4. 实测：进限速区看 HUD 的 `nRoadLimitSpeed` 是否跟随；`cruise.py` 里做的是
   `cruiseSpeed1 = nRoadLimitSpeed * safetyFactor`，可作校验点。

> 没有导航源时，`UseLaneLineSpeed`（按车道线限速）和原车 ACC 手动设速是兜底方案。

---

## 3. 调试流程（照这个顺序，别跳步）

### 阶段 0 · 静态检查（桌面，不接车）

```bash
cd ~/openpilot/cpv8 && source .venv/bin/activate && scons -u -j8      # 编译过
PYTHONPATH=opendbc_repo .venv/bin/python -c "
from opendbc.car.byd.values import CAR, PLATFORM_SONG_PLUS_DMI
print(CAR.BYD_SONG_PRO_DMI_23 in PLATFORM_SONG_PLUS_DMI)"            # True
~/openpilot/launch/set-params.py --show                              # 参数快照
```

### 阶段 1 · 空跑（不接车，验证摄像头/软件链路）

```bash
~/openpilot/launch/run-songpro23.sh
```
- UI 是否出画面、HUD 是否有速度/方向角；
- 终端 **Ctrl+C** 退出（点 × 无效）。

### 阶段 2 · 接车静态（点火，P 档）

- 确认 `carState` 能读到：`vEgo`、`steeringAngleDeg`、`cruiseState.available/enabled`、`buttonEvents`；
- 按方向盘 SET / RES / 车距 / cancel，看 `buttonEvents` 是否出现对应类型（`accelCruise`/`decelCruise`/
  `gapAdjustCruise`/`cancel`）——**这是验证"原车按键是否被 op 看见"的最直接办法**。

### 阶段 3 · 只开横向

- `ExperimentalMode` 关，**只让它控方向**；速度由原车 ACC 负责（你踩/它跟）。
- 看是否画龙：PlotJuggler 里 `steeringAngleDeg` 应平滑跟随 `/modelV2` 的 `desiredCurvature`；
  抖动大→先查摄像头安装角度/焦距，再动 `STEER_RATIO`/`PathOffset`。

### 阶段 4 · 原车 ACC 联动

- 打开 `TrafficLightDetectMode=1`（先只停不自动走），低速找个人少的路口验证；
- 纵向：**当前 op 不控纵向**（见 §2.2），只能做"有限干预"或接管，别去调 `K_ACCEL_*`（死代码）；
- 每次只改一个变量，**同路段对比**，记录到 [调参记录.md](调参记录.md)；指标定义见
  [纵向优化-可行性与方案](纵向优化-可行性与方案.md) §3。

### PlotJuggler 必看信号

| 信号 | 看什么 |
| --- | --- |
| `carState.aEgo` vs `longitudinalPlan.aTarget` | 原车 ACC 实际加减速 vs 计划值（差太多说明原车 long 不听话） |
| `carState.steeringAngleDeg` / `steeringTorque` | 横向是否抖、是否抢 |
| `carrotMan.trafficState` / `Carrot` HUD | 红绿灯状态机 |
| `controlsState.latActive` / `enabled` | 接管状态 |
| `radarState.leadOne` | 有雷达时前车跟踪质量 |

---

## 4. 用户实践案例（社区可查）

| 来源 | 结论/可借鉴点 |
| --- | --- |
| cpv8 更新日志（2025-08-25） | 「**纵向接入 byd 汉前置雷达数据**」「接入车辆底盘 IMU」「yawRate 适配」「驾驶监控默认关」——说明 PC 版纵向是**用原车 ACC + 雷达/底盘数据**这条路走通的 |
| 同一日志（2025-07-31） | 「整合 yysnet BYD 车型适配」「修改配置/日志路径」「简化安装」——BYD 适配的源头是 yysnet 的 opendbc 移植 |
| B 站《比亚迪 Carrotpilot 参数调整》（2025-10） | 社区里确实按"跟车时距 / K_ACCEL 缩放 / 驾驶模式"这套调，和 §2 的做法一致 |
| B 站《Openpilot 比亚迪适配移植中的那些坑》（35 分钟） | 重点坑：接线/固件指纹/纵向往复、EPS 报错；与 §6/§8 呼应 |
| `shemps/byd-atto3-openpilot-port`（GitHub，实测手册） | BYD 总线拓扑：底盘 500k 经典 CAN + **私有 CAN-FD 2Mbit**（相机+雷达）；雷达目标要读私有总线 |
| helper 工具 `config/cars/BYD_TANG_DMI_23.env` | 实车参数：`ROAD_FOCAL=2320`、`WIDE_FOCAL=605`、1920×1080、`NO_DM=1`、`JY62=2` —— **本文 §1 的 env 就是照这个起步** |
| 公众号《教你手搓 Openpilot PC 版-软件篇》 | 摄像头编号排查法（拔插 `ls /dev/video*`）、`Ctrl+C` 关 op、双摄 `WIDE_CAM` |

> 这些是"社区实践"，不是厂商验证；同一参数在不同车上表现不同，务必自己实测。

---

## 5. 问题一：装了 OP，原车 ACC 按钮还有用吗？

**有，而且默认必须用。** 依据（本机代码）：

1. **宋 Pro 不走 op 纵向**：`interface.py` 里 `EXP_LONG_CAR = {HAN_*, TANG_DM, SONG_PLUS_DMI_21}`，
   宋 Pro 不在其中 → `openpilotLongitudinalControl = False` → **纵向（油门/刹车）仍然是原车 ACC 在做**。
2. 原车按键被 op 读成事件（`carstate.py:224-228`）：

   | 车上按键 | 底层信号 | op 事件 |
   | --- | --- | --- |
   | SET | `PCM_BUTTONS.BTN_AccSetReset`（1） | `decelCruise` |
   | RES | 同上（3） | `accelCruise` |
   | 车距 +/− | `BTN_AccDistanceIncrease/Decrease` | `gapAdjustCruise` |
   | 取消 | `BTN_AccCancel` | `cancel` |
   | ACC 主开关 | `BTN_TOGGLE_ACC_OnOff` | → `ret.latEnabled`（横向使能同步） |

3. **横向（LKA）跟 ACC 主开关联动**：`carstate.py:172` `ret.latEnabled = lkas_isMainSwOn and lkas_allowed_speed`，
   `cruise.py` 每帧把 `latEnabled` 同步到横向控制——也就是说 **按 ACC 主开关，等于同时切换 op 的横向接管**。
4. 按键语义可以改但**不建议**：`CruiseButtonMode`（0:Normal,1:User1,2:User2）与 `LfaButtonMode`
   （0:Normal, 1:Decel&Stop&LeadCarReady）在 `selfdrive/car/cruise.py` 里被读取；默认 0 = 原厂语义。

**结论**：
- SET/RES/车距/cancel **继续按原车 ACC 的语义工作**（因为纵向就是原车 ACC）。
- 按 ACC 主开关会同时让 op 的横向使能/退出——**这就是"用原车 ACC 开关同时控 op 横向"的设计**。
- 你**不会**失去原车 ACC 的任何功能；op 只是在你开 ACC 时接管方向盘。
- 例外：如果你把宋 Pro 加进 `EXP_LONG_CAR`（开 op 全长控），SET/RES 会变成"设定 op 巡航速度"，
  原车 ACC 的纵向逻辑被替代——**那时按键语义才变**。

---

## 6. 问题二：22 款宋 Pro 的 ACC 和 23 款差别大吗？

**从 openpilot 角度看：差别不大（同平台）**，理由与做法：

| 维度 | 22 款 | 23 款（冠军版） | 对 op 的影响 |
| --- | --- | --- | --- |
| 平台分组 | `PLATFORM_SONG_PLUS_DMI` | 同（本次已把 23 款并入） | 安全标志一致（`SONG_PLUS_DMI`） |
| ACC 按键帧 | `PCM_BUTTONS 0x3B0` | 同（同平台沿用） | 按键解析代码不用改 |
| ACC 状态帧 | `ACC_HUD_ADAS` / `ACC_MPC_STATE` | 同 | `carstate.py` 直接复用 |
| 硬件方案 | 单目前视 + 毫米波（DiPilot L2） | 同级别；23 款是 facelift（外观/内饰/车机），智驾硬件同代 | 雷达/DBC 可能微调 |
| 车型指纹 | 已有（`BYD_SONG_PRO_DMI_22`） | **本次补的（复制 22 款）** | 认不出时才需裁剪 |

**但要注意（诚实提示）**：
1. 我没找到公开的"22 vs 23 款 CAN 矩阵对比"文档，上面的判断基于**同平台代码复用 + 社区移植经验**，
   不等于厂商确认。
2. 23 款冠军版换了车机/内饰，**ECU 固件版本可能不同**（同一帧 ID 的字段定义一般不变，但固件查询会变）。
   如果车型认不出，按 §1.1 的顺序处理。
3. 真要确认：接上后看 `carParams.carFingerprint` 是不是 `BYD_SONG_PRO_DMI_23`；再对比 `0xF195` 的 ECU 版本。

---

## 7. 参数速查表（UI ↔ 内部 key）

| UI 名称 | key | 范围/步长 | 备注 |
| --- | --- | --- | --- |
| TrafficLight DetectMode | `TrafficLightDetectMode` | 0–2，步 1 | 红绿灯启停 |
| Dynamic GAP control | `DynamicTFollow` | 0/1 | 动态时距 |
| Dynamic GAP control (LC) | `DynamicTFollowLC` | 0/1 | 变道时 |
| GAP: Additional TFs 100km/h | `TFollowSpeedAdd` | −100–200，步 5 | ×0.01s |
| GAP: Additional TFs 40km/h | `TFollowSpeedAddM` | −100–200，步 5 | ×0.01s |
| CRUISE: Auto speed up | `AutoSpeedUptoRoadSpeedLimit` | 0–200，步 10 | 按限速顶速（%） |
| RoadSpeedLimitOffset | `AutoRoadSpeedLimitOffset` | −1–100，步 1 | −1=不用 |
| SpeedCameraSafetyFactor | `AutoNaviSpeedSafetyFactor` | 80–120，步 1 | % |
| LONG: JERK START | `JerkStartLimit` | 1–50，步 1 | ×0.1 |
| LONG: P / I Gain | `LongTuningKpV` / `LongTuningKiV` | 0–150 / 0–2000 | 谨慎 |
| Button: Cruise Mode | `CruiseButtonMode` | 0–2 | 0=原厂 |
| Button: LFA Mode | `LfaButtonMode` | 0–1 | 0=原厂 |
| DRIVEMODE: Select | `MyDrivingMode` | 整型 | 配合 ECO/SAFE/HIGH 比例 |

> 注意：上表里 `JerkStartLimit` / `LongTuningKpV/KiV` / `MyDrivingMode` **只在 op 接管纵向时才生效**，
> 宋 Pro 当前 `longActive=False`，这些值改了也白改（见 §2.2）。

代码层参数（改完要重编译）：`tuning.py` 的 `STEERING_ANGLE_OFFSET`、`DASHSPEED_*`、
`DISABLE_EPS_*`；`values.py` 的 `CarSpecs`（mass/wheelbase/steerRatio）、`CarControllerParams` 的 jerk 表。
（`K_ACCEL_*` 不在其中——它是死代码，见 §2.2。）

---

## 8. 排障

| 现象 | 处理 |
| --- | --- |
| 认不出车型 | 强制 `FINGERPRINT`；再不行抓包改指纹（§1.1） |
| 红灯不停 | `TrafficLightDetectMode` 是否 2；算力是否够（`HUD CPU/GPU`）；模型是否看到灯 |
| 绿灯不起步 | 同 1/2 模式；`carrot_stay_stop` 是否被别的条件卡住 |
| 画龙 | 摄像头安装/焦距 → `STEERING_ANGLE_OFFSET` → `CarSpecs.steerRatio` |
| 刹车太冲 / 起步迟钝 | 当前 op 不控纵向 → 见 [纵向优化-可行性与方案](纵向优化-可行性与方案.md)（有限限幅 or op 长控）；调 `K_ACCEL_*` 无效 |
| 限速不跟 | 导航源是否活着（`navRouteNavd` 有数据）、`AutoSpeedUptoRoadSpeedLimit` 是否 >0 |
| EPS 报错 | `DISABLE_EPS_WARNING/TEMPORARY/PERMANENT` 临时关检查（先查硬件） |

---

## 9. 待办

1. 硬件到位后：先跑 §3 阶段 2，确认 23 款指纹是否命中；命中就把 `FINGERPRINT` 那行注释掉。
2. 抓一次私有总线，确认雷达帧，再决定 `BYD_RADAR=1`。
3. 调参记录：**已建** [调参记录.md](调参记录.md)（2026-10-28，含模板 / 基线条目 / 回退索引），
   每次上车记一条：日期 / 参数 / 路段 / 感受。
4. 若导航源确认可用，再开 `AutoSpeedUptoRoadSpeedLimit`。
