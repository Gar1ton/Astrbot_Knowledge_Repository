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
        assert sum("requirements-additional.txt" in item for item in diagnostics) >= 2
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
        assert Path(stored.file_path) == temp_dir / "documents" / f"{doc_id}.pdf"
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

    # 2) 测试命令行 /kr add 文件不存在边界
    res = await plugin.on_add("missing_file.pdf")
    assert "Error: File not found" in res

    # 3) 创建一个真实的测试 PDF 并保存
    pdf_path = temp_dir / "test_doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 750), "Hello world text segment for testing.")
    doc.save(pdf_path)
    doc.close()

    # 4) 测试 /kr collection create
    res_col = await plugin.on_collection("create", name="papers", description="academic")
    assert "Collection 'papers' created/updated." in res_col

    # 5) 测试 /kr collection list
    res_list = await plugin.on_collection("list")
    assert "papers" in res_list

    # 6) 测试 /kr add
    res_ingest = await plugin.on_add(str(pdf_path), collection="papers", tags=["tag1", "tag2"])
    assert "Success: Document ingested with ID" in res_ingest
    doc_id = res_ingest.split(":")[-1].strip()

    # 7) 测试 /kr tag show
    res_show = await plugin.on_tag("show", doc_id)
    assert "test_doc.pdf" in res_show
    assert "tag1" in res_show
    assert "tag2" in res_show

    # 8) 测试 /kr tag set
    res_set = await plugin.on_tag("set", doc_id, "new_tag")
    assert "Tags set successfully" in res_set
    res_show2 = await plugin.on_tag("show", doc_id)
    assert "new_tag" in res_show2

    # 9) 测试 /kr quota
    # 建立 mock boto3.client 避免真实网络请求
    mock_s3 = MagicMock()
    # 模拟 check_quota 中的 list_objects_v2 or similar
    mock_s3.list_objects_v2.return_value = {"Contents": []}
    with patch("boto3.client", return_value=mock_s3):
        res_quota = await plugin.on_quota()
        assert "Limit" in res_quota

    # 10) 测试 /kr sync r2
    with patch("boto3.client", return_value=mock_s3):
        res_sync = await plugin.on_sync_r2()
        assert "Sync successful" in res_sync or "Sync BLOCKED" in res_sync

    # 10.5) 测试 /kr graph build
    res_graph_build = await plugin.on_graph_build("papers")
    assert "estimate only" in res_graph_build
    assert "no LLM call was started" in res_graph_build

    # graph query requires graph.enabled and a configured LightRAG Core registry
    res_graph_query = await plugin.on_graph_query("Transformer")
    assert "Error: Graph query failed" in res_graph_query

    # 10.6) 测试 /kr notion init 与 /kr sync notion --pull
    res_notion_init = await plugin.on_notion_init()
    assert "Notion database created" in res_notion_init
    assert (temp_dir / "runtime_config.json").exists()

    res_notion_pull = await plugin.on_sync_notion_pull()
    assert "Notion Pull successful" in res_notion_pull

    # 11) 测试 /kr agent on 状态下普通消息 Hook 自动检索文献并注入 (Phase 6 / Phase 7)
    await plugin.on_agent("on")
    assert plugin._initializer.agent_enabled is True

    from core.domain.models import DocumentChunk

    mock_chunk = DocumentChunk(
        chunk_id="test-chunk-1",
        doc_id=doc_id,
        ordinal=0,
        text="Hello world text segment for testing.",
        content_hash="mock-hash",
    )

    # 11a) inject 模式：on_llm_request 向 req.system_prompt 注入知识库上下文
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

    # 11b) query_agent 模式：on_message 直接返回知识库答案字符串
    plugin._initializer.config.raw.setdefault("ask", {})["conversation_enhancement_mode"] = (
        "query_agent"
    )
    assert (
        plugin._initializer.config.get_ask_agent_config().conversation_enhancement_mode
        == "query_agent"
    )

    mock_event_query = MagicMock()
    mock_event_query.message_str = "testing"
    mock_event_query.session_id = "test-session-123"

    mock_ask_result = {
        "conversation_id": "event-test-session-123",
        "answer": "This is the generated academic answer from standalone ask agent.",
        "sources": [],
    }
    with patch.object(plugin._initializer.api, "ask", return_value=mock_ask_result) as mock_ask:
        answer = await plugin._handler.on_message(mock_event_query)
        assert answer == "This is the generated academic answer from standalone ask agent."
        mock_ask.assert_called_once_with(
            question="testing",
            collection=None,
            top_k=5,
            conversation_id="event-test-session-123",
            persona_enabled=False,
            retrieval_mode="default",
        )

    # 11c) agent off 状态下完全旁路，on_message 返回 None
    await plugin.on_agent("off")
    assert plugin._initializer.agent_enabled is False

    mock_event_off = MagicMock()
    mock_event_off.message_str = "testing"
    result_off = await plugin._handler.on_message(mock_event_off)
    assert result_off is None

    # 11.1) 删除文档并删除集合
    assert plugin._initializer is not None
    assert plugin._initializer.api is not None
    await plugin._initializer.api.delete_document(doc_id)
    res_del = await plugin.on_collection("delete", name="papers")
    assert "deleted" in res_del

    # 12) 销毁薄壳
    await plugin.terminate()
