#!/usr/bin/env bash
# 启动 openpilot（23 款宋 Pro DM-i 专用）
# 用法：~/openpilot/launch/run-songpro23.sh
set -euo pipefail

OP_ROOT="$HOME/openpilot/cpv8"
ENV_FILE="$HOME/openpilot/launch/env/songpro23.env"

[ -d "$OP_ROOT" ] || { echo "找不到 $OP_ROOT"; exit 1; }
[ -f "$ENV_FILE" ] || { echo "找不到 $ENV_FILE"; exit 1; }

cd "$OP_ROOT"
# shellcheck disable=SC1090
source "$OP_ROOT/.venv/bin/activate"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "== 启动参数 =="
echo "  FINGERPRINT=$FINGERPRINT"
echo "  ROAD_CAM=$ROAD_CAM  WIDE_CAM=${WIDE_CAM:-未启用}  USE_WEBCAM=$USE_WEBCAM"
echo "  NO_DM=$NO_DM  BYD_RADAR=${BYD_RADAR:-未启用}"
echo "  按 Ctrl+C 退出（界面点 × 不会真正退出）"
echo

exec system/manager/manager.py
