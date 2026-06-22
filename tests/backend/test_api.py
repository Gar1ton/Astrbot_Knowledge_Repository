"""KnowledgeRepositoryApi 门面测试（注入内存仓储，验证委派与分类逻辑）。

用 async 工厂 `_make_api()` 在每个测试内构造并播种，避免 async fixture 在 pytest-asyncio
auto 模式下被重复收集的已知问题。
"""
from __future__ import annotations

import asyncio
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


async def test_list_document_chunks_rebuilds_legacy_preview_chunks() -> None:
    store = InMemorySourceDocumentStore()
    doc = _doc("doc-preview", "papers")
    await store.add_document(doc)
    await store.replace_chunks(
        "doc-preview",
        [DocumentChunk("doc-preview-0001", "doc-preview", 0, "legacy text", "old")],
    )

    class FakeIngestManager:
        calls = 0

        @staticmethod
        def chunk_needs_rebuild(
            document_id: str,
            chunks: list[DocumentChunk],
            local_meta: dict | None = None,
        ) -> bool:
            del document_id, local_meta
            return any(
                chunk.metadata.get("chunk_schema") != "clean_md_structural_v3"
                for chunk in chunks
            )

        async def rebuild_document_chunks_from_artifact(self, document_id: str) -> int:
            self.calls += 1
            rebuilt = [
                DocumentChunk(
                    f"{document_id}_c0000",
                    document_id,
                    0,
                    "current structural chunk",
                    "new",
                    metadata={
                        "chunk_schema": "clean_md_structural_v3",
                        "start_char": 0,
                        "end_char": 24,
                    },
                )
            ]
            await store.replace_chunks(document_id, rebuilt)
            current = await store.get_document(document_id)
            assert current is not None
            current.needs_reindex = True
            await store.update_document(current)
            return len(rebuilt)

    ingest = FakeIngestManager()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        ingest_manager=ingest,  # type: ignore[arg-type]
    )

    chunks = await api.list_document_chunks("doc-preview")
    context = await api.get_chunk_context("doc-preview", "doc-preview_c0000")
    rebuilt_doc = await store.get_document("doc-preview")

    assert ingest.calls == 1
    assert [chunk.chunk_id for chunk in chunks] == ["doc-preview_c0000"]
    assert chunks[0].metadata["chunk_schema"] == "clean_md_structural_v3"
    assert context["matched_chunk_id"] == "doc-preview_c0000"
    assert rebuilt_doc is not None and rebuilt_doc.needs_reindex is True


async def test_document_and_collection_notes_are_zotero_shaped() -> None:
    api = await _make_api()
    doc_note = await api.create_document_note("d1", "hello\nworld")
    assert doc_note is not None
    assert doc_note["scope_type"] == "document"
    assert doc_note["doc_id"] == "d1"
    assert doc_note["content"] == "hello\nworld"
    assert doc_note["raw_zotero_json"]["itemType"] == "note"
    assert doc_note["raw_zotero_json"]["note"] == "<p>hello<br/>world</p>"
    assert [n["id"] for n in await api.list_document_notes("d1") or []] == [doc_note["id"]]

    await api.create_collection("papers")
    collection_note = await api.create_collection_note("papers", "collection note")
    assert collection_note is not None
    assert collection_note["scope_type"] == "collection"
    assert collection_note["collection_name"] == "papers"
    assert collection_note["raw_zotero_json"]["itemType"] == "note"


