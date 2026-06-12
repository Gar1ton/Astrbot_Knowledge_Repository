#!/bin/bash
# 一键停止、清理缓存、重新编译、同步并后台启动前后端的开发调试脚本

info()    { echo -e "\033[1;34m[INFO] $1\033[0m"; }
success() { echo -e "\033[1;32m[SUCCESS] $1\033[0m"; }
error()   { echo -e "\033[1;31m[ERROR] $1\033[0m"; }

set -e

MIN_NODE_VERSION="20.9.0"
BACKEND_HOST="0.0.0.0"
BACKEND_PORT="6520"
FRONTEND_HOST="0.0.0.0"
FRONTEND_PORT="3000"
LOCAL_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
LOCAL_FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
PYTHON_REQUIREMENTS="requirements.txt"
PYTHON_DEPS_STAMP="/tmp/kr-python-deps.stamp"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# ── 0. 运行环境自检 ──────────────────────────────────────────────────────────
_version_at_least() {
  local current="$1" required="$2"
  local c_major c_minor c_patch r_major r_minor r_patch
  IFS=. read -r c_major c_minor c_patch <<< "$current"
  IFS=. read -r r_major r_minor r_patch <<< "$required"

  c_minor="${c_minor:-0}"
  c_patch="${c_patch:-0}"
  r_minor="${r_minor:-0}"
  r_patch="${r_patch:-0}"

  [[ "$c_major" =~ ^[0-9]+$ && "$c_minor" =~ ^[0-9]+$ && "$c_patch" =~ ^[0-9]+$ ]] || return 1
  [[ "$r_major" =~ ^[0-9]+$ && "$r_minor" =~ ^[0-9]+$ && "$r_patch" =~ ^[0-9]+$ ]] || return 1

  if (( c_major > r_major )); then return 0; fi
  if (( c_major < r_major )); then return 1; fi
  if (( c_minor > r_minor )); then return 0; fi
  if (( c_minor < r_minor )); then return 1; fi
  (( c_patch >= r_patch ))
}

_kill_matching_processes() {
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "tests/run_webui.py" 2>/dev/null || true
    pkill -f "next-server" 2>/dev/null || true
    pkill -f "next/dist/bin/next" 2>/dev/null || true
    pkill -f "npm run dev" 2>/dev/null || true
    return
  fi

  python3 - <<'PY'
from pathlib import Path
import os
import signal

needles = (
    "tests/run_webui.py",
    "next-server",
    "next/dist/bin/next",
    "npm run dev",
)
current_pid = os.getpid()

for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
    try:
        command = cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        continue

    if not any(needle in command for needle in needles):
        continue

    pid = int(cmdline.parent.name)
    if pid == current_pid:
        continue

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
PY
}

info "0. 检查 Docker 内 Node.js 版本..."
if ! command -v node >/dev/null 2>&1; then
  error "未找到 node。请先重建 devcontainer 镜像。"
  exit 1
fi
NODE_VERSION="$(node -p 'process.versions.node' 2>/dev/null || true)"
if ! _version_at_least "$NODE_VERSION" "$MIN_NODE_VERSION"; then
  error "当前 Node.js ${NODE_VERSION:-unknown} 不满足 Next.js 16.2.6 要求 >= ${MIN_NODE_VERSION}。"
  error "请重建 devcontainer，使 Dockerfile 使用 NodeSource setup_20.x 后再运行本脚本。"
  exit 1
fi
info "   Node.js ${NODE_VERSION} OK"

# ── 0b. 后端 Python 依赖自检 ────────────────────────────────────────────────
info "0b. 检查后端 Python 依赖..."
if ! command -v python3 >/dev/null 2>&1; then
  error "未找到 python3。请检查 devcontainer 镜像。"
  exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
  error "未找到 pip。请检查 devcontainer 镜像。"
  exit 1
fi

mkdir -p "$(dirname "$PYTHON_DEPS_STAMP")"
if ! python3 - <<'PY' >/dev/null 2>&1
import aiohttp  # noqa: F401
PY
then
  info "   缺少 aiohttp，执行 pip install -r ${PYTHON_REQUIREMENTS}..."
  python3 -m pip install -r "$PYTHON_REQUIREMENTS"
elif [ "$PYTHON_REQUIREMENTS" -nt "$PYTHON_DEPS_STAMP" ] 2>/dev/null; then
  info "   ${PYTHON_REQUIREMENTS} 已更新，刷新后端依赖..."
  python3 -m pip install -r "$PYTHON_REQUIREMENTS"
else
  info "   Python 后端依赖 OK"
fi
touch "$PYTHON_DEPS_STAMP"

# ── 1. 停止旧进程 ────────────────────────────────────────────────────────────
info "1. 停止旧的开发服务器进程..."
# `next dev` 启动后进程名会变为 `next-server`；同时兼容 slim 镜像缺少 pkill 的情况。
_kill_matching_processes
sleep 1

