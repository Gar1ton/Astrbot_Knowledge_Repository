"""依赖模块替换回归：保留实际服务所有者、启动原因与临时库数据。"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kacore.domain.models import DocumentChunk
from kacore.repository.vector_store.milvus_lite import MilvusLiteVectorStore
from kacore.repository.vector_store.milvus_service import MilvusLiteService

_REAL_MILVUS = all(importlib.util.find_spec(name) is not None
                   for name in ("pymilvus", "milvus_lite"))
if _REAL_MILVUS:
    importlib.import_module("pymilvus")
    importlib.import_module("milvus_lite.adapter.grpc.server")


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch):
    manager = MagicMock()
    manager.start_and_get_uri.return_value = "http://127.0.0.1:12345"
    client_class = MagicMock()
    monkeypatch.setitem(sys.modules, "milvus_lite.server_manager", SimpleNamespace(
        server_manager_instance=manager,
    ))
    monkeypatch.setitem(sys.modules, "pymilvus", SimpleNamespace(MilvusClient=client_class))
    return manager, client_class


def test_module_replacement_does_not_change_service_owner(fake_sdk, monkeypatch) -> None:
    owner, client_class = fake_sdk
    service = MilvusLiteService("owned.db")
    service.open_client()
    replacement = MagicMock()
    monkeypatch.setitem(sys.modules, "milvus_lite.server_manager", SimpleNamespace(
        server_manager_instance=replacement,
    ))
    service.open_client()
    service.release()
    assert owner.start_and_get_uri.call_count == 2
    owner.release_server.assert_called_once_with("owned.db")
    replacement.start_and_get_uri.assert_not_called()
    replacement.release_server.assert_not_called()
    assert client_class.call_args.args == ("http://127.0.0.1:12345",)


def test_client_constructor_failure_retains_owner(fake_sdk) -> None:
    manager, client_class = fake_sdk
    client_class.side_effect = RuntimeError("RPC failed")
    service = MilvusLiteService("owned.db")
    with pytest.raises(RuntimeError, match="RPC failed"):
        service.open_client()
    service.release()
    manager.release_server.assert_called_once_with("owned.db")


def test_sdk_logged_failure_is_chained_and_handler_removed(fake_sdk) -> None:
    manager, client_class = fake_sdk
    sdk_logger = logging.getLogger("milvus_lite.server_manager")
    handlers_before = list(sdk_logger.handlers)
    cause = PermissionError("another process holds the lock")

    def fail(_):
        try:
            raise cause
        except PermissionError:
            sdk_logger.exception("Failed to start MilvusLite server")
        return None

    manager.start_and_get_uri.side_effect = fail
    service = MilvusLiteService("locked.db")
    with pytest.raises(RuntimeError, match="PermissionError: another process") as error:
        service.open_client()
    assert error.value.__cause__ is cause
    assert sdk_logger.handlers == handlers_before
    client_class.assert_not_called()
    service.release()
    manager.release_server.assert_called_once_with("locked.db")


def test_other_thread_failure_is_not_attributed_to_current_open(fake_sdk) -> None:
    manager, _ = fake_sdk
    sdk_logger = logging.getLogger("milvus_lite.server_manager")

    def unrelated():
        try:
            raise PermissionError("unrelated database")
        except PermissionError:
            sdk_logger.exception("Unrelated open failed")

    def fail(_):
        worker = threading.Thread(target=unrelated)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        return None

    manager.start_and_get_uri.side_effect = fail
    with pytest.raises(RuntimeError) as error:
        MilvusLiteService("current.db").open_client()
    assert str(error.value) == "Open local milvus failed"
    assert error.value.__cause__ is None


@pytest.mark.skipif(not _REAL_MILVUS, reason="Milvus Lite SDK unavailable")
@pytest.mark.parametrize("rebuild", [False, True])
async def test_real_store_releases_original_manager_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rebuild: bool,
) -> None:
    path = str(tmp_path / "vectors.db")
    chunk = DocumentChunk("c1", "d1", 0, "preserved text", "hash")
    store = MilvusLiteVectorStore(path, dim=4)
    replacement = MagicMock()
    try:
        await store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])
        with monkeypatch.context() as swap:
            swap.setitem(sys.modules, "milvus_lite.server_manager", SimpleNamespace(
                server_manager_instance=replacement,
            ))
            if rebuild:
                await store.clear()
                await store.upsert_chunks([chunk], [[1.0, 0.0, 0.0, 0.0]])
            await store.close()
        replacement.start_and_get_uri.assert_not_called()
        replacement.release_server.assert_not_called()
        reopened = MilvusLiteVectorStore(path, dim=4)
        try:
            results = await reopened.search("default", [1.0, 0.0, 0.0, 0.0], top_k=1)
            assert results[0][0] == "c1"
            data = reopened._client.get("kb_chunks", ids=["c1"])
            assert data[0]["text"] == "preserved text"
        finally:
            await reopened.close()
    finally:
        await store.close()


@pytest.mark.skipif(not _REAL_MILVUS, reason="Milvus Lite SDK unavailable")
async def test_real_lock_failure_preserves_owner_and_reports_cause(tmp_path, monkeypatch) -> None:
    from milvus_lite.server_manager import ServerManager

    path = str(tmp_path / "locked.db")
    owner = MilvusLiteVectorStore(path, dim=4)
    contender = MilvusLiteVectorStore(path, dim=4)
    try:
        await owner.upsert_chunks(
            [DocumentChunk("c1", "d1", 0, "text", "hash")], [[1.0, 0.0, 0.0, 0.0]],
        )
        with monkeypatch.context() as swap:
            swap.setitem(sys.modules, "milvus_lite.server_manager", SimpleNamespace(
                server_manager_instance=ServerManager(),
            ))
            with pytest.raises(RuntimeError, match="DataDirLockedError"):
                await contender._ensure_client()
            await contender.close()
        assert (Path(path) / "LOCK").exists()
        results = await owner.search("default", [1.0, 0.0, 0.0, 0.0], top_k=1)
        assert results[0][0] == "c1"
    finally:
        await contender.close()
        await owner.close()