async def test_chat_lock_and_console_scope_state() -> None:
    api = await _make_api()
    await api._source_store.add_chat_message("conv", "user", "q")  # type: ignore[attr-defined]
    await api._source_store.add_chat_message("conv", "assistant", "a")  # type: ignore[attr-defined]
    locked = await api.set_chat_message_locked("conv", 1, True)
    assert locked is not None and locked["locked"] is True
    await api.clear_chat_history("conv", preserve_locked=True)
    messages = await api.get_chat_history("conv")
    assert [(m["role"], m["locked"]) for m in messages] == [("assistant", True)]

    state = await api.upsert_console_scope_state(
        "collection",
        "papers",
        selected_collection="papers",
        selected_doc_id="d1",
        note_doc_id="d1",
        payload={"right": "notes"},
    )
    assert state["selected_doc_id"] == "d1"
    assert await api.get_console_scope_state("collection", "papers") == state


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

        async def sync(self, target, doc_ids=None, force=False):
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
        async def retrieve_with_outcome(self, collection, query, top_k, scope=None):
            return RetrievalOutcome(
                [DocumentChunk("c1", "d1", 0, "chunk evidence", "h1")],
                ["milvus", "sqlite_lexical"],
            )

        async def retrieve_lightrag_context(self, collection, query, scope=None) -> str:
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

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks: list[str] | None = None,
            progress_callback=None,
        ) -> None:
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

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks: list[str] | None = None,
            progress_callback=None,
        ) -> None:
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
        async def retrieve_with_outcome(self, collection, query, top_k, scope=None):
            return RetrievalOutcome([], [])

        async def retrieve_lightrag_context(self, collection, query, scope=None) -> str:
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

    assert rebuilt == {"rebuilt_docs": 1, "rebuilt_chunks": 1, "failed_docs": 0, "errors": []}
    assert vector_store.clear_calls == 1
    assert await store.list_pending_reindex_documents() == []
    assert compatibility.is_milvus_compatible("fp")


async def test_rerank_config_update_hot_swaps_deep_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import Config
    from core.repository.reranker.noop import NoopReranker

    class HotSwapProbe:
        def __init__(self) -> None:
            self.calls = []

        def update_reranker(self, reranker, rerank_config) -> None:
            self.calls.append((reranker, rerank_config))

        @property
        def reranker_status(self) -> dict:
            if not self.calls:
                return NoopReranker().status
            return self.calls[-1][0].status

    monkeypatch.setattr("core.repository.reranker._has_sentence_transformers", lambda: False)
    probe = HotSwapProbe()
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"rerank": {"provider": "noop"}}),
        deep_thinking_orchestrator=probe,  # type: ignore[arg-type]
    )

    result = await api.update_config_value("rerank", "provider", "cross_encoder")

    assert result["restart_required"] is False
    assert result["rebuild_required"] is False
    assert len(probe.calls) == 1
    reranker, rerank_cfg = probe.calls[0]
    assert isinstance(reranker, NoopReranker)
    assert rerank_cfg.provider == "cross_encoder"


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


