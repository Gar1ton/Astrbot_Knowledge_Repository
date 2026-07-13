#!/usr/bin/env python3
"""把前端构建产物（web/frontend/out/）同步到运行时静态目录（pages/）。

v0.10.0 起前端改用 Next.js App Router，构建产物在 web/frontend/out/。
本脚本检测 out/ 目录是否存在：存在则同步 out/，不存在时回退同步 web/frontend/（兼容旧版）。

构建流程：
    cd web/frontend && npm run build   # Next.js export → out/
    python tools/sync_frontend.py      # 同步 out/ → pages/

用法：
    python tools/sync_frontend.py          # 同步产物到 pages/
    python tools/sync_frontend.py --check  # 只检查是否一致（CI 用），不写入
    python tools/sync_frontend.py -f       # 同步（-f 与无参数行为相同，保留兼容性）
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_NEXT_OUT = _ROOT / "web" / "frontend" / "out"
_LEGACY_SRC = _ROOT / "web" / "frontend"
_DST = _ROOT / "pages"

_SKIP_NAMES = {"README.md", ".DS_Store"}
_SKIP_DIRS = {".next", "node_modules", "__pycache__"}


def _resolve_src() -> Path:
    """优先使用 Next.js export 产物目录；不存在时回退旧版源码目录。"""
    if _NEXT_OUT.exists():
        return _NEXT_OUT
    return _LEGACY_SRC


def _iter_files(root: Path) -> list[Path]:
    result = []
    for p in root.rglob("*"):
        if p.is_file() and p.name not in _SKIP_NAMES:
            # 跳过构建中间目录
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            result.append(p)
    return result


def _check() -> int:
    src = _resolve_src()
    mismatched = []
    src_relatives = {s.relative_to(src) for s in _iter_files(src)}
    for s in _iter_files(src):
        d = _DST / s.relative_to(src)
        if not d.exists() or not filecmp.cmp(s, d, shallow=False):
            mismatched.append(str(s.relative_to(_ROOT)))
    for d in _iter_files(_DST):
        if d.relative_to(_DST) not in src_relatives:
            mismatched.append(str(d.relative_to(_ROOT)))
    if mismatched:
        print(f"pages/ 与 {src.relative_to(_ROOT)} 不一致，需运行 sync_frontend：")
        for m in mismatched:
            print("  -", m)
        return 1
    print(f"pages/ 已与 {src.relative_to(_ROOT)} 一致。")
    return 0


def _sync() -> int:
    src = _resolve_src()
    print(f"同步源：{src.relative_to(_ROOT)} → pages/")
    # 先写入临时目录，再整体原子替换，避免删除旧目录期间 HTTP 服务出现短暂 404 窗口。
    tmp = _DST.parent / f"{_DST.name}.__tmp__"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    # 保留 pages/ 里不属于构建产物的文件（如 README.md）
    if _DST.exists():
        for name in _SKIP_NAMES:
            path = _DST / name
            if path.is_file():
                (tmp / name).write_bytes(path.read_bytes())
    count = 0
    for s in _iter_files(src):
        d = tmp / s.relative_to(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        count += 1
        print("  copied", s.relative_to(_ROOT), "→", d.relative_to(_ROOT))
    # 原子替换：重命名临时目录为正式目录
    old = _DST.parent / f"{_DST.name}.__old__"
    if _DST.exists():
        _DST.rename(old)
    tmp.rename(_DST)
    if old.exists():
        shutil.rmtree(old)
    print(f"完成：同步 {count} 个文件到 pages/。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="同步前端产物到 pages/")
    parser.add_argument("--check", action="store_true", help="只检查一致性，不写入")
    parser.add_argument("-f", "--force", action="store_true", help="强制同步（与默认行为相同）")
    args = parser.parse_args()
    if not _NEXT_OUT.exists() and not _LEGACY_SRC.exists():
        print(f"未找到前端源码目录：{_NEXT_OUT} 或 {_LEGACY_SRC}", file=sys.stderr)
        return 2
    return _check() if args.check else _sync()


if __name__ == "__main__":
    raise SystemExit(main())
