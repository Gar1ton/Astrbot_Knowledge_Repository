"""Zotero 数据目录与 storage 路径解析（OS 默认探测 + 覆盖 + linked_root 探针）。

依赖方向：仅 stdlib。不读取业务层。
"""
from __future__ import annotations

import sys
from pathlib import Path

ZOTERO_SQLITE = "zotero.sqlite"
STORAGE_DIRNAME = "storage"


def default_zotero_data_dir() -> Path | None:
    """返回 OS 上 Zotero 的默认数据目录（存在才返回；否则 None）。

    Zotero 默认数据目录：Win=%USERPROFILE%\\Zotero，macOS/Linux=~/Zotero。
    用户若自定义过数据目录，应在设置中显式覆盖。
    """
    home = Path.home()
    candidates = [home / "Zotero"]
    if sys.platform == "win32":
        candidates.insert(0, home / "Zotero")
    for c in candidates:
        if (c / ZOTERO_SQLITE).exists():
            return c
    return None


def resolve_data_dir(override: str) -> Path | None:
    """解析有效 Zotero 数据目录：优先用户覆盖，否则自动探测。返回含 zotero.sqlite 的目录或 None。"""
    if override:
        p = Path(override).expanduser()
        if (p / ZOTERO_SQLITE).exists():
            return p
        return None
    return default_zotero_data_dir()


def zotero_sqlite_path(data_dir: Path) -> Path:
    return data_dir / ZOTERO_SQLITE


def storage_dir(data_dir: Path) -> Path:
    return data_dir / STORAGE_DIRNAME


def probe_linked_root(root: str) -> dict[str, object]:
    """校验 linked 模式的 Zotero storage 根目录是否 valid。

    valid 判据：路径存在且为目录。返回 {valid, reason, resolved}，供前端在设置后即时反馈。
    """
    if not root:
        return {"valid": False, "reason": "linked_root 未配置", "resolved": ""}
    p = Path(root).expanduser()
    if not p.exists():
        return {"valid": False, "reason": f"目录不存在: {p}", "resolved": str(p)}
    if not p.is_dir():
        return {"valid": False, "reason": f"不是目录: {p}", "resolved": str(p)}
    return {"valid": True, "reason": "", "resolved": str(p)}


__all__ = [
    "ZOTERO_SQLITE",
    "STORAGE_DIRNAME",
    "default_zotero_data_dir",
    "resolve_data_dir",
    "zotero_sqlite_path",
    "storage_dir",
    "probe_linked_root",
]
