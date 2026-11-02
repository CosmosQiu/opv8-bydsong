#!/usr/bin/env python3
import threading
import os
from collections import namedtuple

from msgq.visionipc import VisionIpcServer, VisionStreamType
from cereal import messaging

from openpilot.tools.webcam.camera import Camera, CameraMJPG
from openpilot.common.realtime import Ratekeeper

WIDE_CAM = os.getenv("WIDE_CAM")
# 鱼眼去畸变：openpilot 广角通路是纯针孔模型，原始鱼眼图必须先掰直
WIDE_UNDISTORT = os.getenv("WIDE_UNDISTORT")
WIDE_LENS_FILE = os.getenv("WIDE_LENS_FILE")
from openpilot.common.params import Params
params = Params()
disable_dm = params.get_int("DisableDM") > 0
CameraType = namedtuple("CameraType", ["msg_name", "stream_type", "cam_id", "width", "height", "fps"])


def _camera_type(msg_name, stream_type, prefix, default_id):
  """按前缀从环境变量读每一路的设备号和分辨率：<PREFIX>_CAM/_WIDTH/_HEIGHT/_FPS。

  PC 版多摄一般挂在同一条 USB 2.0 总线上，等时带宽有限：两路都申请 1920x1080 时
  后开的那一路会 VIDIOC_STREAMON: No space left on device（ENOSPC），所以必须能
  按单路降分辨率（例如广角降到 1280x720）。
  """
  return CameraType(
    msg_name, stream_type,
    os.getenv(f"{prefix}_CAM", default_id),
    os.getenv(f"{prefix}_WIDTH"),
    os.getenv(f"{prefix}_HEIGHT"),
    os.getenv(f"{prefix}_FPS"),
  )


CAMERAS = [
  _camera_type("roadCameraState", VisionStreamType.VISION_STREAM_ROAD, "ROAD", "0"),
]
if not disable_dm:
  CAMERAS.append(_camera_type("driverCameraState", VisionStreamType.VISION_STREAM_DRIVER, "DRIVER", "2"))
if WIDE_CAM:
  CAMERAS.append(_camera_type("wideRoadCameraState", VisionStreamType.VISION_STREAM_WIDE_ROAD, "WIDE", WIDE_CAM))


def resolved_cameras():
  """CAM_AUTODETECT 有值时，按画面特征识别哪颗是路面/广角，覆盖 ROAD_CAM/WIDE_CAM 的路径。

  为什么需要：两颗外置摄像头是同一个 DECXIN 模块，VID/PID/序列号全一样，
  /dev/videoN 会漂、/dev/v4l/by-id 只有一条链接，唯一能区分的是 USB 端口；
  可一换端口 by-path 也跟着变。镜头差异（鱼眼四角死黑）反而是稳定特征，
  所以换口、甚至把两颗物理对调，都不用改配置。

  识别失败（设备被预览程序占用等）时原样返回 env 里的配置。
  """
  cams = list(CAMERAS)
  if os.getenv("CAM_AUTODETECT") is None:
    return cams

  from openpilot.tools.webcam.camdetect import detect_roles
  print("CAM_AUTODETECT 已开启，按画面特征识别摄像头…")
  roles = detect_roles(verbose=True)
  if not roles.get("road") and not roles.get("wide"):
    print("⚠️ 自动识别失败，回落到 ROAD_CAM/WIDE_CAM 配置")
    return cams
  if not roles.get("wide"):
    print("⚠️ 没认出广角，继续用 WIDE_CAM 配置")

  out = []
  for c in cams:
    if c.msg_name == "roadCameraState" and roles.get("road"):
      c = c._replace(cam_id=roles["road"])
    elif c.msg_name == "wideRoadCameraState" and roles.get("wide"):
      c = c._replace(cam_id=roles["wide"])
    out.append(c)
  return out

class Camerad:
  def __init__(self):
    self.pm = messaging.PubMaster([c.msg_name for c in CAMERAS])
    self.vipc_server = VisionIpcServer("camerad")

    self.cameras = []
    for c in resolved_cameras():
      # cam_id 可以是裸编号(2 -> /dev/video2)，也可以直接给设备路径
      # （/dev/v4l/by-path/... 或自动识别给出的 /dev/videoN）。
      cam_id = str(c.cam_id)
      cam_device = cam_id if cam_id.startswith("/") else f"/dev/video{cam_id}"
      print(f"opening {c.msg_name} at {cam_device} "
            f"(请求 {c.width or 1920}x{c.height or 1080}@{c.fps or 20})")
      lens_file = None
      if WIDE_UNDISTORT and c.msg_name == "wideRoadCameraState":
        # 没给参数文件就用 lens.DEFAULT_SPEC（等距模型 f≈326），也可传空串
        lens_file = WIDE_LENS_FILE or ""
      cam = CameraMJPG(c.msg_name, c.stream_type, cam_device, c.width, c.height, c.fps, lens_file)
      self.cameras.append(cam)
      self.vipc_server.create_buffers(c.stream_type, 20, cam.W, cam.H)

    self.vipc_server.start_listener()

  def _send_yuv(self, yuv, frame_id, pub_type, yuv_type):
    eof = int(frame_id * 0.05 * 1e9)
    self.vipc_server.send(yuv_type, yuv, frame_id, eof, eof)
    dat = messaging.new_message(pub_type, valid=True)
    msg = {
      "frameId": frame_id,
      "transform": [1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0]
    }
    setattr(dat, pub_type, msg)
    self.pm.send(pub_type, dat)

  def camera_runner(self, cam):
    rk = Ratekeeper(20, None)
    for yuv in cam.read_frames():
      self._send_yuv(yuv, cam.cur_frame_id, cam.cam_type_state, cam.stream_type)
      cam.cur_frame_id += 1
      rk.keep_time()

  def run(self):
    threads = []
    for cam in self.cameras:
      cam_thread = threading.Thread(target=self.camera_runner, args=(cam,))
      cam_thread.start()
      threads.append(cam_thread)

    for t in threads:
      t.join()


def main():
  camerad = Camerad()
  camerad.run()


if __name__ == "__main__":
  main()
