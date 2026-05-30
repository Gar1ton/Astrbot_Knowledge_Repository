#!/usr/bin/env python3
"""把前端源码（web/frontend/）同步到运行时静态目录（pages/）。

零构建项目：前端是单页 HTML，无需打包，本脚本仅做复制。若将来引入打包工具，
在此调用构建命令后再复制产物即可。生产由 web/server.py 指向 pages/ 托管。

用法：
    python tools/sync_frontend.py          # 复制 web/frontend/* → pages/
    python tools/sync_frontend.py --check  # 只检查是否一致（CI 用），不写入
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "web" / "frontend"
_DST = _ROOT / "pages"


def _iter_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.name != "README.md"]


def _check() -> int:
    mismatched = []
    for src in _iter_files(_SRC):
        dst = _DST / src.relative_to(_SRC)
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            mismatched.append(str(src.relative_to(_ROOT)))
    if mismatched:
        print("pages/ 与 web/frontend/ 不一致，需运行 sync_frontend：")
        for m in mismatched:
            print("  -", m)
        return 1
    print("pages/ 已与 web/frontend/ 一致。")
    return 0


def _sync() -> int:
    count = 0
    for src in _iter_files(_SRC):
        dst = _DST / src.relative_to(_SRC)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
        print("  copied", src.relative_to(_ROOT), "→", dst.relative_to(_ROOT))
    print(f"完成：同步 {count} 个文件到 pages/。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="同步前端源码到 pages/")
    parser.add_argument("--check", action="store_true", help="只检查一致性，不写入")
    args = parser.parse_args()
    if not _SRC.exists():
        print(f"未找到前端源码目录：{_SRC}", file=sys.stderr)
        return 2
    return _check() if args.check else _sync()


if __name__ == "__main__":
    raise SystemExit(main())
