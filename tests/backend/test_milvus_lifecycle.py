"""Milvus 生命周期回归：临时库释放锁、取消线程操作和失败装配清理。"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.domain.models import DocumentChunk
from kacore.plugin_initializer import PluginInitializer
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.vector_store.milvus_lite import MilvusLiteVectorStore

_REAL_MILVUS = all(importlib.util.find_spec(name) is not None
                   for name in ("pymilvus", "milvus_lite"))
if _REAL_MILVUS:
    # 在 mock 窗口外加载原生依赖，避免 patch.dict(sys.modules) 回滚初次导入的子模块。
    # 这里只导入 SDK，不启动服务、不打开数据库。
    importlib.import_module("pymilvus")
    importlib.import_module("milvus_lite.adapter.grpc.server")


@pytest.fixture
def opened_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []
    client = MagicMock()
    client.flush.side_effect = lambda _: events.append("flush")
    client.close.side_effect = lambda: events.append("client_close")
    manager = MagicMock()
    manager.release_server.side_effect = lambda _: events.append("server_release")
    monkeypatch.setitem(
        sys.modules, "milvus_lite.server_manager",
        SimpleNamespace(server_manager_instance=manager),
    )
    store = MilvusLiteVectorStore(str(tmp_path / "vectors.db"), dim=4)
    store._client = client
    store._initialized = True
    return store, client, manager, events


async def test_close_releases_only_owned_server_and_is_idempotent(opened_store) -> None:
    store, client, manager, events = opened_store
    await store.close()
    await store.close()
    assert events == ["flush", "client_close", "server_release"]
    manager.release_server.assert_called_once_with(store._db_path)
    manager.release_all.assert_not_called()
    assert store._client is None
    assert not store._initialized
    client.drop_collection.assert_not_called()


@pytest.mark.parametrize("failed_step", ["flush", "close"])
async def test_close_releases_server_even_when_client_cleanup_fails(
    opened_store, failed_step: str,
) -> None:
    store, client, manager, _ = opened_store
    getattr(client, failed_step).side_effect = RuntimeError(failed_step)
    with pytest.raises(RuntimeError, match=failed_step):
        await store.close()
    client.close.assert_called_once()
    manager.release_server.assert_called_once_with(store._db_path)
    assert store._client is None


async def test_unopened_close_does_not_release_server_and_prevents_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_class = MagicMock()
    monkeypatch.setitem(sys.modules, "pymilvus", SimpleNamespace(
        MilvusClient=client_class, DataType=SimpleNamespace(),
    ))
    store = MilvusLiteVectorStore(str(tmp_path / "never_opened.db"))
    await store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.validate_schema()
    client_class.assert_not_called()


@pytest.mark.parametrize("opening", ["validate", "clear"])
async def test_failed_client_constructor_releases_started_service(
    opened_store, monkeypatch: pytest.MonkeyPatch, opening: str,
) -> None:
    store, _, manager, _ = opened_store
    store._client = None
    store._initialized = False
    monkeypatch.setitem(sys.modules, "pymilvus", SimpleNamespace(
        MilvusClient=MagicMock(side_effect=RuntimeError("RPC connection failed")),
        DataType=SimpleNamespace(),
    ))
    with pytest.raises(RuntimeError, match="RPC connection failed"):
        if opening == "validate":
            store.validate_schema()
        else:
            await store.clear()
    await store.close()
    manager.release_server.assert_called_once_with(store._db_path)


async def test_cancelled_close_still_finishes_cleanup(opened_store) -> None:
    store, client, _, events = opened_store
    entered = threading.Event()
    proceed = threading.Event()

    def flush(_) -> None:
        entered.set()
        assert proceed.wait(5)
        events.append("flush")

    client.flush.side_effect = flush
    closing = asyncio.create_task(store.close())
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        closing.cancel()
        await asyncio.sleep(0.01)
        closing.cancel()
        await asyncio.sleep(0.01)
        assert not closing.done()
    finally:
        proceed.set()
        await asyncio.gather(closing, return_exceptions=True)
    assert closing.cancelled()
    assert events == ["flush", "client_close", "server_release"]
    await store.close()


async def test_cancelled_rpc_finishes_before_server_release(opened_store) -> None:
    store, client, _, events = opened_store
    entered = threading.Event()
    proceed = threading.Event()

    def upsert(**kwargs) -> None:
        entered.set()
        assert proceed.wait(5)
        events.append("write_done")

    client.upsert.side_effect = upsert
    write = asyncio.create_task(store.upsert_chunks(
        [DocumentChunk("c1", "d1", 0, "text", "hash")], [[1.0, 0.0, 0.0, 0.0]],
    ))
    assert await asyncio.to_thread(entered.wait, 5)
    write.cancel()
    closing = asyncio.create_task(store.close())
    try:
        await asyncio.sleep(0.02)
        assert not closing.done()
        assert "server_release" not in events
    finally:
        proceed.set()
        await asyncio.gather(write, closing, return_exceptions=True)
    assert write.cancelled()
    assert events == ["write_done", "flush", "client_close", "server_release"]


async def test_cancelled_initialization_finishes_before_close(opened_store) -> None:
    store, client, _, events = opened_store
    store._client = None
    store._initialized = False
    entered = threading.Event()
    proceed = threading.Event()

    def initialize() -> None:
        entered.set()
        assert proceed.wait(5)
        store._client = client
        store._initialized = True
        events.append("init_done")

    with patch.object(store, "_init_client", side_effect=initialize):
        opening = asyncio.create_task(store._ensure_client())
        assert await asyncio.to_thread(entered.wait, 5)
        opening.cancel()
        closing = asyncio.create_task(store.close())
        try:
            await asyncio.sleep(0.02)
            assert not closing.done()
        finally:
            proceed.set()
            await asyncio.gather(opening, closing, return_exceptions=True)
    assert events == ["init_done", "flush", "client_close", "server_release"]


async def test_initializer_closes_store_after_generic_validation_failure(tmp_path: Path) -> None:
    client = SimpleNamespace(
        validate_schema=MagicMock(side_effect=RuntimeError("load failed")),
        close=AsyncMock(),
    )
    provider = SimpleNamespace(embed_query=AsyncMock(return_value=[0.1] * 4))
    with (
        patch("kacore.plugin_initializer.milvus_runtime_status", return_value={"ready": True}),
        patch("kacore.plugin_initializer._module_available", return_value=True),
        patch("kacore.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
              return_value=provider),
        patch("kacore.repository.vector_store.milvus_lite.MilvusLiteVectorStore",
              return_value=client),
    ):
        initializer = PluginInitializer(object(), {
            "vector_db": {"backend": "milvus"}, "graph": {"enabled": False},
        }, tmp_path)
        try:
            await initializer.initialize()
            assert initializer.vector_store is None
            assert initializer._vector_store_init_error == "load failed"
            client.close.assert_awaited_once()
        finally:
            await initializer.teardown()


async def test_teardown_stops_scheduler_then_milvus_build_before_store_close(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    started = asyncio.Event()
    build_started = asyncio.Event()
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(), kb_reader=InMemoryKnowledgeBaseReader(),
        sync_targets={},
    )

    async def build() -> None:
        build_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("build_stopped")

    async def scheduler() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # 暴露顺序竞态：调度器退出前仍可能留下最后一个已创建的构建任务。
            api._milvus_build_task = asyncio.create_task(build())
            await build_started.wait()
            events.append("scheduler_stopped")

    initializer = PluginInitializer(object(), {}, tmp_path)
    initializer.api = api
    initializer.vector_store = SimpleNamespace(close=AsyncMock(
        side_effect=lambda: events.append("store_closed"),
    ))
    initializer._auto_reindex_task = asyncio.create_task(scheduler())
    await started.wait()
    try:
        await initializer.teardown()
        assert events == ["scheduler_stopped", "build_stopped", "store_closed"]
        assert api._milvus_build_task is None
    finally:
        task = api._milvus_build_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.skipif(not _REAL_MILVUS, reason="需要 Milvus Lite 集成依赖")
async def test_real_initializer_reload_and_reinstallation_keep_vectors(tmp_path: Path) -> None:
    config = {
        "vector_db": {"backend": "milvus", "auto_rebuild_enabled": False},
        "graph": {"enabled": False},
    }
    provider = SimpleNamespace(embed_query=AsyncMock(return_value=[0.1] * 4))
    first = PluginInitializer(object(), config, tmp_path)
    second = PluginInitializer(object(), config, tmp_path)
    vector = [1.0, 0.0, 0.0, 0.0]
    with (
        patch("kacore.plugin_initializer._module_available", return_value=True),
        patch("kacore.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
              return_value=provider),
    ):
        try:
            await first.initialize()
            original = first.vector_store
            assert original is not None
            await original.upsert_chunks(
                [DocumentChunk("c1", "d1", 0, "preserved", "h1")], [vector],
            )
            await first.reload()
            assert original._closed
            assert first.vector_store is not original
            assert await first.vector_store.search("default", vector, 1) == [("c1", 1.0)]
            await first.teardown()
            # 模拟卸载后重新安装：新组合根使用同一持久化目录。
            await second.initialize()
            assert second.vector_store is not None
            assert await second.vector_store.search("default", vector, 1) == [("c1", 1.0)]
        finally:
            await first.teardown()
            await second.teardown()


@pytest.mark.skipif(not _REAL_MILVUS, reason="需要 Milvus Lite 集成依赖")
async def test_real_close_preserves_schema_and_does_not_stop_other_database(
    tmp_path: Path,
) -> None:
    first = MilvusLiteVectorStore(str(tmp_path / "first.db"), dim=4)
    other = MilvusLiteVectorStore(str(tmp_path / "other.db"), dim=4)
    mismatched = MilvusLiteVectorStore(str(tmp_path / "first.db"), dim=7)
    reopened = MilvusLiteVectorStore(str(tmp_path / "first.db"), dim=4)
    chunk = DocumentChunk("c1", "d1", 0, "preserved", "h1")
    vector = [1.0, 0.0, 0.0, 0.0]
    try:
        await first.upsert_chunks([chunk], [vector])
        await other.upsert_chunks([chunk], [vector])
        await first.close()
        assert await other.search("default", vector, 1) == [("c1", 1.0)]
        with pytest.raises(RuntimeError, match="dimension is 4"):
            mismatched.validate_schema()
        await mismatched.close()
        assert await reopened.search("default", vector, 1) == [("c1", 1.0)]
    finally:
        for store in (first, other, mismatched, reopened):
            await store.close()


@pytest.mark.skipif(not _REAL_MILVUS, reason="需要 Milvus Lite 集成依赖")
async def test_real_store_close_allows_other_process_to_read_existing_vectors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "persistent.db"
    vector = [1.0, 0.0, 0.0, 0.0]
    for _ in range(2):
        store = MilvusLiteVectorStore(str(path), dim=4)
        try:
            await store.upsert_chunks([DocumentChunk("c1", "d1", 0, "preserved", "h1")],
                                      [vector])
            assert await store.search("default", vector, 1) == [("c1", 1.0)]
        finally:
            await store.close()

    # 父进程保持存活；只有真正释放 advisory lock，子进程才能打开同一目录。
    script = """
import asyncio
import sys
from kacore.repository.vector_store.milvus_lite import MilvusLiteVectorStore

async def main():
    store = MilvusLiteVectorStore(sys.argv[1], dim=4)
    try:
        result = await store.search('default', [1., 0., 0., 0.], 1)
        assert result == [('c1', 1.0)], result
        rows = await asyncio.to_thread(store._client.get, 'kb_chunks', ['c1'])
        assert rows[0]['text'] == 'preserved', rows
    finally:
        await store.close()

asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script, str(path), cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONPATH": "."},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
        assert process.returncode == 0, (stdout + stderr).decode(errors="replace")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
