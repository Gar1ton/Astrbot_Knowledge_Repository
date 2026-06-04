"""KnowledgeRepositoryApi 门面测试（注入内存仓储，验证委派与分类逻辑）。

用 async 工厂 `_make_api()` 在每个测试内构造并播种，避免 async fixture 在 pytest-asyncio
auto 模式下被重复收集的已知问题。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.api import KnowledgeRepositoryApi, LightRAGNotReadyError
from core.domain.models import (
    DocumentChunk,
    SourceDocument,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
)
from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.sync_targets.memory import InMemorySyncTarget


def _doc(doc_id: str, collection: str = "c", tags: list[str] | None = None) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=doc_id,
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection=collection,
        tags=list(tags or []),
    )


async def _make_api() -> KnowledgeRepositoryApi:
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "c1", ["t"]))
    await store.add_document(_doc("d2", "c2"))
    kb = InMemoryKnowledgeBaseReader({"kb1": [DocumentChunk("c0", "x", 0, "alpha", "h0")]})
    targets = {
        SyncTargetKind.R2: InMemorySyncTarget(SyncTargetKind.R2, 10, base_used_bytes=4),
        SyncTargetKind.NOTION: InMemorySyncTarget(SyncTargetKind.NOTION, 0),
    }
    return KnowledgeRepositoryApi(source_store=store, kb_reader=kb, sync_targets=targets)


async def test_list_documents_and_filter() -> None:
    api = await _make_api()
    assert len(await api.list_documents()) == 2
    assert [d.doc_id for d in await api.list_documents(collection="c1")] == ["d1"]


async def test_get_document() -> None:
    api = await _make_api()
    got = await api.get_document("d1")
    assert got is not None and got.doc_id == "d1"
    assert await api.get_document("missing") is None


async def test_classify_document_partial_update() -> None:
    api = await _make_api()
    assert await api.classify_document("d2", collection="moved") is True
    doc = await api.get_document("d2")
    assert doc is not None and doc.collection == "moved" and doc.tags == []  # tags 未传保持不变
    assert await api.classify_document("d2", tags=["x", "y"]) is True
    doc2 = await api.get_document("d2")
    assert doc2 is not None and doc2.collection == "moved" and doc2.tags == ["x", "y"]


async def test_classify_missing_returns_false() -> None:
    api = await _make_api()
    assert await api.classify_document("missing", collection="x") is False


async def test_kb_facade() -> None:
    api = await _make_api()
    assert await api.list_kb_collections() == ["kb1"]
    hits = await api.search_kb("kb1", "alpha", top_k=5)
    assert [c.chunk_id for c in hits] == ["c0"]


async def test_create_and_delete_collection() -> None:
    api = await _make_api()
    await api.create_collection("new", "desc")
    assert "new" in [c.name for c in await api.list_collections()]
    assert await api.delete_collection("new") is True
    assert await api.delete_collection("new") is False


async def test_register_document_generates_id() -> None:
    api = await _make_api()
    doc_id = await api.register_document(
        title="t.pdf",
        file_path="/p/t.pdf",
        content_type="application/pdf",
        size_bytes=10,
        content_hash="hh",
        collection="c1",
        tags=["a"],
    )
    assert doc_id
    doc = await api.get_document(doc_id)
    assert doc is not None and doc.title == "t.pdf" and doc.tags == ["a"]


async def test_delete_document() -> None:
    api = await _make_api()
    assert await api.delete_document("d1") is True
    assert await api.delete_document("d1") is False


async def test_delete_document_cleans_remote_and_managed_file(tmp_path: Path) -> None:
    managed_dir = tmp_path / "documents"
    managed_dir.mkdir()
    managed_file = managed_dir / "d1.pdf"
    managed_file.write_bytes(b"pdf")

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument("d1", "d1", str(managed_file), "application/pdf", 3, "h", "c")
    )
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "text", "ch")])
    await store.upsert_sync_record(
        SyncRecord(
            doc_id="d1",
            target=SyncTargetKind.R2,
            remote_ref="c/d1",
            status=SyncStatus.SYNCED,
        )
    )
    target = InMemorySyncTarget()
    target._objects["c/d1"] = b"pdf"
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        sync_targets={SyncTargetKind.R2: target},
        managed_documents_dir=managed_dir,
    )

    assert await api.delete_document("d1") is True
    assert not managed_file.exists()
    assert target._objects == {}
    assert await store.list_sync_records() == []


async def test_list_quota() -> None:
    api = await _make_api()
    usages = {u.target: u for u in await api.list_quota()}
    assert usages[SyncTargetKind.R2].ratio == pytest.approx(0.4)  # base 4 / limit 10
    assert usages[SyncTargetKind.NOTION].will_exceed is False


async def test_list_quota_empty_when_no_targets() -> None:
    store = InMemorySourceDocumentStore()
    api = KnowledgeRepositoryApi(
        source_store=store, kb_reader=InMemoryKnowledgeBaseReader({})
    )
    assert await api.list_quota() == []


async def test_sync_all_fans_out_to_each_target() -> None:
    class StubPipeline:
        calls = []

        async def sync(self, target, doc_ids=None):
            self.calls.append((target, doc_ids))
            return {"status": "success", "synced_count": 1, "failed_count": 0}

    pipeline = StubPipeline()
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        sync_pipeline=pipeline,  # type: ignore[arg-type]
    )
    result = await api.sync_documents("all", ["d1"])
    assert result["status"] == "success"
    assert set(result["targets"]) == {"r2", "notion"}
    assert pipeline.calls == [
        (SyncTargetKind.NOTION, ["d1"]),
        (SyncTargetKind.R2, ["d1"]),
    ]


# ── ask() ────────────────────────────────────────────────────────


async def test_ask_returns_answer_and_sources_without_llm() -> None:
    """无 LLM 时 ask() 应降级为摘要回答，仍返回 conversation_id 和 sources。"""
    api = await _make_api()
    result = await api.ask(question="alpha", collection="kb1", top_k=3)
    assert "conversation_id" in result and result["conversation_id"]
    assert "answer" in result and result["answer"]
    assert isinstance(result["sources"], list)
    assert result["sources"][0]["text"] == "alpha"


async def test_ask_with_mock_llm_calls_generate() -> None:
    """注入 mock LLMAdapter 时 ask() 应调用 generate() 并返回其输出。"""

    class MockLLM:
        called: bool = False

        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            MockLLM.called = True
            return "Mock answer [1]"

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "kb1"))
    kb = InMemoryKnowledgeBaseReader({"kb1": [DocumentChunk("c0", "d1", 0, "relevant text", "h0")]})
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=MockLLM(),  # type: ignore[arg-type]
    )
    result = await api.ask(question="relevant", collection="kb1")
    assert MockLLM.called
    assert result["answer"] == "Mock answer [1]"
    assert len(result["sources"]) == 1


async def test_ask_with_persona_enabled() -> None:
    """开启 persona_enabled 时 ask() 应从 LLMAdapter 绑定的 context 中动态提取并拼接 Persona。"""

    class MockContext:
        def get_active_persona_prompt(self) -> str:
            return "Active Persona Prompt: You are a cute cat."

    class MockLLM:
        called: bool = False
        captured_system_prompt: str = ""

        def __init__(self) -> None:
            self._context = MockContext()

        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            MockLLM.called = True
            self.captured_system_prompt = system_prompt
            return "Mock answer [1]"

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "kb1"))
    kb = InMemoryKnowledgeBaseReader({"kb1": [DocumentChunk("c0", "d1", 0, "relevant text", "h0")]})
    
    mock_llm = MockLLM()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=mock_llm,  # type: ignore[arg-type]
    )
    
    _ = await api.ask(question="relevant", collection="kb1", persona_enabled=True)
    assert MockLLM.called
    assert "Active Persona Prompt: You are a cute cat." in mock_llm.captured_system_prompt
    assert "RAG Constraints" in mock_llm.captured_system_prompt


async def test_ask_returns_empty_message_when_no_chunks() -> None:
    """知识库无内容时 ask() 应返回未找到相关内容的提示。"""
    store = InMemorySourceDocumentStore()
    kb = InMemoryKnowledgeBaseReader({})
    api = KnowledgeRepositoryApi(source_store=store, kb_reader=kb)
    result = await api.ask(question="anything")
    assert result["sources"] == []
    assert result["answer"]  # 有内容（降级提示）


async def test_ask_uses_provided_conversation_id() -> None:
    api = await _make_api()
    result = await api.ask(question="alpha", collection="kb1", conversation_id="existing-id")
    assert result["conversation_id"] == "existing-id"


async def test_default_ask_never_calls_lightrag() -> None:
    class FailingRegistry:
        async def query(self, *args, **kwargs):
            raise AssertionError("default Ask must not call LightRAG")

    api = await _make_api()
    api._lightrag_registry = FailingRegistry()  # type: ignore[assignment]
    result = await api.ask(question="alpha", collection="kb1")
    assert result["requested_retrieval_mode"] == "default"
    assert "lightrag" not in result["retrieval_engines"]


async def test_high_precision_uses_context_and_one_outer_llm_call(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore
    from core.pipelines.retrieval_orchestrator import RetrievalOutcome

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return collection == "papers"

    class Orchestrator:
        async def retrieve_with_outcome(self, collection: str, query: str, top_k: int):
            return RetrievalOutcome(
                [DocumentChunk("c1", "d1", 0, "chunk evidence", "h1")],
                ["milvus", "sqlite_lexical"],
            )

        async def retrieve_lightrag_context(self, collection: str, query: str) -> str:
            return "graph context"

    class LLM:
        calls = 0

        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            self.calls += 1
            assert "graph context" in prompt
            assert "chunk evidence" in prompt
            return "answer"

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    llm = LLM()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        retrieval_orchestrator=Orchestrator(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
        llm_adapter=llm,  # type: ignore[arg-type]
    )

    result = await api.ask(
        question="q",
        collection="papers",
        retrieval_mode="high_precision",
    )

    assert llm.calls == 1
    assert result["actual_retrieval_mode"] == "milvus_lightrag"
    assert result["retrieval_engines"] == ["milvus", "sqlite_lexical", "lightrag"]


async def test_high_precision_requires_ready_lightrag() -> None:
    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return False

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
    )
    with pytest.raises(LightRAGNotReadyError, match="workspace"):
        await api.ask(question="q", collection="papers", retrieval_mode="high_precision")


async def test_lightrag_build_resets_incompatible_workspace(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore
    from core.lightrag_core import BuildJob

    calls: list[str] = []

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

        async def reset_workspace(self, collection: str) -> None:
            calls.append(f"reset:{collection}")

        async def insert_document(self, collection: str, doc_id: str, text: str) -> None:
            calls.append(f"insert:{collection}:{doc_id}")

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "old-fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="new-fp",
    )
    api._graph_build_jobs["job"] = BuildJob(job_id="job", collection="papers")

    await api._run_lightrag_build_job("job")

    assert calls == ["reset:papers", "insert:papers:d1"]
    assert api._graph_build_jobs["job"].status == "success"
    assert compatibility.is_lightrag_compatible("papers", "new-fp")


async def test_graph_stats_skip_pending_lightrag_workspace(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore

    class Registry:
        exports = 0

        def existing_collections(self) -> list[str]:
            return ["papers"]

        def has_workspace(self, collection: str) -> bool:
            return True

        async def export_graph(self, collection: str) -> dict:
            self.exports += 1
            return {"nodes": [{"id": "n1"}], "edges": []}

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "pending")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    registry = Registry()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=registry,  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    assert await api.get_graph_stats() == {
        "entities_count": 0,
        "relations_count": 0,
        "collections_covered": 0,
    }
    assert registry.exports == 0


async def test_lightrag_build_only_indexes_pending_docs_when_workspace_is_compatible(
    tmp_path: Path,
) -> None:
    from core.index_compatibility import IndexCompatibilityStore
    from core.lightrag_core import BuildJob

    inserted: list[str] = []

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

        async def insert_document(self, collection: str, doc_id: str, text: str) -> None:
            inserted.append(doc_id)

    store = InMemorySourceDocumentStore()
    for doc_id, status in (("d1", "indexed"), ("d2", "pending")):
        await store.add_document(_doc(doc_id, "papers"))
        await store.replace_chunks(
            doc_id, [DocumentChunk(f"c-{doc_id}", doc_id, 0, "evidence", f"h-{doc_id}")]
        )
        await store.set_lightrag_index_status(doc_id, "papers", status)
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )
    api._graph_build_jobs["job"] = BuildJob(job_id="job", collection="papers")

    await api._run_lightrag_build_job("job")

    assert inserted == ["d2"]
    assert api._graph_build_jobs["job"].total_docs == 1
    assert api._graph_build_jobs["job"].status == "success"


async def test_high_precision_can_answer_with_only_lightrag_context(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore
    from core.pipelines.retrieval_orchestrator import RetrievalOutcome

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

    class Orchestrator:
        async def retrieve_with_outcome(self, collection: str, query: str, top_k: int):
            return RetrievalOutcome([], [])

        async def retrieve_lightrag_context(self, collection: str, query: str) -> str:
            return "only graph context"

    class LLM:
        calls = 0

        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            self.calls += 1
            assert "only graph context" in prompt
            return "answer"

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    llm = LLM()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        retrieval_orchestrator=Orchestrator(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
        llm_adapter=llm,  # type: ignore[arg-type]
    )

    result = await api.ask(question="q", collection="papers", retrieval_mode="high_precision")

    assert result["answer"] == "answer"
    assert result["sources"] == []
    assert result["actual_retrieval_mode"] == "lightrag"
    assert llm.calls == 1


async def test_embedding_change_marks_docs_pending_and_rebuilds_incompatible_milvus(
    tmp_path: Path,
) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    class CountingVectorStore(InMemoryVectorStore):
        clear_calls = 0

        async def clear(self) -> None:
            self.clear_calls += 1
            await super().clear()

        async def delete_chunks(self, chunk_ids: list[str]) -> None:
            raise AssertionError("incompatible Milvus must not receive lifecycle writes")

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    vector_store = CountingVectorStore()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=vector_store,
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    update = await api.update_config_value("embedding", "model", "replacement-model")
    assert await api.classify_document("d1", collection="moved") is True

    assert update["rebuild_required"] is True
    assert [doc.doc_id for doc in await store.list_pending_reindex_documents()] == ["d1"]
    assert (await store.get_lightrag_index_status("d1"))["status"] == "pending"
    assert not compatibility.is_milvus_compatible("fp")

    rebuilt = await api.rebuild_index_pending()

    assert rebuilt == {"rebuilt_docs": 1, "rebuilt_chunks": 1}
    assert vector_store.clear_calls == 1
    assert await store.list_pending_reindex_documents() == []
    assert compatibility.is_milvus_compatible("fp")

    token_update = await api.update_config_value("embedding", "max_token_size", 4096)
    assert token_update["restart_required"] is True
    assert token_update["rebuild_required"] is False
    assert compatibility.is_milvus_compatible("fp")


async def test_vector_db_sync_and_rebuild(tmp_path: Path) -> None:
    """测试在 milvus 模式下
    rebuild_vector_store、delete_document 和 delete_collection 的联动一致性。
    """
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc_id = "test_doc"
    await store.add_document(_doc(doc_id, "col1"))
    chunks = [
        DocumentChunk("chunk_A", doc_id, 0, "text A", "hashA"),
        DocumentChunk("chunk_B", doc_id, 1, "text B", "hashB"),
    ]
    await store.replace_chunks(doc_id, chunks)

    # 1. 构造配置与内存 Mock 组件
    config = Config(raw={
        "vector_db": {
            "backend": "milvus",
            "embedding_provider": "local",
        }
    })
    v_store = InMemoryVectorStore()
    v_store.set_doc_collection_mapping(doc_id, "col1")
    embedding = MockEmbeddingProvider(dimension=4)
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")

    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=config,
        vector_store=v_store,
        embedding_provider=embedding,
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    # 2. 测试全量 rebuild
    res = await api.rebuild_vector_store()
    assert res["rebuilt_chunks"] == 2
    # 验证内存向量库中确实有了这 2 个分块
    assert "chunk_A" in v_store._data
    assert "chunk_B" in v_store._data

    # 3. 测试删除文档时的联动删除
    deleted = await api.delete_document(doc_id)
    assert deleted is True
    # 验证内存向量库中的分块已被清空
    assert "chunk_A" not in v_store._data
    assert "chunk_B" not in v_store._data

    # 4. 测试删除集合时的联动删除
    # 由于 rebuild_vector_store 会调用 clear() 清空包括测试辅助映射在内的所有数据，在此重新注册
    v_store.set_doc_collection_mapping(doc_id, "col1")
    # 重新 upsert 分块
    await v_store.upsert_chunks(chunks, [[0.1] * 4, [0.2] * 4])
    assert "chunk_A" in v_store._data
    await api.delete_collection("col1")
    assert "chunk_A" not in v_store._data