async def test_capabilities_reports_milvus_rebuild_required(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")

    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    caps = await api.get_capabilities()
    vector_stage = next(stage for stage in caps["pipeline"] if stage["id"] == "vector_store")

    assert vector_stage["status"] == "degraded"
    assert vector_stage["detail"]["compatible"] is False
    assert vector_stage["detail"]["rebuild_required"] is True
    assert vector_stage["detail"]["pending_reindex_count"] == 1
    assert vector_stage["detail"]["document_count"] == 1
    assert vector_stage["detail"]["chunk_count"] == 1


async def test_capabilities_uses_aggregate_chunk_count(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    class NoChunkScanStore(InMemorySourceDocumentStore):
        async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
            raise AssertionError(f"capabilities must not scan chunks for {doc_id}")

    store = NoChunkScanStore()
    await store.add_document(_doc("d1", "papers"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")

    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    caps = await api.get_capabilities()
    vector_stage = next(stage for stage in caps["pipeline"] if stage["id"] == "vector_store")

    assert vector_stage["detail"]["document_count"] == 1
    assert vector_stage["detail"]["chunk_count"] == 1


async def test_zotero_active_keeps_success_briefly() -> None:
    from core.zotero_sync_job import ZOTERO_SYNC_SUCCESS, ZoteroSyncJob

    api = await _make_api()
    job = ZoteroSyncJob()
    job.start()
    job.finish(ZOTERO_SYNC_SUCCESS)
    api._zotero_sync_job = job

    active = api.get_active_zotero_sync_job()
    assert active is not None
    assert active["status"] == ZOTERO_SYNC_SUCCESS

    assert job.finished_at is not None
    job.finished_at -= 31
    assert api.get_active_zotero_sync_job() is None


async def test_rebuild_index_pending_retries_transient_embedding_failure(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore

    class FlakyEmbedding:
        dimension = 4
        calls = 0

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("model warming up")
            return [[0.1] * self.dimension for _ in texts]

        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * self.dimension

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    vector_store = InMemoryVectorStore()
    embedding = FlakyEmbedding()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=vector_store,
        embedding_provider=embedding,  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    result = await api.rebuild_index_pending()

    assert result == {"rebuilt_docs": 1, "rebuilt_chunks": 1, "failed_docs": 0, "errors": []}
    assert embedding.calls == 2
    assert await store.list_pending_reindex_documents() == []
    assert "c1" in vector_store._data


# ── Milvus 后台重建进度条 ────────────────────────────────────────────

def test_milvus_build_job_progress_counts_cleaning_and_indexing() -> None:
    from core.milvus_build import MilvusBuildJob

    job = MilvusBuildJob(
        total_docs=2,
        total_clean_docs=1,
        processed_clean_docs=1,
        total_index_docs=2,
        processed_index_docs=1,
    )

    snapshot = job.to_dict()

    assert snapshot["progress_percent"] == 67
    assert snapshot["stage"] == "data_cleaning"
    assert snapshot["processed_clean_docs"] == 1
    assert snapshot["processed_index_docs"] == 1


async def test_start_milvus_rebuild_progresses_to_success(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    snapshot = await api.start_milvus_rebuild()
    assert snapshot["status"] == "running"

    assert api._milvus_build_task is not None
    await api._milvus_build_task

    # 成功后隐藏进度条（None），任务终态为 success，needs_reindex 已清空
    assert api.get_active_milvus_build_job() is None
    assert api._milvus_build_job is not None
    assert api._milvus_build_job.status == "success"
    assert api._milvus_build_job.processed_docs == 1
    assert api._milvus_build_job.total_docs == 1
    assert await store.list_pending_reindex_documents() == []


async def test_start_milvus_rebuild_cleans_legacy_chunks_before_indexing(
    tmp_path: Path,
) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("legacy-1", "d1", 0, "legacy", "old")])

    class FakeIngestManager:
        calls = 0

        @staticmethod
        def chunk_needs_rebuild(
            document_id: str,
            chunks: list[DocumentChunk],
            local_meta: dict | None = None,
        ) -> bool:
            del document_id, local_meta
            return any(chunk.chunk_id == "legacy-1" for chunk in chunks)

        async def rebuild_document_chunks_from_artifact(self, document_id: str) -> int:
            self.calls += 1
            await store.replace_chunks(
                document_id,
                [
                    DocumentChunk(
                        f"{document_id}_c0000",
                        document_id,
                        0,
                        "current structural chunk",
                        "new",
                        metadata={
                            "chunk_schema": "clean_md_structural_v3",
                            "start_char": 0,
                            "end_char": 24,
                        },
                    )
                ],
            )
            current = await store.get_document(document_id)
            assert current is not None
            current.needs_reindex = True
            await store.update_document(current)
            return 1

    ingest = FakeIngestManager()
    vector_store = InMemoryVectorStore()
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=vector_store,
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
        ingest_manager=ingest,  # type: ignore[arg-type]
    )

    await api.start_milvus_rebuild()
    assert api._milvus_build_task is not None
    await api._milvus_build_task

    assert ingest.calls == 1
    assert api._milvus_build_job is not None
    assert api._milvus_build_job.status == "success"
    assert api._milvus_build_job.total_clean_docs == 1
    assert api._milvus_build_job.processed_clean_docs == 1
    assert api._milvus_build_job.total_index_docs == 1
    assert api._milvus_build_job.processed_index_docs == 1
    assert "d1_c0000" in vector_store._data
    assert "legacy-1" not in vector_store._data
    assert await store.list_pending_reindex_documents() == []


async def test_start_milvus_rebuild_is_single_flight(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.milvus_build import MilvusBuildJob
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=IndexCompatibilityStore(tmp_path / "compat.json"),
        embedding_fingerprint="fp",
    )
    # 预置一个 running 任务 → 再次 start 应返回同一任务而不新建
    existing = MilvusBuildJob(status="running", total_docs=5, processed_docs=2)
    api._milvus_build_job = existing
    snapshot = await api.start_milvus_rebuild()
    assert snapshot["job_id"] == existing.job_id
    assert api._milvus_build_task is None  # 未创建新后台任务


async def test_capabilities_degraded_while_milvus_building(tmp_path: Path) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.milvus_build import MilvusBuildJob
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")  # 未标记 needs_reindex → 正常应不需重建
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    caps_before = await api.get_capabilities()
    vs_before = next(s for s in caps_before["pipeline"] if s["id"] == "vector_store")
    assert vs_before["detail"]["rebuild_required"] is False
    assert vs_before["detail"]["building"] is False

    # 模拟构建进行中 → 即便无 pending，也应强制 degraded（黄）
    api._milvus_build_job = MilvusBuildJob(status="running", total_docs=3, processed_docs=1)
    caps = await api.get_capabilities()
    vs = next(s for s in caps["pipeline"] if s["id"] == "vector_store")
    assert vs["status"] == "degraded"
    assert vs["detail"]["building"] is True
    assert vs["detail"]["rebuild_required"] is True
    assert vs["detail"]["build_stage"] == "data_cleaning"
    assert "清洗数据" in vs["detail"]["reason"]


async def test_start_milvus_rebuild_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.api as api_module
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore

    monkeypatch.setattr(api_module, "MILVUS_INDEX_RETRY_DELAYS", (0.0, 0.0))

    class AlwaysFailEmbedding:
        dimension = 4

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom")

        async def embed_query(self, text: str) -> list[float]:
            return [0.1] * self.dimension

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "evidence", "h1")])
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=InMemoryVectorStore(),
        embedding_provider=AlwaysFailEmbedding(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    await api.start_milvus_rebuild()
    assert api._milvus_build_task is not None
    await api._milvus_build_task

    active = api.get_active_milvus_build_job()
    assert active is not None
    assert active["status"] == "partial_failure"
    assert active["failed_docs"] == 1
    assert active["processed_docs"] == 0


async def test_start_milvus_rebuild_cleaning_failure_skips_index(
    tmp_path: Path,
) -> None:
    from core.config import Config
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.vector_store.memory import InMemoryVectorStore
    from tests.backend.test_embedding import MockEmbeddingProvider

    store = InMemorySourceDocumentStore()
    doc = _doc("d1", "papers")
    doc.needs_reindex = True
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("legacy-1", "d1", 0, "legacy", "old")])

    class FailingIngestManager:
        @staticmethod
        def chunk_needs_rebuild(
            document_id: str,
            chunks: list[DocumentChunk],
            local_meta: dict | None = None,
        ) -> bool:
            del document_id, chunks, local_meta
            return True

        async def rebuild_document_chunks_from_artifact(self, document_id: str) -> int:
            raise FileNotFoundError(f"Markdown artifact not found for {document_id}")

    vector_store = InMemoryVectorStore()
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_milvus_compatible("fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        config=Config({"vector_db": {"backend": "milvus"}}),
        vector_store=vector_store,
        embedding_provider=MockEmbeddingProvider(dimension=4),
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
        ingest_manager=FailingIngestManager(),  # type: ignore[arg-type]
    )

    await api.start_milvus_rebuild()
    assert api._milvus_build_task is not None
    await api._milvus_build_task

    active = api.get_active_milvus_build_job()
    pending = await store.list_pending_reindex_documents()

    assert active is not None
    assert active["status"] == "partial_failure"
    assert active["failed_docs"] == 1
    assert active["total_clean_docs"] == 1
    assert active["processed_clean_docs"] == 0
    assert active["total_index_docs"] == 0
    assert active["processed_docs"] == 0
    assert active["errors"][0]["stage"] == "data_cleaning"
    assert vector_store._data == {}
    assert [doc.doc_id for doc in pending] == ["d1"]


