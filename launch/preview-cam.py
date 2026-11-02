#!/home/cosmos/openpilot/cpv8/.venv/bin/python3
"""外置摄像头预览启动器（调焦/调试用）。

会自动扫描外置摄像头并按画面特征标出哪颗是鱼眼、哪颗是普通视角，
然后弹窗让你选，再按选的模式打开预览。

桌面图标：~/Desktop/摄像头预览.desktop  →  调的就是本脚本。

命令行用法（调试/无 GUI）：
  ./preview-cam.py                  # 弹窗选择
  ./preview-cam.py --list           # 只列出识别结果
  ./preview-cam.py --device wide --mode zoom2 --no-gui
"""
import argparse
import os
import shutil
import subprocess
import sys

CPV8 = "/home/cosmos/openpilot/cpv8"
sys.path.insert(0, CPV8)

from openpilot.tools.webcam import camdetect  # noqa: E402

CTL = "/home/cosmos/openpilot/launch/wide-cam-ctl.py"
ROLE_CN = {"normal": "普通视角", "fisheye": "鱼眼/超广角", "unknown": "未识别"}
ROLE_ORDER = {"normal": 0, "fisheye": 1, "unknown": 2}

# mode -> (说明, 分辨率, 是否放大)
MODES = {
  "full":  ("全屏 1080p（推荐）", (1920, 1080), None),
  "uhd":   ("全屏 4K（画面更大，更吃 CPU）", (3840, 2160), None),
  "hd":    ("全屏 720p（最省带宽）", (1280, 720), None),
  "zoom2": ("中心 2 倍放大（判焦最准）", (1920, 1080), (960, 540, 480, 270)),
  "zoom4": ("中心 4 倍放大", (1920, 1080), (480, 270, 720, 405)),
}


def which(*names):
  for n in names:
    p = shutil.which(n)
    if p:
      return p
  return None


def have_display():
  return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def zenity(*args):
  """跑 zenity，返回 stdout（取消时返回 None）。"""
  exe = which("zenity")
  if exe is None:
    return None
  proc = subprocess.run([exe, *args], capture_output=True, text=True)
  if proc.returncode != 0:
    return None
  return proc.stdout.strip()


def error_box(msg):
  print(f"[错误] {msg}", file=sys.stderr)
  z = which("zenity")
  if z and have_display():
    subprocess.run([z, "--error", "--title=摄像头预览", f"--text={msg}", "--width=460"])


def busy_pids():
  """找正在占用 /dev/video* 的进程名，用来提示"先关掉预览"这类问题。"""
  users = []
  for pid in os.listdir("/proc"):
    if not pid.isdigit():
      continue
    fd_dir = f"/proc/{pid}/fd"
    try:
      for fd in os.listdir(fd_dir):
        try:
          target = os.readlink(os.path.join(fd_dir, fd))
        except OSError:
          continue
        if target.startswith("/dev/video"):
          try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
              users.append(f"{f.read().strip()}(pid {pid}) → {target}")
          except OSError:
            pass
          break
    except (OSError, PermissionError):
      continue
  return sorted(set(users))


def scan_devices():
  devs = camdetect.scan()
  devs.sort(key=lambda d: (ROLE_ORDER.get(d["role"], 9), d["port"]))
  return devs


def label_of(dev):
  return f"{ROLE_CN.get(dev['role'], dev['role'])}　{dev['path']}　(端口 {dev['port']}, {dev['name'].split(':')[0]})"


def choose_device(devs):
  if len(devs) == 1:
    return devs[0]
  args = ["--list", "--radiolist", "--title=选择外置摄像头",
          "--text=请选择要预览的摄像头：", "--column=选", "--column=摄像头",
          "--column=设备", "--width=620", "--height=260", "--hide-header"]
  for i, d in enumerate(devs):
    args += ["TRUE" if i == 0 else "FALSE", label_of(d), d["path"]]
  out = zenity(*args)
  if not out:
    return None
  path = out.rsplit("|", 1)[-1].strip()
  for d in devs:
    if d["path"] == path:
      return d
  return None


def choose_mode():
  args = ["--list", "--radiolist", "--title=预览模式",
          "--text=选择预览方式：", "--column=选", "--column=模式",
          "--column=key", "--width=520", "--height=260", "--hide-header"]
  for i, (key, (desc, _, _)) in enumerate(MODES.items()):
    args += ["TRUE" if i == 0 else "FALSE", desc, key]
  out = zenity(*args)
  if not out:
    return None
  return out.rsplit("|", 1)[-1].strip()