# ── 2. 检查依赖是否需要更新 ──────────────────────────────────────────────────
info "2. 检查前端依赖..."
cd "$ROOT_DIR/web/frontend"
NODE_STAMP="node_modules/.kr-node-version"
NEED_INSTALL=0
if [ ! -d node_modules ]; then
  info "   node_modules 不存在，需要安装依赖。"
  NEED_INSTALL=1
elif [ package.json -nt node_modules/.package-lock.json ] 2>/dev/null; then
  info "   package.json 新于 node_modules，需要刷新依赖。"
  NEED_INSTALL=1
elif [ package-lock.json -nt node_modules/.package-lock.json ] 2>/dev/null; then
  info "   package-lock.json 新于 node_modules，需要刷新依赖。"
  NEED_INSTALL=1
elif [ ! -f "$NODE_STAMP" ] || [ "$(cat "$NODE_STAMP" 2>/dev/null)" != "$NODE_VERSION" ]; then
  info "   Node.js 版本变化，需要刷新依赖。"
  NEED_INSTALL=1
fi

if [ "$NEED_INSTALL" -eq 1 ]; then
  info "   执行 npm install..."
  npm install
fi
printf "%s\n" "$NODE_VERSION" > "$NODE_STAMP"

# ── 3. 生产构建（生成 pages/ 静态产物）──────────────────────────────────────
info "3. 编译前端（生产构建 → pages/）..."
# 清理 stale TS 增量缓存：tsconfig.tsbuildinfo 会记录已删除的源文件（如旧的
# app/api/[...proxy]/route.ts），构建时 TS 读取该缓存会 ENOENT 而整体失败，
# 由于 set -e 直接中断脚本，dev server 永远起不来、3000 端口无内容。
# （npm 脚本已内置同样清理，这里再做一次以防 package.json 被回退。）
rm -f tsconfig.tsbuildinfo
# NEXT_TEST_WASM=1：强制 WASM bindings，避免下载 native SWC 后导致 lockfile Permission denied 崩溃
NEXT_TEST_WASM=1 npm run build

# ── 4. 同步静态文件 ──────────────────────────────────────────────────────────
info "4. 同步前端静态文件..."
cd "$ROOT_DIR"
python3 tools/sync_frontend.py

# ── 5. 后台启动后端 ──────────────────────────────────────────────────────────
info "5. 后台拉起后端开发服务 (tests/run_webui.py on ${BACKEND_HOST}:${BACKEND_PORT})..."
PYTHONUNBUFFERED=1 nohup python3 tests/run_webui.py --host "$BACKEND_HOST" --port "$BACKEND_PORT" > "$ROOT_DIR/dev_backend.log" 2>&1 &
info "   后端日志: dev_backend.log"

# ── 6. 后台启动前端 dev server ───────────────────────────────────────────────
info "6. 后台拉起前端开发服务器 (npm run dev on ${FRONTEND_HOST}:${FRONTEND_PORT})..."
cd "$ROOT_DIR/web/frontend"
# dev server 不强制 NEXT_TEST_WASM：Node 20/Linux 容器下该变量会导致 .next/dev manifest 缺失并返回 500。
# （npm run dev 自带 `rm -rf .next tsconfig.tsbuildinfo`，无需再手动清缓存。）
NEXT_TELEMETRY_DISABLED=1 nohup npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT" > "$ROOT_DIR/dev_frontend.log" 2>&1 &
info "   前端日志: dev_frontend.log"

# ── 7. 等待服务就绪 ──────────────────────────────────────────────────────────
info "7. 等待服务就绪..."
_wait_for() {
  local name="$1" url="$2" timeout="${3:-60}" elapsed=0
  printf "   等待 %s 就绪 " "$name"
  while ! curl -sf "$url" > /dev/null 2>&1; do
    printf "."
    sleep 1
    elapsed=$((elapsed + 1))
    if [ "$elapsed" -ge "$timeout" ]; then
      echo
      error "$name 启动超时（${timeout}s），请检查对应日志"
      exit 1
    fi
  done
  echo " 就绪"
}

_wait_for "后端 (${BACKEND_PORT})" "${LOCAL_BACKEND_URL}/"
# 前端首次冷编译（webpack + WASM）较慢，放宽到 120s 避免误报超时
_wait_for "前端 dev (${FRONTEND_PORT})" "${LOCAL_FRONTEND_URL}/" 120

success "一键重建并重启完成！"
echo "=========================================="
echo "  后端控制台 (调试数据): ${LOCAL_BACKEND_URL}"
echo "  前端服务 (开发热重载): ${LOCAL_FRONTEND_URL}"
echo "=========================================="