# ── LightRAG API 层覆盖补充 ──────────────────────────────────────────

async def test_lightrag_readiness_fully_ready(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    result = await api.get_lightrag_readiness("papers")

    assert result["ready"] is True
    assert result["build_available"] is False


async def test_lightrag_readiness_partially_indexed(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.add_document(_doc("d2", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    # d2 未 indexed，状态缺失 → 计入 invalid
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    result = await api.get_lightrag_readiness("papers")

    # 部分索引（d1 indexed，d2 未索引）→ 仍视为 ready（至少有一篇可用）
    assert result["ready"] is True
    assert result["indexed_docs"] == 1
    assert result["unindexed_docs"] == 1


async def test_build_graph_raises_when_not_confirmed() -> None:
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

    with pytest.raises(ValueError):
        await api.build_graph("papers", confirmed=False)


async def test_build_graph_partial_failure_when_insert_raises(tmp_path: Path) -> None:
    from core.lightrag_core import BuildJob

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return False

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks: list[str] | None = None,
            progress_callback=None,
        ) -> None:
            raise RuntimeError("LLM API timeout")

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "content", "h1")])
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
    )
    api._graph_build_jobs["job"] = BuildJob(job_id="job", collection="papers")

    await api._run_lightrag_build_job("job")

    job = api._graph_build_jobs["job"]
    assert job.status == "partial_failure"
    assert job.failed_docs == 1