def ctl(device, *args):
  """调用 wide-cam-ctl.py，返回 stdout（失败返回 None）。"""
  proc = subprocess.run([sys.executable, CTL, "--device", device, *args],
                        capture_output=True, text=True)
  return proc.stdout.strip() if proc.returncode == 0 else None


def enter_focus_mode(device):
  """开预览前把锐化归零，返回原值。

  锐化是边缘增强，会让失焦的画面"看起来清楚一点"，严重干扰判焦；
  而且这是非破坏性的——只动 sharpness 一项，退出时原样还原。
  """
  orig = ctl(device, "--get", "sharpness")
  ctl(device, "--set", "sharpness=0")
  return orig


def leave_focus_mode(device, orig):
  if orig is not None:
    ctl(device, "--set", f"sharpness={orig}")


def launch(dev, mode, device_path):
  desc, (w, h), crop = MODES[mode]
  if crop is not None:
    cw, ch, cx, cy = crop
    ffplay = which("ffplay")
    if ffplay is None:
      error_box("没找到 ffplay，无法放大预览。")
      return 1
    cmd = [ffplay, "-hide_banner", "-loglevel", "error", "-f", "v4l2",
           "-input_format", "mjpeg", "-video_size", f"{w}x{h}", "-framerate", "30",
           "-fs", "-window_title", f"预览 - {desc}",
           "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={w}:{h}:flags=lanczos", device_path]
  else:
    exe = which("guvcview")
    if exe is None:
      error_box("没找到 guvcview。\n安装：sudo apt install guvcview")
      return 1
    cmd = [exe, "-d", device_path, "-x", f"{w}x{h}", "-f", "MJPG", "-F", "30",
           "-a", "none", "-m", "full"]
  print("启动:", " ".join(cmd))
  sys.stdout.flush()
  return subprocess.call(cmd)


def main():
  ap = argparse.ArgumentParser(description="外置摄像头预览启动器")
  ap.add_argument("--list", action="store_true", help="只列出识别的摄像头")
  ap.add_argument("--device", help="road / wide / /dev/videoN，跳过选择")
  ap.add_argument("--mode", choices=sorted(MODES), default=None,
                  help="预览模式（不给则弹窗选）")
  ap.add_argument("--no-gui", action="store_true", help="不弹窗，配合 --device 使用")
  ap.add_argument("--keep-uvc", action="store_true", help="不改 UVC 参数（保留当前值）")
  args = ap.parse_args()

  devs = scan_devices()

  if args.list:
    if not devs:
      print("没找到外置摄像头。")
      return 1
    for d in devs:
      print(f"  {d['path']:<12} 端口 {d['port']:<6} {ROLE_CN.get(d['role'], d['role']):<10} {d['why']}")
    return 0

  if not devs:
    errs = busy_pids()
    extra = ("\n\n当前被占用：\n" + "\n".join(errs)) if errs else ""
    error_box("没找到外置摄像头（内置摄像头已排除）。\n"
              "检查 USB 是否插好，或先关掉正在预览的程序。" + extra)
    return 1

  # 选设备
  if args.device:
    tgt = args.device.lower()
    if tgt in ("road", "wide"):
      want = "normal" if tgt == "road" else "fisheye"
      pool = [d for d in devs if d["role"] == want]
      dev = pool[0] if pool else None
    else:
      dev = next((d for d in devs if d["path"] == args.device), None)
    if dev is None:
      error_box(f"找不到设备 {args.device}。可选：\n" + "\n".join(label_of(d) for d in devs))
      return 1
  else:
    if not have_display():
      error_box("没有图形界面，请用 --device 指定摄像头。")
      return 1
    dev = choose_device(devs)
    if dev is None:
      print("已取消。")
      return 0

  # 选模式
  mode = args.mode
  if mode is None:
    if args.no_gui:
      mode = "full"
    else:
      mode = choose_mode()
      if mode is None:
        print("已取消。")
        return 0

  # guvcview 只认短路径（内部 30 字符缓冲会把长路径截断），这里转成 /dev/videoN
  short = os.path.realpath(dev["path"])
  print(f"预览 {label_of(dev)}  模式={MODES[mode][0]}  设备={short}")

  busy = busy_pids()
  if busy:
    error_box("有程序正在占用摄像头，先关掉它：\n\n" + "\n".join(busy))
    return 1

  orig_sharp = None
  if not args.keep_uvc:
    orig_sharp = enter_focus_mode(dev["path"])

  try:
    rc = launch(dev, mode, short)
  finally:
    if orig_sharp is not None:
      leave_focus_mode(dev["path"], orig_sharp)
      print(f"已把锐化还原为 {orig_sharp}。")
  return rc


if __name__ == "__main__":
  sys.exit(main())
