"""SourceDocumentStore SQLite 生产实现契约测试。

使用 aiosqlite 在内存数据库（:memory:）中运行，通过 migration runner 跑迁移，
并对 SQLiteSourceDocumentStore 执行与内存实现完全一致的契约校验。
"""
from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite
import pytest

from core.domain.models import (
    Collection,
    DocumentChunk,
    SourceDocument,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
)
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from migrations.runner import run_migrations


def _doc(doc_id: str, collection: str = "default", tags: list[str] | None = None) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"title-{doc_id}",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        content_hash=f"hash-{doc_id}",
        collection=collection,
        tags=list(tags or []),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
async def sqlite_store() -> SQLiteSourceDocumentStore:
    # 1) 连接内存中 SQLite，开启外键
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")

    # 2) 应用所有未执行的迁移
    await run_migrations(conn)

    # 3) 注入仓储实例
    store = SQLiteSourceDocumentStore(conn)

    # 4) 给一个默认集合，因为 documents.collection 必须引用 collections(name) 外键
    await store.upsert_collection(Collection(name="default"))
    await store.upsert_collection(Collection(name="x"))
    await store.upsert_collection(Collection(name="y"))

    yield store

    await conn.close()


async def test_add_and_get_document(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.add_document(_doc("d1"))
    got = await sqlite_store.get_document("d1")
    assert got is not None
    assert got.doc_id == "d1"
    assert got.title == "title-d1"
    assert await sqlite_store.get_document("missing") is None


async def test_add_duplicate_raises(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.add_document(_doc("d1"))
    with pytest.raises(ValueError):
        await sqlite_store.add_document(_doc("d1"))


async def test_list_documents_filters_by_collection_and_tag(
    sqlite_store: SQLiteSourceDocumentStore,
) -> None:
    await sqlite_store.add_document(_doc("d1", collection="x", tags=["t1"]))
    await sqlite_store.add_document(_doc("d2", collection="x", tags=["t2"]))
    await sqlite_store.add_document(_doc("d3", collection="y", tags=["t1"]))
    assert {d.doc_id for d in await sqlite_store.list_documents(collection="x")} == {"d1", "d2"}
    assert {d.doc_id for d in await sqlite_store.list_documents(tag="t1")} == {"d1", "d3"}
    assert {d.doc_id for d in await sqlite_store.list_documents(collection="x", tag="t1")} == {"d1"}
    assert len(await sqlite_store.list_documents()) == 3


async def test_update_document(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.add_document(_doc("d1", collection="x"))
    updated = _doc("d1", collection="y", tags=["new"])
    assert await sqlite_store.update_document(updated) is True
    got = await sqlite_store.get_document("d1")
    assert got is not None and got.collection == "y" and got.tags == ["new"]
    assert await sqlite_store.update_document(_doc("missing")) is False


async def test_delete_document_cascades_chunks(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.add_document(_doc("d1"))
    await sqlite_store.replace_chunks("d1", [DocumentChunk("c0", "d1", 0, "text", "h0")])
    assert await sqlite_store.delete_document("d1") is True
    assert await sqlite_store.get_document("d1") is None
    assert await sqlite_store.list_chunks("d1") == []
    assert await sqlite_store.delete_document("d1") is False


async def test_replace_and_list_chunks_ordered(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.add_document(_doc("d1"))
    await sqlite_store.replace_chunks(
        "d1",
        [
            DocumentChunk("c2", "d1", 2, "t2", "h2"),
            DocumentChunk("c0", "d1", 0, "t0", "h0"),
            DocumentChunk("c1", "d1", 1, "t1", "h1"),
        ],
    )
    assert [c.ordinal for c in await sqlite_store.list_chunks("d1")] == [0, 1, 2]
    # 整体替换：旧分块被覆盖
    await sqlite_store.replace_chunks("d1", [DocumentChunk("cX", "d1", 0, "tx", "hx")])
    chunks = await sqlite_store.list_chunks("d1")
    assert len(chunks) == 1 and chunks[0].chunk_id == "cX"


async def test_collection_crud(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.upsert_collection(Collection(name="b"))
    await sqlite_store.upsert_collection(Collection(name="a", description="first"))
    await sqlite_store.upsert_collection(Collection(name="a", description="updated"))  # upsert
    cols = await sqlite_store.list_collections()
    # "default", "x", "y" 是 fixture 里默认加好的，加上 "a", "b"，按 name 排序排序
    assert [c.name for c in cols] == ["a", "b", "default", "x", "y"]
    assert cols[0].description == "updated"
    assert await sqlite_store.delete_collection("a") is True
    assert await sqlite_store.delete_collection("a") is False


async def test_sync_record_crud(sqlite_store: SQLiteSourceDocumentStore) -> None:
    # 必须先添加文档，因为 sync_records.doc_id 是指向 documents(doc_id) 的外键
    await sqlite_store.add_document(_doc("d1"))

    # 1) 获取未同步的，返回 None
    assert await sqlite_store.get_sync_record("d1", SyncTargetKind.R2) is None

    # 2) 登记同步账目 (Upsert)
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    rec1 = SyncRecord(
        doc_id="d1",
        target=SyncTargetKind.R2,
        remote_ref="papers/d1.pdf",
        content_hash="hash-d1",
        status=SyncStatus.SYNCED,
        synced_at=now,
    )
    await sqlite_store.upsert_sync_record(rec1)

    # 3) 取回账目并验证
    got = await sqlite_store.get_sync_record("d1", SyncTargetKind.R2)
    assert got is not None
    assert got.doc_id == "d1"
    assert got.target == SyncTargetKind.R2
    assert got.remote_ref == "papers/d1.pdf"
    assert got.status == SyncStatus.SYNCED
    assert got.synced_at == now

    # 4) 列出并过滤
    recs = await sqlite_store.list_sync_records(SyncTargetKind.R2)
    assert len(recs) == 1
    assert recs[0].doc_id == "d1"

    # 5) 更新账目 (ON CONFLICT DO UPDATE)
    rec1.status = SyncStatus.FAILED
    rec1.message = "Failed to reconnect"
    await sqlite_store.upsert_sync_record(rec1)

    got_updated = await sqlite_store.get_sync_record("d1", SyncTargetKind.R2)
    assert got_updated is not None
    assert got_updated.status == SyncStatus.FAILED
    assert got_updated.message == "Failed to reconnect"