async def test_build_graph_reports_lrag_chunk_progress() -> None:
    from core.lightrag_core import BuildJob

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return False

        async def chunk_document(self, collection: str, text: str) -> tuple[list[str], str]:
            assert collection == "papers"
            return ["part 1", "part 2", "part 3"], "lrag_chunks"

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks: list[str] | None = None,
            progress_callback=None,
        ) -> None:
            assert lrag_chunks == ["part 1", "part 2", "part 3"]
            if progress_callback:
                progress_callback({"status": "ok"})
                progress_callback({"status": "ok"})

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "content", "h1")])
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
    )
    api._graph_build_jobs["job"] = BuildJob(job_id="job", collection="papers")

    await api._run_lightrag_build_job("job")

    job = api._graph_build_jobs["job"]
    assert job.status == "success"
    assert job.total_chunks == 3
    assert job.processed_chunks == 3
    assert job.progress_basis == "lrag_chunks"
    assert job.to_dict()["estimated_remaining_seconds"] == 0


async def test_probe_lightrag_core_delegates_to_registry() -> None:
    received: dict = {}

    class Registry:
        async def manual_probe(
            self, *, collection: str, text: str, doc_id: str, query: str
        ) -> dict:
            received.update(
                {"collection": collection, "text": text, "doc_id": doc_id, "query": query}
            )
            return {"status": "success", "steps": []}

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
    )

    result = await api.probe_lightrag_core("col", "text content", "doc_x", "test query")

    assert result["status"] == "success"
    assert received == {
        "collection": "col",
        "text": "text content",
        "doc_id": "doc_x",
        "query": "test query",
    }


async def test_query_graph_delegates_to_registry_when_ready(tmp_path: Path) -> None:
    from core.index_compatibility import IndexCompatibilityStore

    queries: list[str] = []

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

        async def query(
            self, collection: str, query: str, *, only_need_context: bool = False
        ) -> dict:
            queries.append(query)
            return {"answer": "graph answer", "context": "", "entities": [], "relations": []}

    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    result = await api.query_graph("transformer attention", collection="papers")

    assert queries == ["transformer attention"]
    assert result["status"] == "success"
    assert result["answer"] == "graph answer"


# ── Deep Thinking 模式端到端 ────────────────────────────────
class _MockSynthLLM:
    async def generate(
        self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True
    ) -> str:
        return "deep answer [1]"


class _MockDeepThinking:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.query = ""
        self.answer_question = None

    async def run(
        self,
        collection,
        query,
        scope=None,
        progress=None,
        answer_language="auto",
        answer_question=None,
    ):
        self.query = query
        self.answer_question = answer_question
        return self._outcome


async def test_deep_thinking_requires_collection() -> None:
    """deep_thinking 必须显式 collection（校验先于 orchestrator 调用）。"""
    api = await _make_api()
    with pytest.raises(ValueError):
        await api.ask(question="q", retrieval_mode="deep_thinking")


async def test_deep_thinking_returns_trace_and_synthesizes() -> None:
    from core.domain.deep_thinking import (
        Checklist,
        ChecklistItem,
        DeepThinkingOutcome,
        RoundTrace,
    )

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "evidence text", "h0")],
        checklist=Checklist([ChecklistItem("c1", "方法", critical=True, satisfied=True)]),
        trace=[
            RoundTrace(
                round=1, queries=["q1"], gaps=[], kept_chunk_ids=["c0"], llm_calls=2, est_tokens=900
            )
        ],
        degraded=False,
        actual_mode="milvus_deep",
        est_total_tokens=1500,
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    kb = InMemoryKnowledgeBaseReader(
        {"papers": [DocumentChunk("c0", "d1", 0, "evidence text", "h0")]}
    )
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=_MockSynthLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )
    result = await api.ask(
        question="综述问题", collection="papers", retrieval_mode="deep_thinking"
    )
    assert result["actual_retrieval_mode"] == "milvus_deep"
    assert result["answer"].startswith("**提示：以下回答尚未完成证据校验。**")
    assert result["answer"].endswith("deep answer [1]")
    assert len(result["sources"]) == 1
    trace = result["thinking_trace"]
    assert trace is not None
    assert trace["degraded"] is False
    assert trace["rounds"][0]["round"] == 1
    assert trace["checklist"][0]["satisfied"] is True


