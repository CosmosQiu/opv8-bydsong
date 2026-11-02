#!/usr/bin/env bash
# 从「应用列表」启动 openpilot（23 款宋 Pro DM-i 配置）。
#
# 为什么要有这一层：应用列表里的图标只能 Exec 一个程序，而 op 需要
# 「开一个终端窗口 → 里面跑 run-songpro23.sh → 退出后窗口别立刻消失（要能看报错）」。
# 把这段逻辑塞进 .desktop 的 Exec 里引号会套得很难维护，所以单独放这里。
#
# 实际配置全部来自 launch/env/songpro23.env，本脚本不覆盖任何参数。
set -uo pipefail

OP_RUN="$HOME/openpilot/launch/run-songpro23.sh"

if [ ! -x "$OP_RUN" ]; then
  echo "找不到可执行的 $OP_RUN" >&2
  exit 1
fi

if ! command -v gnome-terminal >/dev/null 2>&1; then
  # 没有图形终端就直接在当前终端跑
  exec "$OP_RUN"
fi

exec gnome-terminal --title="openpilot · 宋Pro23" -- \
  bash -c "\"$OP_RUN\"; rc=\$?; echo; echo \"[openpilot 已退出] exit=\$rc\"; echo \"按 Ctrl+D 或关窗口退出\"; exec bash"
