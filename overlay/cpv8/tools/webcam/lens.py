#!/usr/bin/env python3
"""鱼眼镜头去畸变。

为什么必须有：openpilot 的广角通路全程用针孔模型——
`common/transformations/model.py:get_warp_matrix()` 就是
`intrinsics @ view_frame_from_device_frame @ device_from_calib @ calib_from_model`，
一个 3x3 单应，**没有任何畸变项**；UI 里 `annotated_camera.cc` 也是同样处理
（代码里还留着 `// TODO: use proper perspective transform?`）。
所以喂原始鱼眼图进去，几何一定是错的，必须在下游使用前先把图掰直。

模型：OpenCV fisheye（Kannala-Brandt）
    r_d = f * θ * (1 + k1·θ² + k2·θ⁴ + k3·θ⁶ + k4·θ⁸)

注意 D 全 0 时退化为纯等距模型 r = f·θ，这正是本机鱼眼实测假定的模型，
所以在没标定前先用 D=[0,0,0,0] 是自洽的，不是瞎填。
"""
import json
import os

import cv2
import numpy as np

DEFAULT_SPEC = {
  # 1280x720 实测估计：像场圆直径 ≈1024px（水平占 80%，左右黑边 148/108）
  # f=326 对应"水平 FOV≈180° 的等距鱼眼"；主点按左右黑边不对称取 660
  "K": [[326.0, 0.0, 660.0],
        [0.0, 326.0, 360.0],
        [0.0, 0.0, 1.0]],
  # Kannala-Brandt 系数：全 0 = 纯等距 r=f·θ（未标定时的自洽起点）
  "D": [0.0, 0.0, 0.0, 0.0],
  "width": 1280,
  "height": 720,
  # fov_scale: 1.0 = 沿用镜头焦距（输出约 126° 水平视角）；调大 = 更窄更"平"
  "fov_scale": 1.0,
}


def load_spec(path=None):
  """读镜头参数 JSON；没给路径或文件不存在就用 DEFAULT_SPEC。"""
  if path and os.path.exists(path):
    with open(path, encoding="utf-8") as f:
      spec = json.load(f)
  else:
    spec = dict(DEFAULT_SPEC)
  for key in ("K", "D", "width", "height"):
    if key not in spec:
      raise ValueError(f"镜头参数缺少 {key}: {spec}")
  spec.setdefault("fov_scale", 1.0)
  return spec


class FisheyeUndistort:
  """预计算 remap 表 + 逐帧 remap。"""

  def __init__(self, width, height, spec):
    K = np.array(spec["K"], dtype=np.float64)
    D = np.array(spec["D"], dtype=np.float64).reshape(-1, 1)
    identity = np.eye(3, dtype=np.float64)

    # 新相机内参直接手工构造。
    # 不用 cv2.fisheye.estimateNewCameraMatrixForUndistortRectify：在接近 180° 的
    # 鱼眼上它会算出退化解（实测主心变 5.7e16，整帧全黑）。
    # fov_scale 越大 = 焦距越长 = 视野越窄、黑角越少。
    fov_scale = float(spec.get("fov_scale", 1.0))
    new_K = np.array([
      [K[0, 0] * fov_scale, 0.0, width / 2.0],
      [0.0, K[1, 1] * fov_scale, height / 2.0],
      [0.0, 0.0, 1.0]], dtype=np.float64)
    self.map1, self.map2 = cv2.fisheye.initUndistortRectifyMap(
      K, D, identity, new_K, (width, height), cv2.CV_16SC2)
    self.new_K = new_K
    self.spec = spec

  def apply(self, bgr):
    return cv2.remap(bgr, self.map1, self.map2,
                     interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))


def build(width, height, path=None, enabled=True):
  """按需构造；参数不合法时返回 None 而不是抛异常，保证摄像头还能出图。"""
  if not enabled:
    return None
  try:
    return FisheyeUndistort(width, height, load_spec(path))
  except Exception as exc:  # noqa: BLE001
    print(f"⚠️ 去畸变初始化失败（将输出原始鱼眼图）: {exc}")
    return None


if __name__ == "__main__":
  import sys
  # 离线验证：python -m tools.webcam.lens in.jpg out.jpg [lens.json]
  if len(sys.argv) < 3:
    print("用法: python -m tools.webcam.lens <输入图> <输出图> [lens.json]")
    raise SystemExit(1)
  img = cv2.imread(sys.argv[1])
  h, w = img.shape[:2]
  spec_path = sys.argv[3] if len(sys.argv) > 3 else None
  ud = FisheyeUndistort(w, h, load_spec(spec_path))
  out = ud.apply(img)
  cv2.imwrite(sys.argv[2], out)
  print(f"已写出 {sys.argv[2]}  ({w}x{h})")
  print(f"新内参 (new K):\n{ud.new_K}")
