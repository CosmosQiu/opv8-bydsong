#!/usr/bin/env python3
"""鱼眼棋盘格标定：产出 lens.py / camerad 能直接读的 JSON（K + D）。

当前 `launch/env/wide_lens.json` 里的 K/D 是**实测估计值**（等距模型，D=0），
f 不确定度约 ±10%。想要准确的畸变系数就走这个流程。

用法：
  # 1. 拍板：用 preview-cam.py 或 guvcview 对着棋盘格拍 20~30 张，
  #    覆盖画面四角、正对、倾斜 30~45°、远近各种距离。建议存到 /tmp/calib/
  mkdir -p /tmp/calib
  # （拍的时候分辨率要和 OP 里广角一致：1280x720）

  # 2. 标定
  cd ~/openpilot/cpv8
  ./.venv/bin/python -m tools.webcam.calib_lens /tmp/calib \\
      --cols 9 --rows 6 --square 0.025 \\
      --out ~/openpilot/launch/env/wide_lens.json

  参数说明：--cols/--rows 是**内角点**数（不是格子数），--square 是方格边长（米）。

判定标准：RMS < 0.5 px 算合格；> 1 px 说明拍的覆盖不够、板子不平或模糊。
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np


def collect(images, pattern, square):
  objp = np.zeros((1, pattern[0] * pattern[1], 3), np.float32)
  objp[0, :, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square

  obj_pts, img_pts, used, size = [], [], [], None
  criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
  for path in images:
    img = cv2.imread(path)
    if img is None:
      print(f"  跳过（读不到）: {path}")
      continue
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    size = gray.shape[::-1]
    ok, corners = cv2.findChessboardCorners(gray, pattern, None,
                                            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
      print(f"  跳过（没找到角点）: {os.path.basename(path)}")
      continue
    corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
    obj_pts.append(objp.copy())
    img_pts.append(corners.astype(np.float64))
    used.append(path)
    print(f"  ✓ {os.path.basename(path)}")
  return obj_pts, img_pts, used, size


def main():
  ap = argparse.ArgumentParser(description="鱼眼棋盘格标定")
  ap.add_argument("image_dir", help="棋盘格图片目录")
  ap.add_argument("--cols", type=int, default=9, help="内角点列数（默认 9）")
  ap.add_argument("--rows", type=int, default=6, help="内角点行数（默认 6）")
  ap.add_argument("--square", type=float, default=0.025, help="方格边长（米，默认 0.025）")
  ap.add_argument("--out", default="/home/cosmos/openpilot/launch/env/wide_lens.json")
  ap.add_argument("--fov-scale", type=float, default=1.0, help="去畸变输出缩放，1.0=沿用焦距")
  args = ap.parse_args()

  pattern = (args.cols, args.rows)
  exts = ("*.jpg", "*.jpeg", "*.png")
  images = sorted({p for e in exts for p in glob.glob(os.path.join(args.image_dir, e))})
  if not images:
    sys.exit(f"{args.image_dir} 里没有图片")

  print(f"在 {len(images)} 张图里找 {pattern[0]}x{pattern[1]} 内角点…")
  obj_pts, img_pts, used, size = collect(images, pattern, args.square)
  if len(used) < 10:
    sys.exit(f"只成功找到 {len(used)} 张有效图，至少需要 10 张（建议 20~30 张）")

  K = np.zeros((3, 3))
  D = np.zeros((4, 1))
  flags = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW
  criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-6)
  print("开始标定…")
  rms, K, D, _, _ = cv2.fisheye.calibrate(obj_pts, img_pts, size, K, D,
                                          flags=flags, criteria=criteria)
  print(f"\nRMS 重投影误差 = {rms:.4f} px  {'✅ 合格' if rms < 0.5 else '⚠️ 偏大，建议补拍/重新拍'}")

  spec = {
    "_comment": "由 tools/webcam/calib_lens.py 标定生成",
    "_calibration": {"rms": round(float(rms), 4), "images_used": len(used),
                     "pattern": list(pattern), "square_m": args.square},
    "K": [[round(float(K[i][j]), 6) for j in range(3)] for i in range(3)],
    "D": [round(float(D[i][0]), 8) for i in range(4)],
    "width": int(size[0]),
    "height": int(size[1]),
    "fov_scale": args.fov_scale,
  }
  with open(args.out, "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=2)
  print(f"已写出 {args.out}")
  print(json.dumps({"K": spec["K"], "D": spec["D"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
