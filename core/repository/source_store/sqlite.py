"""源文档库的 SQLite 持久化实现。

使用 aiosqlite 进行异步数据库交互，完成原件、集合与分块的 CRUD。
遵循仓储契约，执行参数化查询防止 SQL 注入，通过 JSON 序列化存储标签数组。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.domain.models import (
    Collection,
    DocumentChunk,
    SourceDocument,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
)
from core.repository.source_store.base import SourceDocumentStore

if TYPE_CHECKING:
    import aiosqlite


def _parse_dt(val: str | None) -> datetime | None:
    """解析 ISO8601 时间戳为 UTC datetime。"""
    if not val:
        return None
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return None


def _format_dt(dt: datetime | None) -> str | None:
    """序列化 datetime 为 ISO8601 字符串。"""
    if dt is None:
        return None
    return dt.isoformat()


class SQLiteSourceDocumentStore(SourceDocumentStore):
    """基于 SQLite/aiosqlite 的生产 SourceDocumentStore 实现。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── 集合 ────────────────────────────────────────────────────

    async def upsert_collection(self, collection: Collection) -> None:
        created_at_str = _format_dt(collection.created_at or datetime.now(timezone.utc))
        await self._db.execute(
            """
            INSERT INTO collections (name, description, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description
            """,
            (collection.name, collection.description, created_at_str),
        )
        await self._db.commit()

    async def list_collections(self) -> list[Collection]:
        async with self._db.execute(
            "SELECT name, description, created_at FROM collections ORDER BY name ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                Collection(
                    name=row[0],
                    description=row[1],
                    created_at=_parse_dt(row[2]),
                )
                for row in rows
            ]

    async def delete_collection(self, name: str) -> bool:
        async with self._db.execute(
            "DELETE FROM collections WHERE name = ?", (name,)
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    # ── 文档 ────────────────────────────────────────────────────

    async def add_document(self, document: SourceDocument) -> None:
        created_at_str = _format_dt(document.created_at or datetime.now(timezone.utc))
        updated_at_str = _format_dt(document.updated_at or datetime.now(timezone.utc))
        tags_str = json.dumps(document.tags)

        try:
            await self._db.execute(
                """
                INSERT INTO documents (
                    doc_id, title, file_path, content_type, size_bytes,
                    content_hash, collection, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.doc_id,
                    document.title,
                    document.file_path,
                    document.content_type,
                    document.size_bytes,
                    document.content_hash,
                    document.collection,
                    tags_str,
                    created_at_str,
                    updated_at_str,
                ),
            )
            await self._db.commit()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: documents.doc_id" in str(e):
                raise ValueError(f"duplicate doc_id: {document.doc_id}") from e
            raise

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        async with self._db.execute(
            """
            SELECT title, file_path, content_type, size_bytes, content_hash,
                   collection, tags, created_at, updated_at
              FROM documents WHERE doc_id = ?
            """,
            (doc_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None

            try:
                tags = json.loads(row[6])
                if not isinstance(tags, list):
                    tags = []
            except (json.JSONDecodeError, TypeError):
                tags = []

            return SourceDocument(
                doc_id=doc_id,
                title=row[0],
                file_path=row[1],
                content_type=row[2],
                size_bytes=row[3],
                content_hash=row[4],
                collection=row[5],
                tags=tags,
                created_at=_parse_dt(row[7]),
                updated_at=_parse_dt(row[8]),
            )

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        query = """
            SELECT doc_id, title, file_path, content_type, size_bytes,
                   content_hash, collection, tags, created_at, updated_at
              FROM documents
        """
        params = []
        conditions = []

        if collection is not None:
            conditions.append("collection = ?")
            params.append(collection)

        if tag is not None:
            # 使用 SQL JSON1 扩展函数 json_each 匹配 tags 数组内的元素
            conditions.append("exists (select 1 from json_each(tags) where value = ?)")
            params.append(tag)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        # 默认按 created_at 升序，created_at 为 NULL 的排前面
        query += " ORDER BY created_at ASC, doc_id ASC"

        async with self._db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                try:
                    tags = json.loads(row[7])
                    if not isinstance(tags, list):
                        tags = []
                except (json.JSONDecodeError, TypeError):
                    tags = []

                results.append(
                    SourceDocument(
                        doc_id=row[0],
                        title=row[1],
                        file_path=row[2],
                        content_type=row[3],
                        size_bytes=row[4],
                        content_hash=row[5],
                        collection=row[6],
                        tags=tags,
                        created_at=_parse_dt(row[8]),
                        updated_at=_parse_dt(row[9]),
                    )
                )
            return results

    async def update_document(self, document: SourceDocument) -> bool:
        updated_at_str = _format_dt(document.updated_at or datetime.now(timezone.utc))
        tags_str = json.dumps(document.tags)

        async with self._db.execute(
            """
            UPDATE documents SET
                title = ?, file_path = ?, content_type = ?, size_bytes = ?,
                content_hash = ?, collection = ?, tags = ?, updated_at = ?
            WHERE doc_id = ?
            """,
            (
                document.title,
                document.file_path,
                document.content_type,
                document.size_bytes,
                document.content_hash,
                document.collection,
                tags_str,
                updated_at_str,
                document.doc_id,
            ),
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def delete_document(self, doc_id: str) -> bool:
        # SQLite 配了外键级联删除 (ON DELETE CASCADE) 关联的 chunks 会由外键级联自动删除
        # 但遵循仓储接口约定，为了确定 doc_id 存在性，我们可以在事务里手动操作
        async with self._db.execute(
            "DELETE FROM documents WHERE doc_id = ?", (doc_id,)
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    # ── 分块 ────────────────────────────────────────────────────

    async def replace_chunks(self, doc_id: str, chunks: list[DocumentChunk]) -> None:
        # 整体替换语义：先删该 doc 旧 chunks -> 再插入新 chunks。包裹在同一个事务内。
        await self._db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

        for chunk in chunks:
            await self._db.execute(
                """
                INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id,
                    doc_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.content_hash,
                ),
            )
        await self._db.commit()

    async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
        async with self._db.execute(
            """
            SELECT chunk_id, ordinal, text, content_hash
              FROM chunks WHERE doc_id = ?
             ORDER BY ordinal ASC
            """,
            (doc_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                DocumentChunk(
                    chunk_id=row[0],
                    doc_id=doc_id,
                    ordinal=row[1],
                    text=row[2],
                    content_hash=row[3],
                )
                for row in rows
            ]

    # ── 同步状态 ──────────────────────────────────────────────────

    async def get_sync_record(self, doc_id: str, target: SyncTargetKind) -> SyncRecord | None:
        async with self._db.execute(
            """
            SELECT remote_ref, content_hash, status, synced_at, message
              FROM sync_records WHERE doc_id = ? AND target = ?
            """,
            (doc_id, target.value),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return SyncRecord(
                doc_id=doc_id,
                target=target,
                remote_ref=row[0],
                content_hash=row[1],
                status=SyncStatus(row[2]),
                synced_at=_parse_dt(row[3]),
                message=row[4],
            )

    async def upsert_sync_record(self, record: SyncRecord) -> None:
        synced_at_str = _format_dt(record.synced_at)
        await self._db.execute(
            """
            INSERT INTO sync_records (
                doc_id, target, remote_ref, content_hash, status, synced_at, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id, target) DO UPDATE SET
                remote_ref = excluded.remote_ref,
                content_hash = excluded.content_hash,
                status = excluded.status,
                synced_at = excluded.synced_at,
                message = excluded.message
            """,
            (
                record.doc_id,
                record.target.value,
                record.remote_ref,
                record.content_hash,
                record.status.value,
                synced_at_str,
                record.message,
            ),
        )
        await self._db.commit()

    async def list_sync_records(self, target: SyncTargetKind | None = None) -> list[SyncRecord]:
        query = """
            SELECT doc_id, target, remote_ref, content_hash, status, synced_at, message
              FROM sync_records
        """
        params = []
        if target is not None:
            query += " WHERE target = ?"
            params.append(target.value)

        query += " ORDER BY synced_at ASC"

        async with self._db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [
                SyncRecord(
                    doc_id=row[0],
                    target=SyncTargetKind(row[1]),
                    remote_ref=row[2],
                    content_hash=row[3],
                    status=SyncStatus(row[4]),
                    synced_at=_parse_dt(row[5]),
                    message=row[6],
                )
                for row in rows
            ]


__all__ = ["SQLiteSourceDocumentStore"]
