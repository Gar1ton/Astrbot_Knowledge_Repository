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
    DocumentLifecycle,
    DocumentOrigin,
    PageChunk,
    SourceDocument,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
    ZoteroAttachment,
    ZoteroCollection,
    ZoteroItem,
    ZoteroLibrary,
    ZoteroRelation,
    ZoteroTag,
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


def _loads_list(val: str | None) -> list:
    """安全解析 JSON 数组，失败回退空列表。"""
    try:
        parsed = json.loads(val) if val else []
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# 文档列清单（唯一真相源，杜绝多处 SELECT 列错位）。
_DOC_COLUMNS = (
    "doc_id, title, file_path, content_type, size_bytes, content_hash, collection, tags, "
    "created_at, updated_at, needs_reindex, library_id, zotero_item_key, attachment_key, "
    "origin, read_only, zotero_version, markdown_rel_path, pages_rel_path, "
    "converter, converter_version, lifecycle_state, last_synced_at"
)


def _row_to_document(row: tuple) -> SourceDocument:
    """把 documents 表一行（列顺序同 _DOC_COLUMNS）映射为领域对象。"""
    return SourceDocument(
        doc_id=row[0],
        title=row[1],
        file_path=row[2],
        content_type=row[3],
        size_bytes=row[4],
        content_hash=row[5],
        collection=row[6],
        tags=_loads_list(row[7]),
        created_at=_parse_dt(row[8]),
        updated_at=_parse_dt(row[9]),
        needs_reindex=bool(row[10]),
        library_id=row[11],
        zotero_item_key=row[12],
        attachment_key=row[13],
        origin=DocumentOrigin(row[14]),
        read_only=bool(row[15]),
        zotero_version=row[16],
        markdown_rel_path=row[17],
        pages_rel_path=row[18],
        converter=row[19],
        converter_version=row[20],
        lifecycle_state=DocumentLifecycle(row[21]),
        last_synced_at=_parse_dt(row[22]),
    )