async def test_deep_thinking_trace_serializes_discovered_and_origin() -> None:
    """v0.25.9：开放式发现写入 trace.rounds[].discovered，checklist 暴露 origin。"""
    from core.domain.deep_thinking import (
        Checklist,
        ChecklistItem,
        DeepThinkingOutcome,
        RoundTrace,
    )

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "ev", "h0")],
        checklist=Checklist(
            [
                ChecklistItem("c1", "方法", critical=True, satisfied=True),
                ChecklistItem("d1", "新机制X", origin="discovered"),
            ]
        ),
        trace=[
            RoundTrace(
                round=1, queries=["q1"], gaps=[], discovered=["新机制X"], kept_chunk_ids=["c0"]
            )
        ],
        answer="ans [1]",
        verified=True,
        actual_mode="milvus_deep",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    kb = InMemoryKnowledgeBaseReader({"papers": [DocumentChunk("c0", "d1", 0, "ev", "h0")]})
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=_MockSynthLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )
    result = await api.ask(question="综述", collection="papers", retrieval_mode="deep_thinking")
    trace = result["thinking_trace"]
    assert trace["rounds"][0]["discovered"] == ["新机制X"]
    origins = {i["id"]: i["origin"] for i in trace["checklist"]}
    assert origins["d1"] == "discovered"
    assert origins["c1"] == "plan"


async def test_deep_thinking_verify_disabled_uses_deep_synth_fallback() -> None:
    """v0.25.9 (P2-b)：deep 模式即便无 deep_outcome.answer 也走 deep 合成，不退回普通 prompt。"""
    from core.domain.deep_thinking import DeepThinkingOutcome

    class _RecordingLLM:
        def __init__(self) -> None:
            self.system_prompts: list[str] = []

        async def generate(self, prompt, system_prompt="", *, allow_mock=True):
            self.system_prompts.append(system_prompt)
            return "deep fallback answer [1]"

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "ev", "h0")],
        answer=None,  # verify 关闭 → orchestrator 不产出 answer。
        verified=False,
        actual_mode="milvus_deep",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    kb = InMemoryKnowledgeBaseReader({"papers": [DocumentChunk("c0", "d1", 0, "ev", "h0")]})
    llm = _RecordingLLM()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=llm,  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )
    result = await api.ask(question="综述", collection="papers", retrieval_mode="deep_thinking")
    assert result["answer"].endswith("deep fallback answer [1]")
    assert any("mechanism" in s.lower() for s in llm.system_prompts)


async def test_deep_thinking_degraded_reports_mode() -> None:
    from core.domain.deep_thinking import DeepThinkingOutcome

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "baseline text", "h0")],
        degraded=True,
        actual_mode="deep_degraded_to_default",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    kb = InMemoryKnowledgeBaseReader({"papers": []})
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=_MockSynthLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )
    result = await api.ask(question="q", collection="papers", retrieval_mode="deep_thinking")
    assert result["actual_retrieval_mode"] == "deep_degraded_to_default"
    assert result["thinking_trace"]["degraded"] is True


async def test_default_mode_has_null_thinking_trace() -> None:
    """回归：非 deep_thinking 路径 thinking_trace 为 None。"""
    api = await _make_api()
    result = await api.ask(question="alpha", collection="kb1")
    assert result["thinking_trace"] is None


async def test_deep_thinking_english_retrieval_keeps_original_answer_question() -> None:
    """英语召回只影响检索 query，最终回答问题仍传用户原文。"""
    from core.domain.deep_thinking import DeepThinkingOutcome

    class _TranslateOnlyLLM:
        async def generate(self, prompt, system_prompt="", *, allow_mock=True):
            assert "Translate the following query to English" in prompt
            return "translated retrieval query"

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "ev", "h0")],
        answer="verified answer [1]",
        verified=True,
        actual_mode="milvus_deep",
    )
    deep = _MockDeepThinking(outcome)
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({"papers": []}),
        llm_adapter=_TranslateOnlyLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=deep,  # type: ignore[arg-type]
    )

    result = await api.ask(
        question="用户原始问题",
        collection="papers",
        retrieval_mode="deep_thinking",
        use_english_retrieval=True,
    )

    assert result["answer"] == "verified answer [1]"
    assert deep.query == "translated retrieval query"
    assert deep.answer_question == "用户原始问题"


