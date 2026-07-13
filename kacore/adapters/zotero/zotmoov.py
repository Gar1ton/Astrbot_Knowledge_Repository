"""ZotMoov 附件目录解析（storage_mode=zotmoov）。

ZotMoov 插件把附件移出 Zotero storage 后转为 linked_file，DB path 形如
'attachments:rel/sub/p.pdf'（配了基础目录）或宿主机绝对路径（跨机器/容器时失效）。
本模块把这类 path 解析为 zotmoov_root 下的真实文件；绝对路径失效时按
「每个实例至多构建一次」的递归文件名索引兜底。

依赖方向：仅 stdlib。不读取业务层。
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

ATTACHMENTS_PREFIX = "attachments:"
# ZoteroAttachment.link_mode 的字符串值（见 sqlite_reader._link_mode_name / web_api linkMode）。
LINK_MODE_LINKED_FILE = "linked_file"


def attachments_relative(path: str) -> str:
    """剥离 'attachments:' 前缀并统一分隔符为 '/'；非该前缀返回 ''。"""
    if not path.startswith(ATTACHMENTS_PREFIX):
        return ""
    rel = path[len(ATTACHMENTS_PREFIX) :]
    return rel.replace("\\", "/").lstrip("/")


class ZotmoovResolver:
    """把 linked_file 附件 path 解析为 root 下的真实文件。

    解析顺序：① 'attachments:rel' → root/rel；② 绝对路径 expanduser 后存在即用；
    ③ 文件名索引（大小写不敏感）：唯一命中→用，多命中按 DB 路径父目录名尾段消歧，
    仍歧义→上报 reason；④ 无命中→静默失败（与既有缺件行为一致）。

    索引经 os.walk 全量扫描惰性构建；实例生命周期应为一次 pull，索引不跨同步复用。
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._index: dict[str, list[Path]] | None = None

    def resolve(self, path: str, filename: str) -> tuple[Path | None, str]:
        """返回 (resolved, reason)。resolved=None 且 reason 非空 = 应上报的失败（重名歧义）。"""
        rel = attachments_relative(path)
        if rel:
            cand = self._root / rel
            if cand.exists():
                return cand, ""
        elif path:
            p = Path(path).expanduser()
            if p.exists():
                return p, ""
        name = (filename or "").strip().lower()
        if not name:
            return None, ""
        hits = self._ensure_index().get(name, [])
        if len(hits) == 1:
            return hits[0], ""
        if len(hits) > 1:
            parent = _db_parent_name(path)
            narrowed = [h for h in hits if parent and h.parent.name == parent]
            if len(narrowed) == 1:
                return narrowed[0], ""
            return None, (
                f"zotmoov_root 下存在 {len(hits)} 个同名文件 '{filename}'，无法唯一定位，已跳过"
            )
        return None, ""

    def _ensure_index(self) -> dict[str, list[Path]]:
        if self._index is None:
            index: dict[str, list[Path]] = {}
            if self._root.is_dir():
                for dirpath, _dirnames, filenames in os.walk(self._root):
                    for fn in filenames:
                        index.setdefault(fn.lower(), []).append(Path(dirpath) / fn)
            self._index = index
        return self._index


def _db_parent_name(path: str) -> str:
    """取 DB 存储路径的父目录名尾段（跨 OS 分隔符），用于重名消歧；取不到返回 ''。"""
    rel = attachments_relative(path)
    if rel:
        return PurePosixPath(rel).parent.name
    if not path:
        return ""
    pure = PureWindowsPath(path) if "\\" in path or ":" in path[:3] else PurePosixPath(path)
    return pure.parent.name


__all__ = [
    "ATTACHMENTS_PREFIX",
    "LINK_MODE_LINKED_FILE",
    "attachments_relative",
    "ZotmoovResolver",
]