class SQLiteSourceDocumentStore(SourceDocumentStore):
    """基于 SQLite/aiosqlite 的生产 SourceDocumentStore 实现。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── 集合 ────────────────────────────────────────────────────

    async def upsert_collection(self, collection: Collection) -> None:
        created_at_str = _format_dt(collection.created_at or datetime.now(timezone.utc))
        await self._db.execute(
            """
            INSERT INTO collections
                (name, description, created_at, origin, zotero_collection_key, read_only)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                origin = excluded.origin,
                zotero_collection_key = excluded.zotero_collection_key,
                read_only = excluded.read_only
            """,
            (
                collection.name,
                collection.description,
                created_at_str,
                collection.origin.value,
                collection.zotero_collection_key,
                int(collection.read_only),
            ),
        )
        await self._db.commit()

    async def list_collections(self) -> list[Collection]:
        async with self._db.execute(
            "SELECT name, description, created_at, origin, zotero_collection_key, read_only "
            "FROM collections ORDER BY name ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                Collection(
                    name=row[0],
                    description=row[1],
                    created_at=_parse_dt(row[2]),
                    origin=DocumentOrigin(row[3]),
                    zotero_collection_key=row[4],
                    read_only=bool(row[5]),
                )
                for row in rows
            ]

    async def delete_collection(self, name: str) -> bool:
        async with self._db.execute("DELETE FROM collections WHERE name = ?", (name,)) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def move_documents_to_collection(self, from_name: str, to_name: str) -> int:
        now_str = _format_dt(datetime.now(timezone.utc))
        async with self._db.execute(
            "UPDATE documents SET collection = ?, updated_at = ? WHERE collection = ?",
            (to_name, now_str, from_name),
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount

    # ── 文档 ────────────────────────────────────────────────────

    async def add_document(self, document: SourceDocument) -> None:
        created_at_str = _format_dt(document.created_at or datetime.now(timezone.utc))
        updated_at_str = _format_dt(document.updated_at or datetime.now(timezone.utc))
        tags_str = json.dumps(document.tags)

        try:
            await self._db.execute(
                f"""
                INSERT INTO documents ({_DOC_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(document.needs_reindex),
                    document.library_id,
                    document.zotero_item_key,
                    document.attachment_key,
                    document.origin.value,
                    int(document.read_only),
                    document.zotero_version,
                    document.markdown_rel_path,
                    document.pages_rel_path,
                    document.converter,
                    document.converter_version,
                    document.lifecycle_state.value,
                    _format_dt(document.last_synced_at),
                ),
            )
            await self._db.commit()
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: documents.doc_id" in str(e):
                raise ValueError(f"duplicate doc_id: {document.doc_id}") from e
            raise

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        async with self._db.execute(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE doc_id = ?",
            (doc_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_document(row) if row is not None else None

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        query = f"SELECT {_DOC_COLUMNS} FROM documents"
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
            return [_row_to_document(row) for row in rows]

    async def list_pending_reindex_documents(self) -> list[SourceDocument]:
        """列出所有标记为待重建索引的文档。"""
        async with self._db.execute(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE needs_reindex = 1 "
            "ORDER BY created_at ASC, doc_id ASC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_document(row) for row in rows]

    async def update_document(self, document: SourceDocument) -> bool:
        updated_at_str = _format_dt(document.updated_at or datetime.now(timezone.utc))
        tags_str = json.dumps(document.tags)

        async with self._db.execute(
            """
            UPDATE documents SET
                title = ?, file_path = ?, content_type = ?, size_bytes = ?,
                content_hash = ?, collection = ?, tags = ?, updated_at = ?, needs_reindex = ?,
                library_id = ?, zotero_item_key = ?, attachment_key = ?, origin = ?,
                read_only = ?, zotero_version = ?, markdown_rel_path = ?, pages_rel_path = ?,
                converter = ?, converter_version = ?, lifecycle_state = ?, last_synced_at = ?
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
                int(document.needs_reindex),
                document.library_id,
                document.zotero_item_key,
                document.attachment_key,
                document.origin.value,
                int(document.read_only),
                document.zotero_version,
                document.markdown_rel_path,
                document.pages_rel_path,
                document.converter,
                document.converter_version,
                document.lifecycle_state.value,
                _format_dt(document.last_synced_at),
                document.doc_id,
            ),
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def delete_document(self, doc_id: str) -> bool:
        # SQLite 配了外键级联删除 (ON DELETE CASCADE) 关联的 chunks 会由外键级联自动删除
        # 但遵循仓储接口约定，为了确定 doc_id 存在性，我们可以在事务里手动操作
        async with self._db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,)) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    # ── 分块 ────────────────────────────────────────────────────

    async def replace_chunks(self, doc_id: str, chunks: list[DocumentChunk]) -> None:
        # 整体替换语义：先删该 doc 旧 chunks -> 再插入新 chunks。包裹在同一个事务内。
        try:
            await self._db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

            for chunk in chunks:
                await self._db.execute(
                    """
                    INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        doc_id,
                        chunk.ordinal,
                        chunk.text,
                        chunk.content_hash,
                        json.dumps(chunk.metadata),
                    ),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

    async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
        async with self._db.execute(
            """
            SELECT chunk_id, ordinal, text, content_hash, metadata
              FROM chunks WHERE doc_id = ?
             ORDER BY ordinal ASC
            """,
            (doc_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                try:
                    # 兼容可能存在的旧数据或未应用迁移时的情况，若列数不对或报错做安全回退
                    meta = json.loads(row[4]) if len(row) > 4 and row[4] else {}
                    if not isinstance(meta, dict):
                        meta = {}
                except Exception:
                    meta = {}

                results.append(
                    DocumentChunk(
                        chunk_id=row[0],
                        doc_id=doc_id,
                        ordinal=row[1],
                        text=row[2],
                        content_hash=row[3],
                        metadata=meta,
                    )
                )
            return results

    # ── LightRAG 索引状态 ───────────────────────────────────────

    async def set_lightrag_index_status(
        self, doc_id: str, collection: str, status: str, last_error: str = ""
    ) -> None:
        updated_at = _format_dt(datetime.now(timezone.utc))
        await self._db.execute(
            """
            INSERT INTO lightrag_index_status (doc_id, collection, status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                collection = excluded.collection, status = excluded.status,
                last_error = excluded.last_error, updated_at = excluded.updated_at
            """,
            (doc_id, collection, status, last_error, updated_at),
        )
        await self._db.commit()

    async def get_lightrag_index_status(self, doc_id: str) -> dict[str, str] | None:
        async with self._db.execute(
            "SELECT collection, status, last_error, updated_at "
            "FROM lightrag_index_status WHERE doc_id = ?",
            (doc_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "doc_id": doc_id,
                "collection": row[0],
                "status": row[1],
                "last_error": row[2],
                "updated_at": row[3],
            }

    # ── 图谱构建任务持久化 ─────────────────────────────────────────

    async def upsert_build_job(self, job: dict) -> None:
        await self._db.execute(
            """
            INSERT INTO graph_build_jobs
                (job_id, collection, status, stage,
                 processed_docs, failed_docs, total_docs,
                 processed_chunks, failed_chunks, total_chunks,
                 recent_error, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status, stage = excluded.stage,
                processed_docs = excluded.processed_docs,
                failed_docs = excluded.failed_docs,
                total_docs = excluded.total_docs,
                processed_chunks = excluded.processed_chunks,
                failed_chunks = excluded.failed_chunks,
                total_chunks = excluded.total_chunks,
                recent_error = excluded.recent_error,
                finished_at = excluded.finished_at
            """,
            (
                job["job_id"], job["collection"], job["status"], job.get("stage", ""),
                job.get("processed_docs", 0), job.get("failed_docs", 0),
                job.get("total_docs", 0),
                job.get("processed_chunks", 0), job.get("failed_chunks", 0),
                job.get("total_chunks", 0),
                job.get("recent_error", ""),
                job.get("started_at", ""), job.get("finished_at"),
            ),
        )
        await self._db.commit()

    async def list_build_jobs(
        self, collection: str | None = None, limit: int = 20
    ) -> list[dict]:
        if collection is not None:
            async with self._db.execute(
                "SELECT job_id, collection, status, stage, processed_docs, failed_docs, "
                "total_docs, processed_chunks, failed_chunks, total_chunks, recent_error, "
                "started_at, finished_at, created_at "
                "FROM graph_build_jobs WHERE collection = ? ORDER BY created_at DESC LIMIT ?",
                (collection, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with self._db.execute(
                "SELECT job_id, collection, status, stage, processed_docs, failed_docs, "
                "total_docs, processed_chunks, failed_chunks, total_chunks, recent_error, "
                "started_at, finished_at, created_at "
                "FROM graph_build_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "job_id": r[0], "collection": r[1], "status": r[2], "stage": r[3],
                "processed_docs": r[4], "failed_docs": r[5], "total_docs": r[6],
                "processed_chunks": r[7], "failed_chunks": r[8], "total_chunks": r[9],
                "recent_error": r[10], "started_at": r[11],
                "finished_at": r[12], "created_at": r[13],
            }
            for r in rows
        ]

    async def mark_interrupted_build_jobs(self) -> int:
        cursor = await self._db.execute(
            "UPDATE graph_build_jobs SET status = 'interrupted', stage = 'interrupted' "
            "WHERE status IN ('queued', 'running')"
        )
        await self._db.commit()
        return cursor.rowcount

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


    # ── 聊天记录 ─────────────────────────────────────────────────

    async def add_chat_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list | None = None,
        retrieval_mode: str = "",
    ) -> None:
        now = _format_dt(datetime.now(timezone.utc))
        await self._db.execute(
            """
            INSERT INTO chat_history
                (conversation_id, role, content, sources, retrieval_mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, json.dumps(sources or []), retrieval_mode, now),
        )
        await self._db.commit()

    async def get_chat_messages(self, conversation_id: str) -> list[dict]:
        async with self._db.execute(
            """
            SELECT role, content, sources, retrieval_mode, created_at
              FROM chat_history WHERE conversation_id = ?
             ORDER BY id ASC
            """,
            (conversation_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        result = []
        for row in rows:
            result.append({
                "role": row[0],
                "content": row[1],
                "sources": json.loads(row[2]),
                "retrieval_mode": row[3],
                "created_at": row[4],
            })
        return result

    async def clear_chat_messages(self, conversation_id: str) -> None:
        await self._db.execute(
            "DELETE FROM chat_history WHERE conversation_id = ?",
            (conversation_id,),
        )
        await self._db.commit()

    # ── Zotero 逻辑镜像 ──────────────────────────────────────────

    async def upsert_zotero_library(self, library: ZoteroLibrary) -> None:
        await self._db.execute(
            """
            INSERT INTO zotero_libraries (library_id, library_type, name, raw_zotero_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(library_id) DO UPDATE SET
                library_type = excluded.library_type, name = excluded.name,
                raw_zotero_json = excluded.raw_zotero_json
            """,
            (
                library.library_id,
                library.library_type,
                library.name,
                json.dumps(library.raw_zotero_json),
            ),
        )
        await self._db.commit()

    async def upsert_zotero_collection(self, collection: ZoteroCollection) -> None:
        await self._db.execute(
            """
            INSERT INTO zotero_collections
                (collection_key, library_id, name, parent_collection_key, origin, raw_zotero_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_id, collection_key) DO UPDATE SET
                name = excluded.name, parent_collection_key = excluded.parent_collection_key,
                origin = excluded.origin, raw_zotero_json = excluded.raw_zotero_json
            """,
            (
                collection.collection_key,
                collection.library_id,
                collection.name,
                collection.parent_collection_key,
                collection.origin.value,
                json.dumps(collection.raw_zotero_json),
            ),
        )
        await self._db.commit()

    async def upsert_zotero_item(self, item: ZoteroItem) -> None:
        await self._db.execute(
            """
            INSERT INTO zotero_items
                (item_key, library_id, item_type, version, deleted, title, creators,
                 year, venue, doi, url, abstract, origin, date_added, date_modified,
                 raw_zotero_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_id, item_key) DO UPDATE SET
                item_type = excluded.item_type, version = excluded.version,
                deleted = excluded.deleted, title = excluded.title,
                creators = excluded.creators, year = excluded.year, venue = excluded.venue,
                doi = excluded.doi, url = excluded.url, abstract = excluded.abstract,
                origin = excluded.origin, date_added = excluded.date_added,
                date_modified = excluded.date_modified, raw_zotero_json = excluded.raw_zotero_json
            """,
            (
                item.item_key,
                item.library_id,
                item.item_type,
                item.version,
                int(item.deleted),
                item.title,
                json.dumps(item.creators),
                item.year,
                item.venue,
                item.doi,
                item.url,
                item.abstract,
                item.origin.value,
                _format_dt(item.date_added),
                _format_dt(item.date_modified),
                json.dumps(item.raw_zotero_json),
            ),
        )
        await self._db.commit()

    async def upsert_zotero_attachment(self, attachment: ZoteroAttachment) -> None:
        await self._db.execute(
            """
            INSERT INTO zotero_attachments
                (attachment_key, library_id, parent_item_key, content_type, filename,
                 path, resolved_path, link_mode, md5, raw_zotero_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_id, attachment_key) DO UPDATE SET
                parent_item_key = excluded.parent_item_key,
                content_type = excluded.content_type, filename = excluded.filename,
                path = excluded.path, resolved_path = excluded.resolved_path,
                link_mode = excluded.link_mode, md5 = excluded.md5,
                raw_zotero_json = excluded.raw_zotero_json
            """,
            (
                attachment.attachment_key,
                attachment.library_id,
                attachment.parent_item_key,
                attachment.content_type,
                attachment.filename,
                attachment.path,
                attachment.resolved_path,
                attachment.link_mode,
                attachment.md5,
                json.dumps(attachment.raw_zotero_json),
            ),
        )
        await self._db.commit()

    async def set_item_collections(
        self, library_id: str, item_key: str, collection_keys: list[str]
    ) -> None:
        try:
            await self._db.execute(
                "DELETE FROM zotero_collection_items WHERE library_id = ? AND item_key = ?",
                (library_id, item_key),
            )
            for key in collection_keys:
                await self._db.execute(
                    "INSERT OR IGNORE INTO zotero_collection_items "
                    "(library_id, collection_key, item_key) VALUES (?, ?, ?)",
                    (library_id, key, item_key),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

    async def replace_item_tags(
        self, library_id: str, item_key: str, tags: list[ZoteroTag]
    ) -> None:
        try:
            await self._db.execute(
                "DELETE FROM zotero_item_tags WHERE library_id = ? AND item_key = ?",
                (library_id, item_key),
            )
            for t in tags:
                await self._db.execute(
                    "INSERT OR IGNORE INTO zotero_item_tags "
                    "(library_id, item_key, tag, type, origin) VALUES (?, ?, ?, ?, ?)",
                    (library_id, item_key, t.tag, t.type, t.origin.value),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

    async def upsert_zotero_relation(self, relation: ZoteroRelation, library_id: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO zotero_relations "
            "(library_id, source_item_key, relation_type, target_item_key) VALUES (?, ?, ?, ?)",
            (
                library_id,
                relation.source_item_key,
                relation.relation_type,
                relation.target_item_key,
            ),
        )
        await self._db.commit()

    async def list_zotero_items(self, library_id: str | None = None) -> list[ZoteroItem]:
        query = (
            "SELECT item_key, library_id, item_type, version, deleted, title, creators, "
            "year, venue, doi, url, abstract, origin, date_added, date_modified, raw_zotero_json "
            "FROM zotero_items"
        )
        params: tuple = ()
        if library_id is not None:
            query += " WHERE library_id = ?"
            params = (library_id,)
        query += " ORDER BY library_id ASC, item_key ASC"
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_zotero_item(r) for r in rows]

    async def get_zotero_item(self, library_id: str, item_key: str) -> ZoteroItem | None:
        async with self._db.execute(
            "SELECT item_key, library_id, item_type, version, deleted, title, creators, "
            "year, venue, doi, url, abstract, origin, date_added, date_modified, raw_zotero_json "
            "FROM zotero_items WHERE library_id = ? AND item_key = ?",
            (library_id, item_key),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_zotero_item(row) if row is not None else None

    @staticmethod
    def _row_to_zotero_item(row: tuple) -> ZoteroItem:
        return ZoteroItem(
            item_key=row[0],
            library_id=row[1],
            item_type=row[2],
            version=row[3],
            deleted=bool(row[4]),
            title=row[5],
            creators=_loads_list(row[6]),
            year=row[7],
            venue=row[8],
            doi=row[9],
            url=row[10],
            abstract=row[11],
            origin=DocumentOrigin(row[12]),
            date_added=_parse_dt(row[13]),
            date_modified=_parse_dt(row[14]),
            raw_zotero_json=json.loads(row[15]) if row[15] else {},
        )

    async def list_zotero_attachments(
        self, library_id: str, parent_item_key: str | None = None
    ) -> list[ZoteroAttachment]:
        query = (
            "SELECT attachment_key, library_id, parent_item_key, content_type, filename, "
            "path, resolved_path, link_mode, md5, raw_zotero_json FROM zotero_attachments "
            "WHERE library_id = ?"
        )
        params: list = [library_id]
        if parent_item_key is not None:
            query += " AND parent_item_key = ?"
            params.append(parent_item_key)
        query += " ORDER BY attachment_key ASC"
        async with self._db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [
                ZoteroAttachment(
                    attachment_key=r[0],
                    library_id=r[1],
                    parent_item_key=r[2],
                    content_type=r[3],
                    filename=r[4],
                    path=r[5],
                    resolved_path=r[6],
                    link_mode=r[7],
                    md5=r[8],
                    raw_zotero_json=json.loads(r[9]) if r[9] else {},
                )
                for r in rows
            ]

    async def list_item_tags(self, library_id: str, item_key: str) -> list[ZoteroTag]:
        async with self._db.execute(
            "SELECT item_key, tag, type, origin FROM zotero_item_tags "
            "WHERE library_id = ? AND item_key = ? ORDER BY tag ASC",
            (library_id, item_key),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                ZoteroTag(item_key=r[0], tag=r[1], type=r[2], origin=DocumentOrigin(r[3]))
                for r in rows
            ]

    async def get_collection_descendants(
        self, library_id: str, collection_key: str
    ) -> list[str]:
        # 递归 CTE 自顶向下遍历集合树，含自身。
        async with self._db.execute(
            """
            WITH RECURSIVE descendants(ck) AS (
                SELECT collection_key FROM zotero_collections
                 WHERE library_id = ? AND collection_key = ?
                UNION
                SELECT c.collection_key FROM zotero_collections c
                  JOIN descendants d ON c.parent_collection_key = d.ck
                 WHERE c.library_id = ?
            )
            SELECT ck FROM descendants
            """,
            (library_id, collection_key, library_id),
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def get_items_in_collections(
        self, library_id: str, collection_keys: list[str]
    ) -> list[str]:
        if not collection_keys:
            return []
        placeholders = ",".join("?" for _ in collection_keys)
        async with self._db.execute(
            f"SELECT DISTINCT item_key FROM zotero_collection_items "
            f"WHERE library_id = ? AND collection_key IN ({placeholders}) ORDER BY item_key ASC",
            (library_id, *collection_keys),
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def get_items_with_tag(self, library_id: str, tag: str) -> list[str]:
        async with self._db.execute(
            "SELECT DISTINCT item_key FROM zotero_item_tags "
            "WHERE library_id = ? AND tag = ? ORDER BY item_key ASC",
            (library_id, tag),
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    # ── 页面级 provenance ────────────────────────────────────────

    async def replace_page_chunks(
        self, document_id: str, page_chunks: list[PageChunk]
    ) -> None:
        try:
            await self._db.execute(
                "DELETE FROM page_chunks WHERE document_id = ?", (document_id,)
            )
            for pc in page_chunks:
                await self._db.execute(
                    "INSERT INTO page_chunks "
                    "(document_id, page, markdown_start_char, markdown_end_char) "
                    "VALUES (?, ?, ?, ?)",
                    (document_id, pc.page, pc.markdown_start_char, pc.markdown_end_char),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

    async def list_page_chunks(self, document_id: str) -> list[PageChunk]:
        async with self._db.execute(
            "SELECT page, markdown_start_char, markdown_end_char FROM page_chunks "
            "WHERE document_id = ? ORDER BY page ASC",
            (document_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                PageChunk(
                    document_id=document_id,
                    page=r[0],
                    markdown_start_char=r[1],
                    markdown_end_char=r[2],
                )
                for r in rows
            ]


__all__ = ["SQLiteSourceDocumentStore"]