async def test_deep_thinking_uses_verified_answer_when_present() -> None:
    """orchestrator 产出 answer（verification 闭环）时，api.ask 直接用之，不重复合成。"""
    from core.domain.deep_thinking import DeepThinkingOutcome

    class _ShouldNotSynth:
        async def generate(self, prompt, system_prompt="", *, allow_mock=True):
            return "SHOULD NOT BE USED"

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "ev", "h0")],
        answer="verified answer [1]",
        verified=True,
        actual_mode="milvus_deep",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    kb = InMemoryKnowledgeBaseReader({"papers": []})
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=kb,
        llm_adapter=_ShouldNotSynth(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )
    result = await api.ask(question="q", collection="papers", retrieval_mode="deep_thinking")
    assert result["answer"] == "verified answer [1]"
    assert result["thinking_trace"]["verified"] is True


async def test_deep_thinking_degraded_answer_gets_warning_prefix() -> None:
    from core.domain.deep_thinking import DeepThinkingOutcome

    class _SynthLLM:
        async def generate(self, prompt, system_prompt="", *, allow_mock=True):
            return "有限回答 [1]"

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "baseline text", "h0")],
        degraded=True,
        degraded_reason="关键检查项未满足",
        actual_mode="deep_degraded_to_default",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({"papers": []}),
        llm_adapter=_SynthLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )

    result = await api.ask(question="综述问题", collection="papers", retrieval_mode="deep_thinking")

    assert result["answer"].startswith("**提示：深度思考证据不足")
    assert "关键检查项未满足" in result["answer"]
    assert result["answer"].endswith("有限回答 [1]")


async def test_deep_thinking_unverified_missing_gets_warning_prefix() -> None:
    from core.domain.deep_thinking import DeepThinkingOutcome

    outcome = DeepThinkingOutcome(
        evidence=[DocumentChunk("c0", "d1", 0, "ev", "h0")],
        answer="草稿回答 [1]",
        verified=False,
        verify_missing=["缺少定义", "缺少对比"],
        actual_mode="milvus_deep",
    )
    store = InMemorySourceDocumentStore()
    await store.add_document(_doc("d1", "papers"))
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({"papers": []}),
        llm_adapter=_MockSynthLLM(),  # type: ignore[arg-type]
        deep_thinking_orchestrator=_MockDeepThinking(outcome),  # type: ignore[arg-type]
    )

    result = await api.ask(question="综述问题", collection="papers", retrieval_mode="deep_thinking")

    assert result["answer"].startswith("**提示：以下回答未完全通过证据校验。**")
    # 告警瘦身（v0.25.9）：正文只留缺口计数 notice，不再 join 全量 missing 进正文。
    assert "共 2 项" in result["answer"]
    assert "缺少定义" not in result["answer"]
    assert "缺少对比" not in result["answer"]
    assert result["answer"].endswith("草稿回答 [1]")
    assert result["actual_retrieval_mode"] == "milvus_deep"
    assert result["thinking_trace"]["degraded"] is False
    # 完整明细仍经 thinking_trace.verify_missing 暴露（前端折叠渲染）。
    assert result["thinking_trace"]["verify_missing"] == ["缺少定义", "缺少对比"]


async def test_restart_plugin_unsupported_without_callback() -> None:
    """未注入 reload_callback（如无法程序化重启的环境）时返回 unsupported，不报错。"""
    api = await _make_api()
    result = await api.restart_plugin()
    assert result["status"] == "unsupported"


async def test_restart_plugin_schedules_reload() -> None:
    """注入 reload_callback 时立即返回 restarting，并在后台延迟触发软重启回调。"""
    reloaded = asyncio.Event()

    async def _reload() -> None:
        reloaded.set()

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        reload_callback=_reload,
    )
    result = await api.restart_plugin()
    assert result["status"] == "restarting"
    await asyncio.wait_for(reloaded.wait(), timeout=3.0)
