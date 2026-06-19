#!/usr/bin/env bash
# tools/watch_frontend.sh
# 监听前端源码变动 → 自动 build → sync → 后端 26618 立即可用
#
# 用法（在仓库根目录执行）：
#   bash tools/watch_frontend.sh
#   bash tools/watch_frontend.sh --port 8000   # 指定后端端口（仅用于提示）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/web/frontend"
WATCH_DIRS=(
  "$FRONTEND_DIR/app"
  "$FRONTEND_DIR/components"
  "$FRONTEND_DIR/lib"
  "$FRONTEND_DIR/styles"
  "$FRONTEND_DIR/public"
)
DEBOUNCE=2   # 秒，收集连续保存事件再触发构建

# ── 颜色 ──────────────────────────────────────────────────────
C_RESET='\033[0m'
C_CYAN='\033[0;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_BOLD='\033[1m'

log()  { echo -e "${C_CYAN}[watch]${C_RESET} $*"; }
ok()   { echo -e "${C_GREEN}[watch] ✓${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[watch] ⚠${C_RESET} $*"; }
err()  { echo -e "${C_RED}[watch] ✗${C_RESET} $*"; }

# ── 过滤不需要监听的路径 ──────────────────────────────────────
EXCLUDE_REGEX='(node_modules|\.next|out|\.git)'

# ── 单次构建 + 同步 ───────────────────────────────────────────
build_and_sync() {
  echo ""
  log "${C_BOLD}源文件变更，开始重新构建...${C_RESET}"

  cd "$FRONTEND_DIR"
  if npm run build --silent 2>&1 | grep -E "error TS|Error:|✓|⚠|Failed"; then
    :
  fi

  # 检查 build 是否真的成功（out/ 目录存在）
  if [[ ! -d "$FRONTEND_DIR/out" ]]; then
    err "构建失败，out/ 目录不存在，跳过同步"
    return 1
  fi

  cd "$REPO_ROOT"
  python tools/sync_frontend.py 2>&1 | tail -1

  ok "同步完成 → 刷新 http://localhost:26618 即可看到最新改动"
  echo ""
}

# ── 主循环 ────────────────────────────────────────────────────
main() {
  echo -e "${C_BOLD}${C_CYAN}"
  echo "  ╔══════════════════════════════════════╗"
  echo "  ║   前端热同步监听器  (build → sync)   ║"
  echo "  ╚══════════════════════════════════════╝"
  echo -e "${C_RESET}"
  log "监听目录："
  for d in "${WATCH_DIRS[@]}"; do
    echo "    $d"
  done
  log "防抖延迟：${DEBOUNCE}s  |  排除：node_modules / .next / out"
  echo ""

  # 检查 inotifywait
  if ! command -v inotifywait &>/dev/null; then
    err "inotifywait 未找到，请执行：sudo apt-get install inotify-tools"
    exit 1
  fi

  # 先做一次初始构建
  log "执行初始构建..."
  build_and_sync || warn "初始构建失败，继续监听..."

  PENDING=0
  LAST_CHANGE=0

  while true; do
    # inotifywait 阻塞等待任意一个事件（超时 1s 用于检查 debounce）
    if inotifywait -r -q -t 1 \
        --event modify,create,delete,move \
        --exclude "$EXCLUDE_REGEX" \
        "${WATCH_DIRS[@]}" &>/dev/null; then
      PENDING=1
      LAST_CHANGE=$(date +%s)
    fi

    # 有待处理事件，且距上次变更超过 debounce 时间
    if [[ $PENDING -eq 1 ]]; then
      NOW=$(date +%s)
      if (( NOW - LAST_CHANGE >= DEBOUNCE )); then
        PENDING=0
        build_and_sync || warn "构建失败，等待下次变更..."
      fi
    fi
  done
}

main "$@"
