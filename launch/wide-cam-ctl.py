#!/usr/bin/env python3
"""超广角（鱼眼）摄像头 UVC 参数读写工具。

本机没装 v4l-utils（没有 v4l2-ctl），所以直接用 ioctl 操作 V4L2 控制项，
不引入任何新依赖。

用法：
  ./wide-cam-ctl.py --show                      # 读 /dev/video4 当前全部控制项
  ./wide-cam-ctl.py --preset                    # 应用下面的 WIDE_PRESET
  ./wide-cam-ctl.py --set gain=90 sharpness=3   # 临时改单项
  ./wide-cam-ctl.py --device /dev/video2 --show # 换设备

⚠️ 控制项只在**没人开流**时能改（guvcview / op 占用时会 EBUSY）。
⚠️ 这些是**硬件层**参数，重启/重插后可能回到默认；要固化见 --preset 的说明。

参数含义速查见 ~/openpilot/docs/超广角-鱼眼-调试参数.md
"""
import argparse
import fcntl
import os
import struct
import sys

VIDIOC_QUERYCTRL = 0xC0445624  # _IOWR('V', 36, struct v4l2_queryctrl) 68 字节
VIDIOC_G_CTRL = 0xC008561B     # _IOWR('V', 27, struct v4l2_control)    8 字节
VIDIOC_S_CTRL = 0xC008561C     # _IOWR('V', 28, struct v4l2_control)    8 字节

V4L2_CTRL_FLAG_DISABLED = 0x0001
V4L2_CTRL_FLAG_NEXT_CTRL = 0x80000000
V4L2_CTRL_TYPE_INTEGER = 1
V4L2_CTRL_TYPE_BOOLEAN = 2
V4L2_CTRL_TYPE_MENU = 3
V4L2_CTRL_TYPE_BUTTON = 4

# 本机两颗 DECXIN 摄像头实测出来的控制项（0x0098xxxx = V4L2 CID 基础段）
KNOWN = {
  0x00980900: "brightness",
  0x00980901: "contrast",
  0x00980902: "saturation",
  0x00980903: "hue",
  0x0098090c: "white_balance_auto",
  0x00980910: "gamma",
  0x00980913: "gain",
  0x00980918: "power_line_frequency",
  0x0098091a: "white_balance_temp",
  0x0098091b: "sharpness",
  0x0098091c: "backlight_comp",
  # camera class（0x009a09xx）：这两颗模块会暴露，但对焦扫全范围画面不变、
  # 是固焦镜头的假控制项；曝光模式当前=3(APERTURE_PRIORITY)，设 0 会 EINVAL。
  0x009a0901: "exposure_auto",
  0x009a0902: "exposure_absolute",
  0x009a090a: "focus_absolute",
  0x009a090c: "focus_auto",
}
CID_BY_NAME = {v: k for k, v in KNOWN.items()}

# 两颗 DECXIN 是**同一个模块、只换了镜头**，所以 UVC 范围和默认值完全相同，
# 但建议值要分开：鱼眼边缘衰减严重 → 更吃 contrast/sharpness；普通镜头通光好 → gain 保守。
PRESETS = {
  # 鱼眼超广角（USB 端口 10.2，OP 里的 WIDE_CAM）
  "wide": {
    "brightness": 0,            # -64..64，默认 0；整体偏暗/偏亮优先动这个
    "contrast": 20,             # 0..95，默认 0（很平），鱼眼建议 15~30
    "saturation": 80,           # 0..255，默认 70；过高会让路面颜色失真
    "gamma": 100,               # 64..300，默认 100；暗部细节差可提到 130~160
    "gain": 90,                 # 0..255，默认 100；过曝时往下压，暗时往上加
    "sharpness": 3,             # 0..7，默认 0；鱼眼边缘发虚，2~4 比较合适
    "backlight_comp": 48,       # 16..160，默认 64；强逆光时压低可减过曝
    "power_line_frequency": 1,  # 0=off 1=50Hz 2=60Hz
    "white_balance_auto": 1,    # 1=自动；固定色温时设 0 并给 white_balance_temp
  },
  # 普通视角（USB 端口 10.3，OP 里的 ROAD_CAM）
  "road": {
    "brightness": 0,
    "contrast": 15,             # 普通镜头本身对比度就比鱼眼好，不用推太高
    "saturation": 75,
    "gamma": 100,
    "gain": 95,                 # 镜头通光好，gain 可以比鱼眼高一点
    "sharpness": 2,             # 边缘没有鱼眼那么虚
    "backlight_comp": 56,
    "power_line_frequency": 1,
    "white_balance_auto": 1,
  },
}

