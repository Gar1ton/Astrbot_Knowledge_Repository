#!/bin/bash
# 一键停止、清理缓存、重新编译、同步并后台启动前后端的开发调试脚本

info()    { echo -e "\033[1;34m[INFO] $1\033[0m"; }
success() { echo -e "\033[1;32m[SUCCESS] $1\033[0m"; }
error()   { echo -e "\033[1;31m[ERROR] $1\033[0m"; }

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# ── 1. 停止旧进程 ────────────────────────────────────────────────────────────
info "1. 停止旧的开发服务器进程..."
# 后端
pkill -f "tests/run_webui.py" 2>/dev/null || true
# 前端：`next dev` / `next build` 启动后进程名会变为 `next-server`，
# 只 kill "next dev" 抓不到正在运行的旧 dev server——它会继续占用 3000 端口
# 与文件 watcher，导致本次启动假死。这里把 server / cli / npm 包装一并清掉。
pkill -f "next-server"        2>/dev/null || true
pkill -f "next/dist/bin/next" 2>/dev/null || true
pkill -f "npm run dev"        2>/dev/null || true
sleep 1

# ── 2. 检查依赖是否需要更新 ──────────────────────────────────────────────────
info "2. 检查前端依赖..."
cd "$ROOT_DIR/web/frontend"
if [ package.json -nt node_modules/.package-lock.json ] 2>/dev/null || [ ! -d node_modules ]; then
  info "   检测到 package.json 变更，执行 npm install..."
  npm install
fi

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
info "5. 后台拉起后端开发服务 (tests/run_webui.py)..."
PYTHONUNBUFFERED=1 nohup python3 tests/run_webui.py > "$ROOT_DIR/dev_backend.log" 2>&1 &
info "   后端日志: dev_backend.log"

# ── 6. 后台启动前端 dev server ───────────────────────────────────────────────
info "6. 后台拉起前端开发服务器 (npm run dev)..."
cd "$ROOT_DIR/web/frontend"
# NEXT_TEST_WASM=1：强制 WASM bindings → Next.js 跳过创建 .next/lock 的 flock。
# WSL2 的 drvfs/9p 挂载不支持文件锁，原生 lockfile 会 "Permission denied (os error 13)"，
# 即便 next.config.ts 触发热重启也不会因抢锁而崩溃。
# （npm run dev 自带 `rm -rf .next`，无需再手动清 lock 文件。）
NEXT_TELEMETRY_DISABLED=1 NEXT_TEST_WASM=1 nohup npm run dev > "$ROOT_DIR/dev_frontend.log" 2>&1 &
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

_wait_for "后端 (6520)" "http://127.0.0.1:6520/"
# 前端首次冷编译（webpack + WASM）较慢，放宽到 120s 避免误报超时
_wait_for "前端 dev (3000)" "http://localhost:3000/" 120

success "一键重建并重启完成！"
echo "=========================================="
echo "  后端控制台 (调试数据): http://127.0.0.1:6520"
echo "  前端服务 (开发热重载): http://localhost:3000"
echo "=========================================="
