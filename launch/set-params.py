#!/usr/bin/env python3
"""给 23 款宋 Pro 预设一批运行时参数（只设语义明确的整型开关）。

用法：  ~/openpilot/launch/set-params.py          # 写入预设
        ~/openpilot/launch/set-params.py --show   # 只读当前值

改完需要重启 op（system/manager/manager.py）才生效。
浮点/百分比类参数（AutoSpeedUptoRoadSpeedLimit 等）请在车机 UI 里调，避免类型写错。
"""
import sys

sys.path.insert(0, "/home/cosmos/openpilot/cpv8")
from openpilot.common.params import Params  # noqa: E402

PRESET = {
    # 红绿灯：0 关 / 1 只停 / 2 停走
    "TrafficLightDetectMode": 2,
    # 动态跟车时距（含变道时）
    "DynamicTFollow": 1,
    "DynamicTFollowLC": 1,
    # 按键映射：0 原厂语义（不改车辆按键行为）
    "CruiseButtonMode": 0,
    "LfaButtonMode": 0,
    # 驾驶员监控：1 = 关。env 里的 NO_DM 在本分支是死变量，真正生效的是这个参数；
    # 为 0 时 tools/webcam/camerad.py 会把 DRIVER_CAM（默认 /dev/video2）也打开，
    # 和路面摄像头撞同一个设备号。
    "DisableDM": 1,
}

WATCH = [
    "TrafficLightDetectMode", "DynamicTFollow", "DynamicTFollowLC",
    "CruiseButtonMode", "LfaButtonMode", "MyDrivingMode", "MyHighModeFactor",
    "AutoSpeedUptoRoadSpeedLimit", "AutoRoadSpeedLimitOffset", "AutoNaviSpeedSafetyFactor",
    "TFollowSpeedAdd", "TFollowSpeedAddM", "StopDistanceCarrot", "LongTuningKpV", "LongTuningKvV",
    "ExperimentalMode", "DisableDM", "IsMetric",
]


def show(p):
    print("==== 当前参数 ====")
    for k in WATCH:
        try:
            print(f"  {k} = {p.get(k)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {k} = <读取失败: {exc}>")


def main():
    p = Params()
    if "--show" in sys.argv:
        show(p)
        return
    print("==== 写入预设 ====")
    for k, v in PRESET.items():
        p.put_int(k, v)
        print(f"  {k} = {p.get_int(k)}")
    print()
    show(p)
    print("\n提示：百分比类参数请在车机 UI 调整；改完重启 op 生效。")


if __name__ == "__main__":
    main()
