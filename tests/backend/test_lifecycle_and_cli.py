"""单元与集成测试：PluginInitializer 生命周期、后台任务调度，与 CLI/EventHandler 事件分发。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import fitz  # type: ignore[import-untyped]
import pytest

from core.main import KnowledgeRepositoryPlugin
from core.migration_runner import run_migrations
from core.plugin_initializer import PluginInitializer, _load_plugin_web_build_app


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mock_context() -> object:
    return object()


@pytest.fixture
def raw_config() -> dict[str, Any]:
    return {
        "source_store": {
            "db_filename": "test_kr.db",
            "default_collection": "default",
            "ocr_enabled": False,
        },
        "r2_sync": {
            "enabled": True,
            "account_id": "test-acc",
            "access_key_id": "test-key",
            "secret_access_key": "test-sec",
            "bucket": "test-bucket",
            "backup_interval_sec": 60,
        },
        "notion_sync": {
            "enabled": True,
            "parent_page_id": "parent-page",
            "database_title": "KR Test",
            "rate_limit_rps": 100,
        },
        # Existing installs may explicitly keep AstrBot retrieval; avoid loading a local
        # embedding model in lifecycle tests that do not exercise Milvus.
        "vector_db": {"backend": "astr"},
    }


async def test_plugin_initializer_lifecycle(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    # 1) 实例化 PluginInitializer
    initializer = PluginInitializer(mock_context, raw_config, temp_dir)
    assert initializer.source_store is None
    assert initializer._backup_task is None

    # 2) 初始化
    await initializer.initialize()

    assert initializer.source_store is not None
    assert initializer.kb_reader is not None
    assert initializer.api is not None
    assert initializer.ingest_manager is not None
    assert initializer.category_manager is not None
    assert initializer.quota_manager is not None
    assert initializer.sync_pipeline is not None
    assert initializer._backup_task is not None
    assert not initializer._backup_task.done()

    # 3) 销毁
    await initializer.teardown()
    assert initializer._backup_task is None


def test_initializer_uses_plugin_owned_migration_runner() -> None:
    assert run_migrations.__module__ == "core.migration_runner"


def test_web_server_loader_ignores_conflicting_top_level_web_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflicting_web = ModuleType("web")
    conflicting_server = ModuleType("web.server")
    conflicting_server.build_app = object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "web", conflicting_web)
    monkeypatch.setitem(sys.modules, "web.server", conflicting_server)

    build_app = _load_plugin_web_build_app()

    assert build_app.__module__ == "_astrbot_plugin_knowledge_repository_web_server"


async def test_plugin_initializer_lifecycle_periodic_disabled(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    # 禁用 R2 或周期备份
    config_disabled = dict(raw_config)
    config_disabled["r2_sync"] = dict(raw_config["r2_sync"])
    config_disabled["r2_sync"]["enabled"] = False

    initializer = PluginInitializer(mock_context, config_disabled, temp_dir)
    await initializer.initialize()
    assert initializer._backup_task is None
    await initializer.teardown()


async def test_initializer_creates_default_collection_without_overwriting_it(
    temp_dir: Path, mock_context: object
) -> None:
    from core.domain.models import Collection

    config = {"vector_db": {"backend": "astr"}}
    first = PluginInitializer(mock_context, config, temp_dir)
    await first.initialize()
    assert first.source_store is not None
    await first.source_store.upsert_collection(
        Collection(name="default", description="User description")
    )
    await first.teardown()

    second = PluginInitializer(mock_context, config, temp_dir)
    await second.initialize()
    assert second.source_store is not None
    collections = await second.source_store.list_collections()
    assert [(item.name, item.description) for item in collections] == [
        ("default", "User description")
    ]
    await second.teardown()


async def test_initializer_passes_probed_dimension_to_milvus_and_lightrag(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    captured: dict[str, int] = {}

    class Provider:
        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * 7

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 7 for _ in texts]

    class Milvus:
        def __init__(self, *, db_path: str, dim: int) -> None:
            captured["milvus"] = dim

        def validate_schema(self) -> None:
            pass

        async def close(self) -> None:
            pass

    class Registry:
        def __init__(self, **kwargs: Any) -> None:
            captured["lightrag"] = kwargs["embedding_dim"]

        def existing_collections(self) -> list[str]:
            return []

        async def close(self) -> None:
            pass

    config = {
        **raw_config,
        "vector_db": {"backend": "milvus"},
        "graph": {"enabled": True},
    }
    with (
        patch(
            "core.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
            return_value=Provider(),
        ),
        patch("core.repository.vector_store.milvus_lite.MilvusLiteVectorStore", Milvus),
        patch("core.lightrag_core.LightRAGCoreRegistry", Registry),
        patch("core.plugin_initializer._module_available", return_value=True),
    ):
        initializer = PluginInitializer(mock_context, config, temp_dir)
        await initializer.initialize()
        assert initializer.embedding_dimension == 7
        assert initializer.config.runtime_embedding_dimension == 7
        assert captured == {"milvus": 7, "lightrag": 7}
        await initializer.teardown()


async def test_default_initializer_starts_without_optional_feature_packages(
    temp_dir: Path, mock_context: object
) -> None:
    blocked_modules = {
        "boto3": None,
        "botocore": None,
        "lightrag": None,
        "pymilvus": None,
        "sentence_transformers": None,
    }
    with patch.dict(sys.modules, blocked_modules):
        initializer = PluginInitializer(mock_context, {}, temp_dir)
        await initializer.initialize()

        assert initializer.api is not None
        assert initializer.source_store is not None
        assert initializer.vector_store is None
        assert initializer.lightrag_registry is None
        diagnostics = initializer.config.get_diagnostics()
        # 可选特性缺包仍给出可执行指引：local embedding 指向 requirements-additional.txt；
        # Milvus Lite 自 v0.24.6 起为必装依赖，缺失时改提示 requirements.txt + AstrBot 兜底。
        assert any("requirements-additional.txt" in item for item in diagnostics)
        assert any(
            "Milvus Lite is a required dependency from requirements.txt" in item
            for item in diagnostics
        )
        await initializer.teardown()


async def test_initializer_probe_failure_disables_embedding_indexes(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    class Provider:
        async def embed_query(self, text: str) -> list[float]:
            raise RuntimeError("probe failed")

    config = {
        **raw_config,
        "vector_db": {"backend": "milvus"},
        "graph": {"enabled": True},
    }
    with (
        patch(
            "core.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
            return_value=Provider(),
        ),
        patch("core.plugin_initializer._module_available", return_value=True),
    ):
        initializer = PluginInitializer(mock_context, config, temp_dir)
        await initializer.initialize()
        assert initializer.embedding_provider is None
        assert initializer.vector_store is None
        assert initializer.lightrag_registry is None
        assert any(
            "Embedding dimension probe failed" in item
            for item in initializer.config.get_diagnostics()
        )
        await initializer.teardown()


async def test_fresh_install_uploads_and_lexically_retrieves_when_embedding_probe_fails(
    temp_dir: Path, mock_context: object
) -> None:
    class Provider:
        async def embed_query(self, text: str) -> list[float]:
            raise RuntimeError("offline first startup")

    pdf_path = temp_dir / "fresh-install.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox(
        fitz.Rect(50, 50, 550, 750),
        "Fresh install lexical baseline remains available without embeddings.",
    )
    pdf.save(pdf_path)
    pdf.close()

    with (
        patch(
            "core.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
            return_value=Provider(),
        ),
        patch("core.plugin_initializer._module_available", return_value=True),
    ):
        initializer = PluginInitializer(mock_context, {}, temp_dir)
        await initializer.initialize()

        assert initializer.source_store is not None
        assert initializer.api is not None
        assert initializer.retrieval_orchestrator is not None
        assert [item.name for item in await initializer.source_store.list_collections()] == [
            "default"
        ]

        doc_id = await initializer.api.register_document(
            title=pdf_path.name,
            file_path=str(pdf_path),
            content_type="application/pdf",
            size_bytes=pdf_path.stat().st_size,
            content_hash="",
            collection="default",
        )
        stored = await initializer.source_store.get_document(doc_id)
        assert stored is not None
        assert Path(stored.file_path) == temp_dir / "library" / doc_id / "original.pdf"
        assert Path(stored.file_path).exists()

        result = await initializer.retrieval_orchestrator.retrieve_with_outcome(
            "default", "lexical baseline", 5
        )
        assert [chunk.doc_id for chunk in result.chunks] == [doc_id]
        assert "sqlite_lexical" in result.engines
        assert result.fallback_reason == "milvus_unavailable"
        await initializer.teardown()


async def test_initializer_keeps_mismatched_milvus_available_for_manual_rebuild(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    from core.repository.vector_store.milvus_lite import MilvusSchemaMismatchError

    class Provider:
        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * 7

    class Milvus:
        def __init__(self, *, db_path: str, dim: int) -> None:
            self.dim = dim

        def validate_schema(self) -> None:
            raise MilvusSchemaMismatchError("rebuild required")

        async def close(self) -> None:
            pass

    config = {
        **raw_config,
        "vector_db": {"backend": "milvus"},
        "graph": {"enabled": False},
    }
    with (
        patch(
            "core.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
            return_value=Provider(),
        ),
        patch("core.repository.vector_store.milvus_lite.MilvusLiteVectorStore", Milvus),
        patch("core.plugin_initializer._module_available", return_value=True),
    ):
        initializer = PluginInitializer(mock_context, config, temp_dir)
        await initializer.initialize()

        assert isinstance(initializer.vector_store, Milvus)
        assert initializer.embedding_fingerprint is not None
        assert initializer.index_compatibility is not None
        assert not initializer.index_compatibility.is_milvus_compatible(
            initializer.embedding_fingerprint
        )
        assert "rebuild required" in initializer.index_compatibility.reason("milvus")
        await initializer.teardown()


async def test_initializer_marks_recreated_empty_milvus_incompatible_when_docs_exist(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    from core.domain.models import Collection, SourceDocument

    seed_config = {
        **raw_config,
        "vector_db": {"backend": "astr"},
        "graph": {"enabled": False},
    }
    seed = PluginInitializer(mock_context, seed_config, temp_dir)
    await seed.initialize()
    assert seed.source_store is not None
    await seed.source_store.upsert_collection(Collection(name="papers"))
    await seed.source_store.add_document(
        SourceDocument("d1", "Doc", "/d1.pdf", "application/pdf", 1, "h", "papers")
    )
    await seed.teardown()

    class Provider:
        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * 7

    class Milvus:
        created_collection = True

        def __init__(self, *, db_path: str, dim: int) -> None:
            pass

        def validate_schema(self) -> None:
            pass

        async def close(self) -> None:
            pass

    config = {
        **raw_config,
        "vector_db": {"backend": "milvus"},
        "graph": {"enabled": False},
    }
    with (
        patch(
            "core.repository.embedding.factory.EmbeddingProviderFactory.create_provider",
            return_value=Provider(),
        ),
        patch("core.repository.vector_store.milvus_lite.MilvusLiteVectorStore", Milvus),
        patch("core.plugin_initializer._module_available", return_value=True),
    ):
        initializer = PluginInitializer(mock_context, config, temp_dir)
        await initializer.initialize()

        assert initializer.embedding_fingerprint is not None
        assert initializer.index_compatibility is not None
        assert not initializer.index_compatibility.is_milvus_compatible(
            initializer.embedding_fingerprint
        )
        assert "recreated" in initializer.index_compatibility.reason("milvus")
        assert initializer.source_store is not None
        assert [
            doc.doc_id
            for doc in await initializer.source_store.list_pending_reindex_documents()
        ] == ["d1"]
        await initializer.teardown()


async def test_plugin_shell_lifecycle(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    # 1) 实例化并启动薄壳
    plugin = KnowledgeRepositoryPlugin(mock_context, raw_config)
    await plugin.initialize(temp_dir)

    assert plugin._initializer is not None
    assert plugin._handler is not None
    assert plugin._initializer.api is not None

    # 2) /ka help 与 /ka status（运营控制面）
    res_help = await plugin.on_ka_help()
    assert "/ka help" in res_help and "/ka r2" in res_help
    res_status = await plugin.on_ka_status()
    assert "KA 服务框架" in res_status and "agent" in res_status

    # 3) 内容管理已下沉 WebUI：经 api 直接 seed 一篇真实 PDF 供后续 hook 测试
    pdf_path = temp_dir / "test_doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 750), "Hello world text segment for testing.")
    doc.save(pdf_path)
    doc.close()

    await plugin._initializer.api.create_collection("papers", "academic")
    doc_id = await plugin._initializer.api.register_document(
        title=pdf_path.name,
        file_path=str(pdf_path),
        content_type="application/pdf",
        size_bytes=pdf_path.stat().st_size,
        content_hash="",
        collection="papers",
    )

    # 4) /ka agent on → 开关开启且持久化
    res_agent_on = await plugin.on_ka_agent("on")
    assert "开启" in res_agent_on
    assert plugin._initializer.agent_enabled is True
    assert (temp_dir / "runtime_config.json").exists()

    from core.domain.models import DocumentChunk

    mock_chunk = DocumentChunk(
        chunk_id="test-chunk-1",
        doc_id=doc_id,
        ordinal=0,
        text="Hello world text segment for testing.",
        content_hash="mock-hash",
    )

    # 4a) inject 模式：on_llm_request 向 req.system_prompt 注入知识库上下文
    mock_event_on = MagicMock()
    mock_event_on.message_str = "testing"

    class _MockReq:
        system_prompt = "You are a bot."

    mock_req = _MockReq()

    with patch.object(
        plugin._initializer.retrieval_orchestrator, "retrieve", return_value=[mock_chunk]
    ) as mock_retrieve:
        await plugin._handler.on_llm_request(mock_event_on, mock_req)
        assert mock_retrieve.await_count == 2
        assert {
            awaited.kwargs["collection"] for awaited in mock_retrieve.await_args_list
        } == {"default", "papers"}
        assert "Knowledge Base Context" in mock_req.system_prompt
        assert "testing" in mock_req.system_prompt

    # 4b) /ka agent off → on_llm_request 完全旁路，不注入、不检索（query_agent 已删，无 on_message）
    res_agent_off = await plugin.on_ka_agent("off")
    assert "关闭" in res_agent_off
    assert plugin._initializer.agent_enabled is False

    mock_event_off = MagicMock()
    mock_event_off.message_str = "testing"

    class _MockReqOff:
        system_prompt = "You are a bot."

    mock_req_off = _MockReqOff()
    with patch.object(
        plugin._initializer.retrieval_orchestrator, "retrieve", return_value=[mock_chunk]
    ) as mock_retrieve_off:
        await plugin._handler.on_llm_request(mock_event_off, mock_req_off)
        assert mock_retrieve_off.await_count == 0
        assert mock_req_off.system_prompt == "You are a bot."

    # 5) /ka r2 push（增量上传，mock boto3 避免真实网络）
    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = []
    mock_s3.get_paginator.return_value = mock_paginator
    boto3_module = ModuleType("boto3")
    boto3_module.client = MagicMock(return_value=mock_s3)  # type: ignore[attr-defined]
    botocore_module = ModuleType("botocore")
    config_module = ModuleType("botocore.config")

    class _BotoConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    config_module.Config = _BotoConfig  # type: ignore[attr-defined]
    botocore_module.config = config_module  # type: ignore[attr-defined]
    with patch.dict(
        sys.modules,
        {
            "boto3": boto3_module,
            "botocore": botocore_module,
            "botocore.config": config_module,
        },
    ):
        res_push = await plugin.on_ka_r2("push")
        assert res_push.startswith("R2 增量上传")
        assert plugin._initializer.r2_backup_manager is not None
        await plugin._initializer.r2_backup_manager.wait_current()

        # 6) /ka r2 force push 需二次确认：首发提示，窗口内二次执行
        res_warn = await plugin.on_ka_r2("force push")
        assert "再次发送" in res_warn
        res_force = await plugin.on_ka_r2("force push")
        assert res_force.startswith("R2 强制全量上传")
        await plugin._initializer.r2_backup_manager.wait_current()

    # 7) 销毁薄壳
    await plugin._initializer.api.delete_document(doc_id)
    await plugin.terminate()


async def test_ka_toggles_persist_across_reinit(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    """agent/research/persona 开关写入 runtime_config.json，重建 initializer 后保留。"""
    first = PluginInitializer(mock_context, raw_config, temp_dir)
    await first.initialize()
    first.set_toggle("agent", True)
    first.set_toggle("research", True)
    first.set_toggle("persona", True)
    await first.teardown()

    assert (temp_dir / "runtime_config.json").exists()

    second = PluginInitializer(mock_context, raw_config, temp_dir)
    await second.initialize()
    assert second.agent_enabled is True
    assert second.research_enabled is True
    assert second.persona_enabled is True
    await second.teardown()


async def test_ka_r2_force_pull_confirmation_and_auto_restart(
    temp_dir: Path, mock_context: object, raw_config: dict[str, Any]
) -> None:
    """force pull：首发待确认；确认后恢复并自动触发 restart_plugin。"""
    plugin = KnowledgeRepositoryPlugin(mock_context, raw_config)
    await plugin.initialize(temp_dir)
    assert plugin._initializer is not None and plugin._initializer.api is not None

    with (
        patch.object(
            plugin._initializer.api,
            "restore_from_backup",
            return_value={"status": "success"},
        ),
        patch.object(
            plugin._initializer.api, "restart_plugin", return_value={"status": "restarting"}
        ) as mock_restart,
    ):
        warn = await plugin.on_ka_r2("force pull")
        assert "再次发送" in warn
        done = await plugin.on_ka_r2("force pull")
        assert "自动重启" in done
        mock_restart.assert_awaited_once()

    await plugin.terminate()
