#!/usr/bin/env python3
"""按**画面特征**识别外置摄像头的角色，不依赖 USB 端口号。

背景：本机两颗外置摄像头是同一个 DECXIN 模块，VID/PID/序列号全一样，
`/dev/v4l/by-id` 只有一条链接，`/dev/videoN` 会随插拔漂移，只有 by-path 能
区分——但一换 USB 口 by-path 也跟着变。所以"端口"这条路天生不可靠。

可靠的是镜头本身：鱼眼那颗是圆形像场，画面**四角是死黑**；普通视角那颗四角
有内容。本模块就用这个特征判定：

    四角黑像素占比 > 0.5 且 中心足够亮  →  fish-eye（当广角）
    其它                              →  normal（当路面）

用法：
    from openpilot.tools.webcam.camdetect import detect_roles
    roles = detect_roles()      # {'road': '/dev/video2', 'wide': '/dev/video4'}
"""
import glob
import os
import re

import cv2
import numpy as np

BY_PATH = "/dev/v4l/by-path"
SYS_V4L = "/sys/class/video4linux"

# 内置摄像头不参与识别
DEFAULT_EXCLUDE = ("Integrated", "Webcam_HD")

BLACK_LEVEL = 12          # 灰度低于它算"死黑"
FISHEYE_CORNER_RATIO = 0.5
MIN_CENTER_MEAN = 40.0    # 中心太暗（黑灯/挡镜头）就不下结论


def _dev_name(index):
  try:
    with open(f"{SYS_V4L}/video{index}/name", encoding="utf-8") as f:
      return f.read().strip()
  except OSError:
    return f"video{index}"


def _port_of(link):
  """/dev/v4l/by-path/pci-...-usb-0:10.4:1.0-video-index0 -> '10.4'"""
  m = re.search(r"-usb-\d+:([0-9.]+):\d", os.path.basename(link))
  return m.group(1) if m else "?"


def list_capture_devices(exclude=DEFAULT_EXCLUDE):
  """列出所有外置采集设备（只取 video-index0，跳过 metadata 节点和内置摄像头）。"""
  out = []
  for link in sorted(glob.glob(f"{BY_PATH}/*video-index0")):
    base = os.path.basename(link)
    if "usbv2" in base:      # 同一个物理端口会出 usb- 和 usbv2- 两条链接，只留一条
      continue
    real = os.path.realpath(link)
    m = re.search(r"video(\d+)$", real)
    if not m:
      continue
    idx = int(m.group(1))
    name = _dev_name(idx)
    if any(k.lower() in name.lower() for k in exclude):
      continue
    out.append({"path": real, "index": idx, "name": name,
                "port": _port_of(link), "by_path": link})
  return out


def metrics_from_bgr(img):
  """从一张 BGR 图算四角/中心亮度指标（抽出来便于用离线图片验证算法）。"""
  g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
  h, w = g.shape
  k = max(8, min(h, w) // 8)
  corners = np.concatenate([g[:k, :k].ravel(), g[:k, -k:].ravel(),
                            g[-k:, :k].ravel(), g[-k:, -k:].ravel()])
  center = g[h // 2 - k:h // 2 + k, w // 2 - k:w // 2 + k]
  return {
    "corner_black_ratio": float((corners < BLACK_LEVEL).mean()),
    "corner_mean": float(corners.mean()),
    "center_mean": float(center.mean()),
    "shape": (w, h),
  }


def probe(path, frames=15, width=640, height=480):
  """打开设备抓几帧，返回四角/中心亮度指标。设备被占用时返回 None。"""
  cap = cv2.VideoCapture(path)
  if not cap.isOpened():
    return None
  try:
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    img = None
    for _ in range(frames):          # 多抓几帧，等自动曝光收敛
      ok, f = cap.read()
      if ok and f is not None:
        img = f
    return None if img is None else metrics_from_bgr(img)
  finally:
    cap.release()


def probe_image(path):
  """离线图片版 probe，用于验证分类算法。"""
  img = cv2.imread(path)
  return None if img is None else metrics_from_bgr(img)


def classify(metrics):
  """-> ('fisheye'|'normal'|'unknown', 说明)"""
  if metrics is None:
    return "unknown", "设备打不开（被占用？）"
  if metrics["center_mean"] < MIN_CENTER_MEAN:
    return "unknown", f"中心太暗({metrics['center_mean']:.0f})，无法判断"
  if metrics["corner_black_ratio"] > FISHEYE_CORNER_RATIO:
    return "fisheye", f"四角死黑 {metrics['corner_black_ratio'] * 100:.0f}% → 圆形像场"
  return "normal", f"四角有内容(黑占比 {metrics['corner_black_ratio'] * 100:.0f}%) → 普通视角"


def scan(exclude=DEFAULT_EXCLUDE, verbose=False):
  """扫描并逐个分类，返回带分类结果的设备列表。"""
  result = []
  for dev in list_capture_devices(exclude=exclude):
    m = probe(dev["path"])
    role, why = classify(m)
    dev = dict(dev, role=role, why=why, metrics=m)
    result.append(dev)
    if verbose:
      print(f"  {dev['path']:<12} 端口 {dev['port']:<6} {dev['name']:<28} -> {role:<8} {why}")
  return result


def detect_roles(exclude=DEFAULT_EXCLUDE, verbose=False):
  """识别出 路面(road) 和 广角(wide) 各自的设备路径。

  认不出来（个数不对/太暗/被占用）时对应键为 None，调用方应回落到 env 配置。
  """
  devs = scan(exclude=exclude, verbose=verbose)
  fisheye = [d for d in devs if d["role"] == "fisheye"]
  normal = [d for d in devs if d["role"] == "normal"]
  roles = {"road": None, "wide": None}
  if len(normal) >= 1:
    roles["road"] = normal[0]["path"]
  if len(fisheye) == 1:
    roles["wide"] = fisheye[0]["path"]
  elif len(fisheye) > 1:
    # 两颗都像鱼眼，没法确定是哪颗，宁可不认
    if verbose:
      print("  ⚠️ 检测到多颗鱼眼，放弃自动识别")
  if verbose and devs and roles["road"] is None:
    print("  ⚠️ 没找到普通视角摄像头")
  return roles


if __name__ == "__main__":
  import sys
  if len(sys.argv) > 2 and sys.argv[1] == "--image":
    for path in sys.argv[2:]:
      m = probe_image(path)
      role, why = classify(m)
      print(f"{path}: {role:<8} {why}")
    raise SystemExit(0)

  print("=== 外置摄像头扫描 ===")
  roles = detect_roles(verbose=True)
  print()
  print(f"  路面 road = {roles['road']}")
  print(f"  广角 wide = {roles['wide']}")