# 兼容旧名字
WIDE_PRESET = PRESETS["wide"]


def _query(fd, cid):
  buf = bytearray(struct.pack("<II32siiiiII", cid, 0, b"", 0, 0, 0, 0, 0, 0))
  try:
    fcntl.ioctl(fd, VIDIOC_QUERYCTRL, buf)
  except OSError:
    return None
  cid_, typ, name, mn, mx, st, df, fl, _ = struct.unpack("<II32siiiiII", buf)
  return {
    "id": cid_, "type": typ, "name": name.split(b"\0")[0].decode(errors="replace"),
    "min": mn, "max": mx, "step": st, "default": df, "flags": fl,
  }


def enum_controls(fd):
  """枚举全部控制项。

  用 V4L2_CTRL_FLAG_NEXT_CTRL 让内核直接给出"下一个控制项"，是 O(n) 的；
  早期版本这里是按 ID 暴力扫 0x00980001~0x009A0000（13 万次 ioctl），
  单次调用要 11 秒，拖慢了所有脚本调用。
  """
  found = {}

  # (a) NEXT_CTRL 走一遍：能顺带发现 camera class(0x009a09xx) 的控制项
  cid = 0x00980001
  while True:
    c = _query(fd, cid | V4L2_CTRL_FLAG_NEXT_CTRL)
    if c is None:
      break
    cid = (c["id"] & ~V4L2_CTRL_FLAG_NEXT_CTRL) + 1
    if c["type"] == V4L2_CTRL_TYPE_BUTTON or (c["flags"] & V4L2_CTRL_FLAG_DISABLED):
      continue
    found[c["id"]] = c

  # (b) uvcvideo 的 NEXT_CTRL 会漏掉一部分实例化较晚的项（实测漏 contrast/hue/
  #     sharpness），所以再显式扫两段已知区间补齐。每段只 256 次 ioctl，很快。
  for base in (0x00980900, 0x009a0900):
    for cid in range(base, base + 0x100):
      if cid in found:
        continue
      c = _query(fd, cid)
      if c is None:
        continue
      if c["type"] == V4L2_CTRL_TYPE_BUTTON or (c["flags"] & V4L2_CTRL_FLAG_DISABLED):
        continue
      found[c["id"]] = c

  if found:
    return [found[k] for k in sorted(found)]

  return []


def get_ctrl(fd, cid):
  buf = bytearray(struct.pack("<ii", cid, 0))
  fcntl.ioctl(fd, VIDIOC_G_CTRL, buf)
  return struct.unpack("<ii", buf)[1]


def set_ctrl(fd, cid, value):
  fcntl.ioctl(fd, VIDIOC_S_CTRL, bytearray(struct.pack("<ii", cid, int(value))))


def fmt_value(ctrl, val):
  if ctrl["type"] == V4L2_CTRL_TYPE_BOOLEAN:
    return f"{val} ({'开' if val else '关'})"
  if ctrl["type"] == V4L2_CTRL_TYPE_MENU:
    label = {0x00980918: {0: "off", 1: "50Hz", 2: "60Hz"}}.get(ctrl["id"], {})
    return f"{val} ({label.get(val, 'menu')})"
  return str(val)


