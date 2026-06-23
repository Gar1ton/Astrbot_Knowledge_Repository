"""SourceDocumentStore SQLite 生产实现契约测试。

使用 aiosqlite 在内存数据库（:memory:）中运行，通过 migration runner 跑迁移，
并对 SQLiteSourceDocumentStore 执行与内存实现完全一致的契约校验。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest

from core.domain.models import (
    Collection,
    ConsoleScopeState,
    DocumentChunk,
    ScopedNote,
    SourceDocument,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
)
from core.migration_runner import run_migrations
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore


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


async def test_graph_build_job_pause_migration_defaults_and_cleanup() -> None:
    conn = await aiosqlite.connect(":memory:")
    await run_migrations(conn)
    store = SQLiteSourceDocumentStore(conn)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    for status in ["queued", "running", "pause_requested", "paused"]:
        await conn.execute(
            "INSERT INTO graph_build_jobs (job_id, collection, status, stage, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"job-{status}", "papers", status, status, started),
        )
    await conn.commit()

    jobs = {job["job_id"]: job for job in await store.list_build_jobs(limit=10)}
    assert jobs["job-queued"]["pause_requested"] is False
    assert jobs["job-queued"]["paused_at"] is None
    assert jobs["job-queued"]["paused_seconds"] == 0
    assert jobs["job-queued"]["progress_current"] == 0
    assert jobs["job-queued"]["progress_total"] == 0

    changed = await store.mark_interrupted_build_jobs()
    jobs = {job["job_id"]: job for job in await store.list_build_jobs(limit=10)}
    assert changed == 3
    assert jobs["job-queued"]["status"] == "interrupted"
    assert jobs["job-running"]["status"] == "interrupted"
    assert jobs["job-pause_requested"]["status"] == "interrupted"
    assert jobs["job-paused"]["status"] == "paused"
    resumable = await store.get_latest_resumable_build_job()
    assert resumable and resumable["job_id"] == "job-paused"
    await conn.close()


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


async def test_file_database_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "restart.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA foreign_keys = ON")
    await run_migrations(conn)
    store = SQLiteSourceDocumentStore(conn)
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("persisted"))
    await conn.close()

    reopened = await aiosqlite.connect(db_path)
    await reopened.execute("PRAGMA foreign_keys = ON")
    assert await run_migrations(reopened) == []
    reopened_store = SQLiteSourceDocumentStore(reopened)
    got = await reopened_store.get_document("persisted")
    assert got is not None and got.doc_id == "persisted"
    await reopened.close()


async def test_chunk_metadata_persistence(sqlite_store: SQLiteSourceDocumentStore) -> None:
    # 1) Setup document and chunks with metadata
    doc = _doc("meta_doc")
    await sqlite_store.add_document(doc)

    chunks = [
        DocumentChunk(
            chunk_id="mc1",
            doc_id="meta_doc",
            ordinal=0,
            text="First paragraph text on page 1.",
            content_hash="h1",
            metadata={"page_number": 1, "locator": "page_1_p1", "paragraph": 1}
        ),
        DocumentChunk(
            chunk_id="mc2",
            doc_id="meta_doc",
            ordinal=1,
            text="Second paragraph text on page 2.",
            content_hash="h2",
            metadata={"page_number": 2, "locator": "page_2_p1", "paragraph": 1}
        )
    ]
    await sqlite_store.replace_chunks("meta_doc", chunks)

    # 2) Retrieve chunks and verify metadata
    got = await sqlite_store.list_chunks("meta_doc")
    assert len(got) == 2
    assert got[0].chunk_id == "mc1"
    assert got[0].metadata == {"page_number": 1, "locator": "page_1_p1", "paragraph": 1}
    assert got[1].chunk_id == "mc2"
    assert got[1].metadata == {"page_number": 2, "locator": "page_2_p1", "paragraph": 1}


async def test_scoped_notes_persist_zotero_shape(
    sqlite_store: SQLiteSourceDocumentStore,
) -> None:
    await sqlite_store.add_document(_doc("note-doc", collection="default", tags=["tag1"]))
    note = ScopedNote(
        id="n1",
        scope_type="document",
        scope_key="note-doc",
        content="plain note",
        note_html="<p>plain note</p>",
        doc_id="note-doc",
        library_id="1",
        parent_item_key="ITEM1",
        parent_attachment_key="ATT1",
        tags=["tag1"],
        collections=["default"],
        raw_zotero_json={"itemType": "note", "parentItem": "ITEM1", "note": "<p>plain note</p>"},
    )
    await sqlite_store.add_scoped_note(note)

    notes = await sqlite_store.list_scoped_notes("document", "note-doc")
    assert len(notes) == 1
    assert notes[0].parent_item_key == "ITEM1"
    assert notes[0].raw_zotero_json["itemType"] == "note"

    notes[0].content = "updated"
    notes[0].raw_zotero_json["note"] = "<p>updated</p>"
    assert await sqlite_store.update_scoped_note(notes[0]) is True
    got = await sqlite_store.get_scoped_note("n1")
    assert got is not None
    assert got.content == "updated"
    assert got.raw_zotero_json["note"] == "<p>updated</p>"


async def test_chat_lock_and_preserve_locked_clear(
    sqlite_store: SQLiteSourceDocumentStore,
) -> None:
    await sqlite_store.add_chat_message("conv", "user", "q")
    await sqlite_store.add_chat_message("conv", "assistant", "a")
    locked = await sqlite_store.set_chat_message_locked("conv", 1, True)
    assert locked is not None and locked["locked"] is True

    await sqlite_store.clear_chat_messages("conv", preserve_locked=True)
    messages = await sqlite_store.get_chat_messages("conv")
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["locked"] is True


async def test_console_scope_state_upsert(sqlite_store: SQLiteSourceDocumentStore) -> None:
    await sqlite_store.upsert_console_scope_state(
        ConsoleScopeState(
            scope_type="collection",
            scope_key="papers",
            selected_collection="papers",
            selected_doc_id="d1",
            note_doc_id="d1",
            payload={"right": "notes"},
        )
    )
    state = await sqlite_store.get_console_scope_state("collection", "papers")
    assert state is not None
    assert state.selected_doc_id == "d1"
    assert state.payload == {"right": "notes"}


# ── 统一多归属集合树（v0.26.3）SQL 实现契约 ──────────────────────


async def test_tree_and_multi_membership_sqlite(sqlite_store: SQLiteSourceDocumentStore) -> None:
    # 建 root → child → grand
    keys = {}
    parent = ""
    for name in ("root", "child", "grand"):
        c = Collection(name=name, parent_key=parent)
        await sqlite_store.upsert_collection(c)
        keys[name] = c.coll_key
        parent = c.coll_key
    extra = Collection(name="extra")
    await sqlite_store.upsert_collection(extra)

    assert set(await sqlite_store.get_local_collection_descendants(keys["root"])) == set(
        keys.values()
    )

    d1 = _doc("d1")
    d1.collection_keys = [keys["child"]]
    await sqlite_store.add_document(d1)
    d2 = _doc("d2")
    d2.collection_keys = [keys["grand"], extra.coll_key]
    await sqlite_store.add_document(d2)

    child_docs = await sqlite_store.list_documents_by_collection_key(keys["child"])
    assert {d.doc_id for d in child_docs} == {"d1"}
    assert {
        d.doc_id
        for d in await sqlite_store.list_documents_by_collection_key(keys["root"], descendants=True)
    } == {"d1", "d2"}
    assert set((await sqlite_store.get_document("d2")).collection_keys) == {
        keys["grand"],
        extra.coll_key,
    }


async def test_same_name_subcollections_sqlite(sqlite_store: SQLiteSourceDocumentStore) -> None:
    a = Collection(name="A")
    await sqlite_store.upsert_collection(a)
    s1 = Collection(name="Dup", parent_key=a.coll_key)
    s2 = Collection(name="Dup", parent_key="")
    await sqlite_store.upsert_collection(s1)
    await sqlite_store.upsert_collection(s2)
    assert s1.coll_key != s2.coll_key
    names = [c.name for c in await sqlite_store.list_collections() if c.name == "Dup"]
    assert len(names) == 2


async def test_exact_mentions_sqlite_scope_and_subtree(
    sqlite_store: SQLiteSourceDocumentStore,
) -> None:
    """SQLite 单 SQL 覆写：正文精确命中 + 父集合覆盖子树 + 子集合排除兄弟（中性占位词）。"""
    root = Collection(name="ROOT_SCOPE_A")
    await sqlite_store.upsert_collection(root)
    child = Collection(name="CHILD_SCOPE_B", parent_key=root.coll_key)
    await sqlite_store.upsert_collection(child)
    sibling = Collection(name="SIBLING_SCOPE_C")
    await sqlite_store.upsert_collection(sibling)

    child_doc = _doc("doc-child", collection="CHILD_SCOPE_B")
    child_doc.collection_keys = [child.coll_key]
    await sqlite_store.add_document(child_doc)
    await sqlite_store.replace_chunks(
        "doc-child",
        [DocumentChunk("ch-0", "doc-child", 0, "body text with EXACT_TERM_A inside", "h0")],
    )
    sib_doc = _doc("doc-sibling", collection="SIBLING_SCOPE_C")
    sib_doc.collection_keys = [sibling.coll_key]
    await sqlite_store.add_document(sib_doc)
    await sqlite_store.replace_chunks(
        "doc-sibling",
        [DocumentChunk("sb-0", "doc-sibling", 0, "sibling body with EXACT_TERM_A too", "h1")],
    )

    # 全局：正文命中两篇，标题都不含该词。
    g = await sqlite_store.search_exact_mentions(["EXACT_TERM_A"], None)
    assert {h["doc_id"] for h in g} == {"doc-child", "doc-sibling"}
    assert all("EXACT_TERM_A" not in h["title"] for h in g)
    # 父集合覆盖子树、排除树外兄弟。
    root_hits = await sqlite_store.search_exact_mentions(["EXACT_TERM_A"], root.coll_key)
    assert {h["doc_id"] for h in root_hits} == {"doc-child"}
    # 子集合只含自身。
    child_hits = await sqlite_store.search_exact_mentions(["EXACT_TERM_A"], child.coll_key)
    assert {h["doc_id"] for h in child_hits} == {"doc-child"}
    # 无命中 / 过短词。
    assert await sqlite_store.search_exact_mentions(["MISSING_TERM_Z"], None) == []
    assert await sqlite_store.search_exact_mentions(["a"], None) == []


async def test_exact_mentions_sqlite_ascii_terms_require_boundaries(
    sqlite_store: SQLiteSourceDocumentStore,
) -> None:
    """SQLite LIKE 只做粗筛，返回前仍要复核 ASCII 词边界。"""
    coll = Collection(name="BOUNDARY_SCOPE_A")
    await sqlite_store.upsert_collection(coll)

    true_doc = _doc("doc-true", collection="BOUNDARY_SCOPE_A")
    true_doc.collection_keys = [coll.coll_key]
    await sqlite_store.add_document(true_doc)
    await sqlite_store.replace_chunks(
        "doc-true",
        [
            DocumentChunk("bt-0", "doc-true", 0, "SHAP/XAI and SHAP values appear here", "bt")
        ],
    )

    false_doc = _doc("doc-false", collection="BOUNDARY_SCOPE_A")
    false_doc.collection_keys = [coll.coll_key]
    await sqlite_store.add_document(false_doc)
    await sqlite_store.replace_chunks(
        "doc-false",
        [DocumentChunk("bf-0", "doc-false", 0, "shape and shaping are unrelated", "bf")],
    )

    hits = await sqlite_store.search_exact_mentions(["SHAP"], coll.coll_key)
    assert {hit["doc_id"] for hit in hits} == {"doc-true"}
