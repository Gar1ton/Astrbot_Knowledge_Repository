"""只读 zotero.sqlite 读取器（本地 pull 主路径）。

把 Zotero 内部 SQLite schema 翻译为本插件 domain 镜像对象（ZoteroItem/Collection/Attachment/Tag/
Relation）。**只读、不加锁**（immutable URI），即使 Zotero 正在运行也安全；绝不写 zotero.sqlite。

附件路径解析（linkMode）：
    0/1 imported → storage/<attachment_key>/<filename>（path 形如 storage:xxx.pdf）
    2 linked_file → 绝对路径或 attachments: 相对（取绝对路径）
    3 linked_url → 无本地文件（resolved_path 为空）

依赖方向：仅 stdlib。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.adapters.zotero import paths as zpaths
from core.domain.models import (
    DocumentOrigin,
    ZoteroAttachment,
    ZoteroCollection,
    ZoteroItem,
    ZoteroLibrary,
    ZoteroRelation,
    ZoteroTag,
)

# linkMode 枚举（Zotero 内部数值）。
LINK_IMPORTED_FILE = 0
LINK_IMPORTED_URL = 1
LINK_LINKED_FILE = 2
LINK_LINKED_URL = 3

# 非「常规文献条目」的类型（不作为 ZoteroItem 镜像主体）。
_NON_REGULAR_TYPES = {"attachment", "note", "annotation"}

_VENUE_FIELDS = ("publicationTitle", "proceedingsTitle", "bookTitle", "conferenceName")


@dataclass
class ZoteroSnapshot:
    """一次 zotero.sqlite 读取的结构化快照。"""

    library: ZoteroLibrary
    collections: list[ZoteroCollection] = field(default_factory=list)
    # 元素为 (collection_key, item_key)
    collection_items: list[tuple[str, str]] = field(default_factory=list)
    items: list[ZoteroItem] = field(default_factory=list)
    attachments: list[ZoteroAttachment] = field(default_factory=list)
    item_tags: dict[str, list[ZoteroTag]] = field(default_factory=dict)
    relations: list[ZoteroRelation] = field(default_factory=list)


def _parse_zotero_dt(val: str | None) -> datetime | None:
    """Zotero 时间戳形如 '2026-06-07 12:00:00'（UTC）。"""
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_year(date_value: str) -> str:
    m = re.search(r"\d{4}", date_value or "")
    return m.group(0) if m else ""


class ZoteroSqliteReader:
    """只读读取 zotero.sqlite，产出 domain 镜像快照。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._storage = zpaths.storage_dir(data_dir)

    def _connect(self) -> sqlite3.Connection:
        db_path = zpaths.zotero_sqlite_path(self._data_dir)
        if not db_path.exists():
            raise FileNotFoundError(f"zotero.sqlite not found: {db_path}")
        # immutable=1：只读且不加锁，Zotero 运行时也可安全读取。
        uri = f"file:{db_path}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True)

    def read_snapshot(self, library_type: str = "user") -> ZoteroSnapshot:
        """读取指定类型库（默认 personal user library）的完整镜像快照。"""
        conn = self._connect()
        try:
            library = self._read_library(conn, library_type)
            lib_id = library.library_id
            item_key_by_id = self._read_item_keys(conn, lib_id)
            snapshot = ZoteroSnapshot(library=library)
            snapshot.collections = self._read_collections(conn, lib_id)
            snapshot.collection_items = self._read_collection_items(conn, lib_id, item_key_by_id)
            snapshot.items = self._read_items(conn, lib_id)
            snapshot.attachments = self._read_attachments(conn, lib_id, item_key_by_id)
            snapshot.item_tags = self._read_item_tags(conn, lib_id, item_key_by_id)
            snapshot.relations = self._read_relations(conn, lib_id, item_key_by_id)
            return snapshot
        finally:
            conn.close()

    # ── 库 ────────────────────────────────────────────────────

    def _read_library(self, conn: sqlite3.Connection, library_type: str) -> ZoteroLibrary:
        row = conn.execute(
            "SELECT libraryID, type FROM libraries WHERE type = ? ORDER BY libraryID LIMIT 1",
            (library_type,),
        ).fetchone()
        if row is None:
            # 退化：取任意一个库。
            row = conn.execute("SELECT libraryID, type FROM libraries LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError("no libraries found in zotero.sqlite")
        return ZoteroLibrary(library_id=str(row[0]), library_type=str(row[1]), name=str(row[1]))

    def _read_item_keys(self, conn: sqlite3.Connection, lib_id: str) -> dict[int, str]:
        rows = conn.execute(
            "SELECT itemID, key FROM items WHERE libraryID = ?", (int(lib_id),)
        ).fetchall()
        return {int(r[0]): str(r[1]) for r in rows}

    # ── 集合 ──────────────────────────────────────────────────

    def _read_collections(self, conn: sqlite3.Connection, lib_id: str) -> list[ZoteroCollection]:
        # 解析 parentCollectionID → parent key。
        rows = conn.execute(
            "SELECT collectionID, collectionName, parentCollectionID, key "
            "FROM collections WHERE libraryID = ?",
            (int(lib_id),),
        ).fetchall()
        key_by_id = {int(r[0]): str(r[3]) for r in rows}
        result = []
        for cid, name, parent_id, key in rows:
            parent_key = key_by_id.get(int(parent_id), "") if parent_id is not None else ""
            result.append(
                ZoteroCollection(
                    collection_key=str(key),
                    library_id=lib_id,
                    name=str(name),
                    parent_collection_key=parent_key,
                    origin=DocumentOrigin.ZOTERO,
                )
            )
        return result

    def _read_collection_items(
        self, conn: sqlite3.Connection, lib_id: str, item_key_by_id: dict[int, str]
    ) -> list[tuple[str, str]]:
        rows = conn.execute(
            "SELECT c.key, ci.itemID FROM collectionItems ci "
            "JOIN collections c ON c.collectionID = ci.collectionID "
            "WHERE c.libraryID = ?",
            (int(lib_id),),
        ).fetchall()
        pairs = []
        for coll_key, item_id in rows:
            item_key = item_key_by_id.get(int(item_id))
            if item_key:
                pairs.append((str(coll_key), item_key))
        return pairs

    # ── 条目 ──────────────────────────────────────────────────

    def _read_items(self, conn: sqlite3.Connection, lib_id: str) -> list[ZoteroItem]:
        # 常规文献条目（排除 attachment/note/annotation 与已删除）。
        rows = conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName, i.version, i.dateAdded, i.dateModified
              FROM items i
              JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
             WHERE i.libraryID = ?
               AND it.typeName NOT IN ('attachment', 'note', 'annotation')
               AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            """,
            (int(lib_id),),
        ).fetchall()
        if not rows:
            return []
        item_ids = [int(r[0]) for r in rows]
        fields_by_item = self._read_item_fields(conn, item_ids)
        creators_by_item = self._read_item_creators(conn, item_ids)

        result = []
        for item_id, key, type_name, version, date_added, date_modified in rows:
            f = fields_by_item.get(int(item_id), {})
            venue = next((f[k] for k in _VENUE_FIELDS if f.get(k)), "")
            result.append(
                ZoteroItem(
                    item_key=str(key),
                    library_id=lib_id,
                    item_type=str(type_name),
                    version=int(version or 0),
                    deleted=False,
                    title=f.get("title", ""),
                    creators=creators_by_item.get(int(item_id), []),
                    year=_extract_year(f.get("date", "")),
                    venue=venue,
                    doi=f.get("DOI", ""),
                    url=f.get("url", ""),
                    abstract=f.get("abstractNote", ""),
                    origin=DocumentOrigin.ZOTERO,
                    date_added=_parse_zotero_dt(date_added),
                    date_modified=_parse_zotero_dt(date_modified),
                    raw_zotero_json={"itemType": type_name, "fields": f},
                )
            )
        return result

    def _read_item_fields(
        self, conn: sqlite3.Connection, item_ids: list[int]
    ) -> dict[int, dict[str, str]]:
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(
            f"""
            SELECT id.itemID, f.fieldName, idv.value
              FROM itemData id
              JOIN fields f ON f.fieldID = id.fieldID
              JOIN itemDataValues idv ON idv.valueID = id.valueID
             WHERE id.itemID IN ({placeholders})
            """,
            item_ids,
        ).fetchall()
        out: dict[int, dict[str, str]] = {}
        for item_id, field_name, value in rows:
            out.setdefault(int(item_id), {})[str(field_name)] = str(value)
        return out

    def _read_item_creators(
        self, conn: sqlite3.Connection, item_ids: list[int]
    ) -> dict[int, list[str]]:
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(
            f"""
            SELECT ic.itemID, c.lastName, c.firstName, c.fieldMode, ic.orderIndex
              FROM itemCreators ic
              JOIN creators c ON c.creatorID = ic.creatorID
             WHERE ic.itemID IN ({placeholders})
             ORDER BY ic.itemID, ic.orderIndex
            """,
            item_ids,
        ).fetchall()
        out: dict[int, list[str]] = {}
        for item_id, last, first, field_mode, _order in rows:
            if int(field_mode or 0) == 1 or not first:
                name = str(last or "")
            else:
                name = f"{last}, {first}"
            if name:
                out.setdefault(int(item_id), []).append(name)
        return out

    # ── 附件 ──────────────────────────────────────────────────

    def _read_attachments(
        self, conn: sqlite3.Connection, lib_id: str, item_key_by_id: dict[int, str]
    ) -> list[ZoteroAttachment]:
        rows = conn.execute(
            """
            SELECT ia.itemID, ia.parentItemID, ia.linkMode, ia.contentType, ia.path,
                   ia.storageHash, i.key
              FROM itemAttachments ia
              JOIN items i ON i.itemID = ia.itemID
             WHERE i.libraryID = ?
               AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            """,
            (int(lib_id),),
        ).fetchall()
        result = []
        for item_id, parent_id, link_mode, content_type, path, storage_hash, key in rows:
            parent_key = item_key_by_id.get(int(parent_id), "") if parent_id is not None else ""
            filename, resolved = self._resolve_attachment_path(
                int(link_mode or 0), str(path or ""), str(key)
            )
            result.append(
                ZoteroAttachment(
                    attachment_key=str(key),
                    parent_item_key=parent_key,
                    library_id=lib_id,
                    content_type=str(content_type or ""),
                    filename=filename,
                    path=str(path or ""),
                    resolved_path=resolved,
                    link_mode=_link_mode_name(int(link_mode or 0)),
                    md5=str(storage_hash or ""),
                    raw_zotero_json={"linkMode": link_mode, "path": path},
                )
            )
        return result

    def _resolve_attachment_path(
        self, link_mode: int, path: str, attachment_key: str
    ) -> tuple[str, str]:
        """返回 (filename, resolved_absolute_path)；无本地文件时 resolved 为空。"""
        if link_mode in (LINK_IMPORTED_FILE, LINK_IMPORTED_URL):
            # path 形如 'storage:paper.pdf' → storage/<attachment_key>/paper.pdf
            filename = path.split(":", 1)[1] if path.startswith("storage:") else path
            resolved = self._storage / attachment_key / filename
            return filename, str(resolved) if resolved.exists() else ""
        if link_mode == LINK_LINKED_FILE:
            # path 可能是绝对路径或 'attachments:rel'；取绝对路径。
            raw = path.split(":", 1)[1] if path.startswith("attachments:") else path
            p = Path(raw).expanduser()
            return p.name, str(p) if p.exists() else ""
        # linked_url：无本地文件。
        return "", ""

    # ── 标签 ──────────────────────────────────────────────────

    def _read_item_tags(
        self, conn: sqlite3.Connection, lib_id: str, item_key_by_id: dict[int, str]
    ) -> dict[str, list[ZoteroTag]]:
        rows = conn.execute(
            """
            SELECT it.itemID, t.name, it.type
              FROM itemTags it
              JOIN tags t ON t.tagID = it.tagID
              JOIN items i ON i.itemID = it.itemID
             WHERE i.libraryID = ?
            """,
            (int(lib_id),),
        ).fetchall()
        out: dict[str, list[ZoteroTag]] = {}
        for item_id, name, tag_type in rows:
            item_key = item_key_by_id.get(int(item_id))
            if not item_key:
                continue
            out.setdefault(item_key, []).append(
                ZoteroTag(
                    item_key=item_key,
                    tag=str(name),
                    type=int(tag_type or 0),
                    origin=DocumentOrigin.ZOTERO,
                )
            )
        return out

    # ── 关系 ──────────────────────────────────────────────────

    def _read_relations(
        self, conn: sqlite3.Connection, lib_id: str, item_key_by_id: dict[int, str]
    ) -> list[ZoteroRelation]:
        try:
            rows = conn.execute(
                """
                SELECT ir.itemID, rp.predicate, ir.object
                  FROM itemRelations ir
                  JOIN relationPredicates rp ON rp.predicateID = ir.predicateID
                  JOIN items i ON i.itemID = ir.itemID
                 WHERE i.libraryID = ?
                """,
                (int(lib_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        result = []
        for item_id, predicate, obj in rows:
            src_key = item_key_by_id.get(int(item_id))
            if not src_key:
                continue
            # object 通常是 zotero URI，末段即 target key。
            target_key = str(obj).rstrip("/").rsplit("/", 1)[-1]
            result.append(
                ZoteroRelation(
                    source_item_key=src_key,
                    relation_type=str(predicate),
                    target_item_key=target_key,
                )
            )
        return result


def _link_mode_name(link_mode: int) -> str:
    return {
        LINK_IMPORTED_FILE: "imported_file",
        LINK_IMPORTED_URL: "imported_url",
        LINK_LINKED_FILE: "linked_file",
        LINK_LINKED_URL: "linked_url",
    }.get(link_mode, "unknown")


__all__ = [
    "ZoteroSqliteReader",
    "ZoteroSnapshot",
    "LINK_IMPORTED_FILE",
    "LINK_IMPORTED_URL",
    "LINK_LINKED_FILE",
    "LINK_LINKED_URL",
]