def main():
  ap = argparse.ArgumentParser(description="超广角摄像头 UVC 参数读写")
  ap.add_argument("--device", default="/dev/video4", help="设备节点（默认 /dev/video4）")
  ap.add_argument("--show", action="store_true", help="打印当前全部控制项")
  ap.add_argument("--preset", nargs="?", const="wide", choices=sorted(PRESETS),
                  help="应用预设：wide(鱼眼,默认) 或 road(普通视角)")
  ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VAL", help="临时设置单项")
  ap.add_argument("--get", nargs="*", default=[], metavar="KEY", help="只打印指定项的值（便于脚本调用）")
  args = ap.parse_args()

  if not (args.show or args.preset or args.set or args.get):
    ap.error("至少要给 --show / --preset / --set / --get 之一")

  try:
    fd = os.open(args.device, os.O_RDWR | os.O_NONBLOCK)
  except OSError as e:
    sys.exit(f"打不开 {args.device}: {e}")

  try:
    # 只有在需要全表时才枚举：--get/--set 只查用到的那一项，避免 13 万次 ioctl
    ctrls = {c["id"]: c for c in enum_controls(fd)} if (args.show or args.preset) else {}

    def info(cid):
      """按需查询单个控制项（不触发全表枚举）。"""
      if cid not in ctrls:
        c = _query(fd, cid)
        if c is None:
          return None
        ctrls[cid] = c
      return ctrls[cid]

    if args.get:
      vals = []
      for key in args.get:
        key = key.strip()
        if key not in CID_BY_NAME:
          sys.exit(f"未知参数 {key!r}，可用：{', '.join(sorted(CID_BY_NAME))}")
        cid = CID_BY_NAME[key]
        if info(cid) is None:
          sys.exit(f"设备没有控制项 {key}")
        vals.append(str(get_ctrl(fd, cid)))
      print(" ".join(vals))
      return

    if args.preset:
      preset = PRESETS[args.preset]
      print(f"== 应用 {args.preset} 预设到 {args.device} ==")
      for key, want in preset.items():
        cid = CID_BY_NAME[key]
        c = info(cid)
        if c is None:
          print(f"  {key:<20} 跳过（设备无此控制项）")
          continue
        val = max(c["min"], min(c["max"], want))
        if val != want:
          print(f"  {key:<20} {want} 超出范围 [{c['min']},{c['max']}]，夹到 {val}")
        try:
          set_ctrl(fd, cid, val)
          print(f"  {key:<20} -> {fmt_value(c, get_ctrl(fd, cid))}")
        except OSError as e:
          print(f"  {key:<20} 写入失败: {e}")
      print()

    if args.set:
      print(f"== 临时设置 {args.device} ==")
      for kv in args.set:
        if "=" not in kv:
          sys.exit(f"格式应为 key=value，收到 {kv!r}")
        key, raw = kv.split("=", 1)
        key = key.strip()
        if key not in CID_BY_NAME:
          sys.exit(f"未知参数 {key!r}，可用：{', '.join(sorted(CID_BY_NAME))}")
        cid = CID_BY_NAME[key]
        c = info(cid)
        if c is None:
          sys.exit(f"设备没有控制项 {key}")
        val = int(float(raw))
        val = max(c["min"], min(c["max"], val))
        set_ctrl(fd, cid, val)
        print(f"  {key:<20} -> {fmt_value(c, get_ctrl(fd, cid))}")
      print()

    if args.show or args.preset or args.set:  # --get 是给脚本用的，不刷全表
      if not ctrls:
        ctrls.update({c["id"]: c for c in enum_controls(fd)})
      if not ctrls:
        sys.exit("没枚举到控制项")
      print(f"== {args.device} 当前控制项 ==")
      for cid in sorted(ctrls):
        c = ctrls[cid]
        try:
          cur = get_ctrl(fd, cid)
        except OSError:
          cur = None
        alias = KNOWN.get(cid, "")
        extra = f"  [{alias}]" if alias else ""
        print(f"  0x{cid:08x} {c['name']:<28} = {fmt_value(c, cur) if cur is not None else '?'}"
              f"   (范围 {c['min']}..{c['max']} 步长 {c['step']} 默认 {c['default']}){extra}")
  finally:
    os.close(fd)


if __name__ == "__main__":
  main()
