"""旧库升级的故障恢复与并发契约；真实 SQLite 使用临时目录，模型与向量使用替身。"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from types import SimpleNamespace

import aiosqlite
import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.config import SourceStoreConfig
from kacore.domain.models import Collection, DocumentChunk, PageChunk, SourceDocument
from kacore.managers.artifact_provenance import PROCESSING_VERSION
from kacore.managers.ingest_manager import IngestManager
from kacore.managers.markdown_extractor import MarkdownArtifact, PageSpan
from kacore.migration_runner import run_migrations
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.source_store.sqlite import SQLiteSourceDocumentStore
from kacore.repository.vector_store.memory import InMemoryVectorStore
from kacore.utils.processing_lock import ProcessingLock, complete_thread_call

NEW_TEXT = "New body is much longer."


def extraction(*args):
    return MarkdownArtifact(NEW_TEXT, [PageSpan(1, 0, len(NEW_TEXT))], raw_pages=[NEW_TEXT])


async def seed(store, directory):
    await store.upsert_collection(Collection(name="default"))
    bundle = directory / "library" / "legacy"
    bundle.mkdir(parents=True)
    (bundle / "original.pdf").write_bytes(b"original fixture; extraction stubbed")
    (bundle / "clean.md").write_text("Old body.")
    doc = SourceDocument(
        "legacy", "User title", str(bundle / "original.pdf"), "application/pdf", 9, "pdf-hash",
        "default", local_meta={"chunk_schema": "clean_md_structural_v3", "user_note": "keep"},
    )
    await store.add_document(doc)
    await store.replace_chunks("legacy", [DocumentChunk(
        "legacy_c0000", "legacy", 0, "Old body.", "oldhash",
        {"chunk_schema": "clean_md_structural_v3", "start_char": 0, "end_char": 9},
    )])
    await store.replace_page_chunks("legacy", [PageChunk("legacy", 1, 0, 9)])
    return bundle


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_processing_commit_preserves_user_fields_and_marks_index_pending(tmp_path, backend):
    async with aiosqlite.connect(tmp_path / "db") as db:
        await run_migrations(db)
        store = (SQLiteSourceDocumentStore(db) if backend == "sqlite"
                 else InMemorySourceDocumentStore())
        bundle = await seed(store, tmp_path)
        manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
        manager._extract_artifact = extraction
        await manager.reextract_document("legacy")
        doc = await store.get_document("legacy")
        assert doc.title == "User title"
        assert doc.local_meta["user_note"] == "keep"
        assert doc.local_meta["processing_version"] == PROCESSING_VERSION
        assert "processing_pending" not in doc.local_meta
        assert doc.needs_reindex
        assert (await store.list_chunks("legacy"))[0].text == NEW_TEXT
        assert (await store.list_page_chunks("legacy"))[0].markdown_end_char == len(NEW_TEXT)
        assert (bundle / "original.pdf").read_bytes() == b"original fixture; extraction stubbed"


async def test_page_insert_failure_rolls_back_and_recovers_after_reopen(tmp_path):
    db_path = tmp_path / "db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await run_migrations(db)
        store = SQLiteSourceDocumentStore(db)
        await seed(store, tmp_path)
        manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
        manager._extract_artifact = extraction
        # 触发器在新 chunks 已 INSERT 后拒绝页映射，覆盖真实事务回滚。
        await db.execute(
            "CREATE TEMP TRIGGER fail_pages BEFORE INSERT ON page_chunks "
            "BEGIN SELECT RAISE(ABORT, 'page write failed'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="page write failed"):
            await manager.reextract_document("legacy")
        assert (await store.list_chunks("legacy"))[0].text == "Old body."
        assert (await store.list_page_chunks("legacy"))[0].markdown_end_char == 9
        doc = await store.get_document("legacy")
        assert doc.needs_reindex and doc.local_meta["processing_pending"]
        assert "processing_version" not in doc.local_meta
        assert await (await db.execute("PRAGMA integrity_check")).fetchall() == [("ok",)]
        assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []
        api = KnowledgeRepositoryApi(source_store=store, kb_reader=None, ingest_manager=manager)
        with pytest.raises(RuntimeError, match="recovery required"):
            await api.get_document_footnotes("legacy")
        with pytest.raises(RuntimeError, match="recovery required"):
            await api._clear_document_needs_reindex("legacy")

    # 关闭再打开数据库，模拟进程重启；索引入口必须先恢复抽取再消费 chunks。
    async with aiosqlite.connect(db_path) as db:
        assert await run_migrations(db) == []
        store = SQLiteSourceDocumentStore(db)
        manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
        manager._extract_artifact = extraction
        vectors = InMemoryVectorStore()

        async def embed(texts):
            assert texts == [NEW_TEXT]
            return [[1.0, 0.0]]

        api = KnowledgeRepositoryApi(
            source_store=store, kb_reader=None, ingest_manager=manager, vector_store=vectors,
            embedding_provider=SimpleNamespace(embed_documents=embed),
        )
        await api._index_document_chunks_with_retry("legacy", "default", context="recovery")
        await api._clear_document_needs_reindex("legacy")
        doc = await store.get_document("legacy")
        assert not doc.needs_reindex and "processing_pending" not in doc.local_meta
        assert (await store.list_page_chunks("legacy"))[0].markdown_end_char == len(NEW_TEXT)
        assert len(await vectors.search("default", [1.0, 0.0], 5)) == 1


async def test_cancelled_processing_retains_recovery_marker(tmp_path):
    store = InMemorySourceDocumentStore()
    await seed(store, tmp_path)
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    manager._extract_artifact = extraction
    original = store.commit_document_processing

    async def cancel(*args):
        raise asyncio.CancelledError()

    store.commit_document_processing = cancel
    with pytest.raises(asyncio.CancelledError):
        await manager.reextract_document("legacy")
    assert (await store.get_document("legacy")).local_meta["processing_pending"]
    store.commit_document_processing = original
    await asyncio.wait_for(manager.reextract_document("legacy"), 2)
    assert "processing_pending" not in (await store.get_document("legacy")).local_meta


async def test_failed_text_rechunk_recovers_from_original(tmp_path):
    store = InMemorySourceDocumentStore()
    bundle = await seed(store, tmp_path)
    (bundle / "original.pdf").write_text("Original plain text.")
    doc = await store.get_document("legacy")
    doc.content_type = "text/plain"
    await store.update_document(doc)
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    original = store.commit_document_processing

    async def fail(*args):
        raise RuntimeError("commit failed")

    store.commit_document_processing = fail
    with pytest.raises(RuntimeError, match="commit failed"):
        await manager.rebuild_document_chunks_from_artifact("legacy")
    assert (await store.get_document("legacy")).local_meta["processing_pending"]
    store.commit_document_processing = original
    await manager.rebuild_document_chunks_from_artifact("legacy")
    assert (await store.list_chunks("legacy"))[0].text == "Original plain text."


async def test_missing_original_never_indexes_or_clears_pending(tmp_path):
    store = InMemorySourceDocumentStore()
    bundle = await seed(store, tmp_path)
    (bundle / "original.pdf").unlink()
    doc = await store.get_document("legacy")
    doc.needs_reindex = True
    doc.local_meta["processing_pending"] = True
    await store.update_document(doc)
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    api = KnowledgeRepositoryApi(
        source_store=store, kb_reader=None, ingest_manager=manager,
        vector_store=InMemoryVectorStore(), embedding_provider=SimpleNamespace(),
    )
    with pytest.raises(FileNotFoundError, match="Original PDF"):
        await api._index_document_chunks_with_retry("legacy", "default", context="recovery")
    assert (await store.get_document("legacy")).needs_reindex


async def test_auto_rebuild_waits_for_manual_processing(tmp_path):
    store = InMemorySourceDocumentStore()
    await seed(store, tmp_path)
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    manager._extract_artifact = extraction
    entered, release = asyncio.Event(), asyncio.Event()
    embedding_calls = []

    async def embed(texts):
        embedding_calls.append(texts)
        entered.set()
        await release.wait()
        return [[1.0, 0.0] for _ in texts]

    api = KnowledgeRepositoryApi(
        source_store=store, kb_reader=None, ingest_manager=manager,
        vector_store=InMemoryVectorStore(),
        embedding_provider=SimpleNamespace(embed_documents=embed),
    )
    scheduled = []

    def notify():
        scheduled.append(asyncio.create_task(api.run_milvus_rebuild_to_completion()))

    api.attach_auto_reindex_scheduler(SimpleNamespace(notify=notify))
    manual = asyncio.create_task(api.reprocess_documents_with_stale_cleaning())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        # 已唤醒自动任务；手动索引尚未结束。子任务不得继承维护锁所有权。
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert scheduled and not scheduled[0].done()
        assert len(embedding_calls) == 1
        release.set()
        result = await asyncio.wait_for(manual, 2)
        await asyncio.wait_for(asyncio.gather(*scheduled), 2)
        assert result["pending_reindex"] == []
        assert not (await store.get_document("legacy")).needs_reindex
        assert len(embedding_calls) == 1  # 自动任务进入后重读待索引集合，已无工作。
    finally:
        release.set()
        for task in [manual, *scheduled]:
            if not task.done():
                task.cancel()
        await asyncio.gather(manual, *scheduled, return_exceptions=True)


async def test_processing_lock_cancelled_waiter_does_not_unlock_owner():
    lock = ProcessingLock()
    entered = asyncio.Event()

    async def wait_for_lock():
        async with lock:
            entered.set()

    async with lock:
        async with lock:
            waiter = asyncio.create_task(wait_for_lock())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not entered.is_set()
    await asyncio.wait_for(wait_for_lock(), 1)


async def test_cancelled_file_worker_finishes_before_unlocking():
    lock = ProcessingLock()
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    events = []

    def write_file():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        events.append("write_finished")

    async def processing():
        async with lock:
            await complete_thread_call(write_file)

    async def retry():
        async with lock:
            events.append("retry")

    task = asyncio.create_task(processing())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    retry_task = asyncio.create_task(retry())
    try:
        await asyncio.sleep(0)
        assert not task.done() and not retry_task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        await asyncio.wait_for(retry_task, 1)
        assert events == ["write_finished", "retry"]
    finally:
        release.set()
        await asyncio.gather(task, retry_task, return_exceptions=True)


async def test_maintenance_without_vectors_reports_pending_and_retries_only_index(tmp_path):
    store = InMemorySourceDocumentStore()
    await seed(store, tmp_path)
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    manager._extract_artifact = extraction
    api = KnowledgeRepositoryApi(source_store=store, kb_reader=None, ingest_manager=manager)
    result = await api.reprocess_documents_with_stale_cleaning()
    assert result["pending_reindex"] == ["legacy"]

    def no_more_extraction(*args):
        raise AssertionError("already processed PDF must not be extracted again")

    manager._extract_artifact = no_more_extraction
    result = await api.reprocess_documents_with_stale_cleaning()
    assert not result["failed"] and result["pending_reindex"] == ["legacy"]
