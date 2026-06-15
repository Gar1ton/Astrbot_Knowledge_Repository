import importlib.util
import os
import shutil
import tempfile

import aiosqlite
import pytest

from core.config import Config
from core.domain.models import Collection, DocumentChunk, SourceDocument
from core.migration_runner import run_migrations
from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
from core.repository.kb_reader.base import KnowledgeBaseReader
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from core.repository.vector_store.milvus_lite import MilvusLiteVectorStore

_pymilvus_available = importlib.util.find_spec("pymilvus") is not None


class MockKnowledgeBaseReader(KnowledgeBaseReader):
    def __init__(self, chunks=None):
        self.chunks = chunks or []

    async def list_collections(self) -> list[str]:
        return ["col1"]

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        return self.chunks

    async def search(self, collection: str, query: str, top_k: int) -> list[DocumentChunk]:
        return self.chunks[:top_k]


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def sqlite_store(temp_dir):
    db_path = os.path.join(temp_dir, "test_source.db")
    db = await aiosqlite.connect(db_path)
    await db.execute("PRAGMA foreign_keys = ON")

    # 跑真实迁移以获得与生产一致的 schema（含制品包/Zotero 镜像列）。
    await run_migrations(db)

    store = SQLiteSourceDocumentStore(db)
    # documents.collection 外键指向 collections(name)
    await store.upsert_collection(Collection(name="default"))
    await store.upsert_collection(Collection(name="papers"))
    yield store
    await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not _pymilvus_available, reason="pymilvus not installed")
async def test_milvus_lite_vector_store_lifecycle(temp_dir):
    db_path = os.path.join(temp_dir, "milvus_lite_test.db")
    store = MilvusLiteVectorStore(db_path=db_path, dim=4)
    
    # 1. Register document mapping
    store.set_doc_collection_mapping("doc_1", "col_1")
    store.set_doc_collection_mapping("doc_2", "col_1")
    
    chunks = [
        DocumentChunk("c1", "doc_1", 0, "attention neural network", "h1"),
        DocumentChunk("c2", "doc_2", 0, "milvus vector database", "h2"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    
    # 2. Upsert
    await store.upsert_chunks(chunks, embeddings)
    
    # 3. Search
    results = await store.search("col_1", [0.9, 0.1, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0][0] == "c1"
    
    # 4. Search with metadata filtering
    results_filtered = await store.search(
        "col_1", [0.9, 0.1, 0.0, 0.0], top_k=2, filter_metadata={"doc_id": "doc_2"}
    )
    assert len(results_filtered) == 1
    assert results_filtered[0][0] == "c2"
    
    # 5. Delete chunks
    await store.delete_chunks(["c1"])
    results_after_delete = await store.search("col_1", [1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(results_after_delete) == 1
    assert results_after_delete[0][0] == "c2"
    
    # 6. Delete collection
    await store.delete_collection("col_1")
    results_col_deleted = await store.search("col_1", [0.0, 1.0, 0.0, 0.0], top_k=2)
    assert len(results_col_deleted) == 0
    
    # 7. Close
    await store.close()


@pytest.mark.asyncio
async def test_retrieval_orchestrator_lexical_fallback(sqlite_store):
    # Setup document and chunks in SQLite source store
    doc = SourceDocument(
        doc_id="doc1",
        title="Attention Paper",
        file_path="attention.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        content_hash="hash1",
        collection="papers",
    )
    await sqlite_store.add_document(doc)
    
    chunks = [
        DocumentChunk(
            "c1", "doc1", 0, "transformer model relies entirely on attention mechanisms", "hc1"
        ),
        DocumentChunk("c2", "doc1", 1, "dense vectors are used for semantic search", "hc2"),
    ]
    await sqlite_store.replace_chunks("doc1", chunks)
    
    config = Config(raw={})
    kb_reader = MockKnowledgeBaseReader()
    
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=kb_reader,
        config=config,
    )
    
    # Test Lexical road search via RetrievalOrchestrator
    results = await orchestrator.retrieve("papers", "attention mechanisms", top_k=2)
    assert len(results) >= 1
    assert results[0].chunk_id == "c1"
    assert "attention" in results[0].text


@pytest.mark.asyncio
async def test_retrieval_orchestrator_lexical_fallback_supports_chinese_query(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-zh",
            "离线安装",
            "offline.pdf",
            "application/pdf",
            100,
            "hash-zh",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-zh",
        [DocumentChunk("c-zh", "doc-zh", 0, "离线安装后仍然可以完成基础召回", "hc-zh")],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    result = await orchestrator.retrieve_with_outcome("papers", "离线环境如何召回", top_k=2)

    assert [chunk.chunk_id for chunk in result.chunks] == ["c-zh"]
    assert "sqlite_lexical" in result.engines


@pytest.mark.asyncio
async def test_retrieval_orchestrator_prioritizes_thesis_heading_anchor(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-anchor",
            "Synthetic Anchors",
            "synthetic.pdf",
            "application/pdf",
            100,
            "hash-anchor",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-anchor",
        [
            DocumentChunk(
                "c-ref",
                "doc-anchor",
                0,
                "A neighboring paragraph cross-references T42 without explaining it.",
                "h-ref",
                metadata={"section_label": "T41", "chunk_schema": "clean_md_structural_v3"},
            ),
            DocumentChunk(
                "c-t42",
                "doc-anchor",
                1,
                "T42\nThis synthetic thesis defines the target anchor directly.",
                "h-t42",
                metadata={"section_label": "T42", "chunk_schema": "clean_md_structural_v3"},
            ),
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    result = await orchestrator.retrieve_with_outcome(
        "papers", "T42具体说了什么，同时能附带一些原文来说明吗", top_k=2
    )

    assert [chunk.chunk_id for chunk in result.chunks] == ["c-t42", "c-ref"]
    assert "sqlite_anchor" in result.engines
    assert "sqlite_lexical" in result.engines


@pytest.mark.asyncio
async def test_retrieval_outcome_exposes_per_chunk_signals(sqlite_store):
    """retrieve_with_outcome 应为每个返回 chunk 暴露 rrf_score 与 anchor_hit 旁路信号。"""
    await sqlite_store.add_document(
        SourceDocument(
            "doc-sig", "Signal Doc", "sig.pdf", "application/pdf", 100, "hash-sig", "papers"
        )
    )
    await sqlite_store.replace_chunks(
        "doc-sig",
        [
            DocumentChunk(
                "c-t42",
                "doc-sig",
                0,
                "T42\nThis section defines the anchor target directly.",
                "h-t42",
                metadata={"section_label": "T42", "chunk_schema": "clean_md_structural_v3"},
            ),
            DocumentChunk(
                "c-plain",
                "doc-sig",
                1,
                "An unrelated paragraph about attention mechanisms.",
                "h-plain",
            ),
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    result = await orchestrator.retrieve_with_outcome("papers", "T42 与 attention 的关系", top_k=2)

    # 每个返回 chunk 都有 signal，rrf_score 为正。
    assert set(result.per_chunk_signals) == {chunk.chunk_id for chunk in result.chunks}
    assert all(sig.rrf_score > 0 for sig in result.per_chunk_signals.values())
    # 命中结构锚点的 chunk anchor_hit=True；纯词法命中的 chunk 为 False。
    assert result.per_chunk_signals["c-t42"].anchor_hit is True
    assert result.per_chunk_signals["c-plain"].anchor_hit is False


@pytest.mark.asyncio
async def test_retrieval_dedups_identical_content_hash(sqlite_store):
    """不同 chunk_id 但相同 content_hash（近重复内容）应只保留最高分一个。"""
    await sqlite_store.add_document(
        SourceDocument(
            "doc-dup", "Dup Doc", "dup.pdf", "application/pdf", 100, "hash-dup", "papers"
        )
    )
    await sqlite_store.replace_chunks(
        "doc-dup",
        [
            DocumentChunk("c-a", "doc-dup", 0, "attention mechanism explained here", "samehash"),
            DocumentChunk("c-b", "doc-dup", 1, "attention mechanism explained here", "samehash"),
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    result = await orchestrator.retrieve_with_outcome("papers", "attention mechanism", top_k=5)

    # 同 content_hash 的两个 chunk 只保留一个，不再冗余进上下文。
    assert [c.content_hash for c in result.chunks].count("samehash") == 1


@pytest.mark.asyncio
async def test_retrieval_orchestrator_matches_section_label_lists(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-numbered",
            "Synthetic Numbered Sections",
            "numbered.pdf",
            "application/pdf",
            100,
            "hash-numbered",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-numbered",
        [
            DocumentChunk(
                "c-merged",
                "doc-numbered",
                0,
                "2 Materials and methods\n2.1 Study area\nSynthetic body text.",
                "h-merged",
                metadata={
                    "section_label": "2",
                    "section_labels": ["2", "2.1"],
                    "section_path": ["2"],
                    "section_paths": [["2"], ["2", "2.1"]],
                    "chunk_schema": "clean_md_structural_v3",
                },
            ),
            DocumentChunk(
                "c-other",
                "doc-numbered",
                1,
                "2.2 Data sources\nSynthetic neighboring section.",
                "h-other",
                metadata={
                    "section_label": "2.2",
                    "section_labels": ["2", "2.2"],
                    "section_path": ["2", "2.2"],
                    "section_paths": [["2"], ["2", "2.2"]],
                    "chunk_schema": "clean_md_structural_v3",
                },
            ),
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    result = await orchestrator.retrieve_with_outcome(
        "papers", "2.1 section details", top_k=2
    )

    assert result.chunks[0].chunk_id == "c-merged"
    assert "sqlite_anchor" in result.engines


@pytest.mark.asyncio
async def test_retrieval_orchestrator_matches_generic_section_queries(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-generic",
            "Synthetic Generic Sections",
            "generic.pdf",
            "application/pdf",
            100,
            "hash-generic",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-generic",
        [
            DocumentChunk(
                "c-section-2",
                "doc-generic",
                0,
                "2 Methods\nSynthetic method body.",
                "h-section-2",
                metadata={
                    "section_label": "2",
                    "section_labels": ["2"],
                    "section_path": ["2"],
                    "section_paths": [["2"]],
                    "chunk_schema": "clean_md_structural_v3",
                },
            ),
            DocumentChunk(
                "c-section-3",
                "doc-generic",
                1,
                "3 Results\nSynthetic result body.",
                "h-section-3",
                metadata={
                    "section_label": "3",
                    "section_labels": ["3"],
                    "section_path": ["3"],
                    "section_paths": [["3"]],
                    "chunk_schema": "clean_md_structural_v3",
                },
            ),
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    explicit = await orchestrator.retrieve_with_outcome(
        "papers", "section 2 method details", top_k=2
    )
    bare_number = RetrievalOrchestrator._structural_anchors("2 method details")

    assert explicit.chunks[0].chunk_id == "c-section-2"
    assert "sqlite_anchor" in explicit.engines
    assert "section_label" not in bare_number


@pytest.mark.asyncio
async def test_retrieval_orchestrator_matches_caption_anchor_lists(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-captions",
            "Synthetic Captions",
            "captions.pdf",
            "application/pdf",
            100,
            "hash-captions",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-captions",
        [
            DocumentChunk(
                "c-caption",
                "doc-captions",
                0,
                "A synthetic chunk containing caption metadata.",
                "h-caption",
                metadata={
                    "section_label": "2.1",
                    "anchor_labels": ["FIGURE 1", "TABLE 2", "EQUATION 3"],
                    "chunk_schema": "clean_md_structural_v3",
                },
            )
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    figure = await orchestrator.retrieve_with_outcome("papers", "Fig. 1", top_k=1)
    table = await orchestrator.retrieve_with_outcome("papers", "Table 2", top_k=1)
    equation = await orchestrator.retrieve_with_outcome("papers", "Equation 3", top_k=1)

    assert figure.chunks[0].chunk_id == "c-caption"
    assert table.chunks[0].chunk_id == "c-caption"
    assert equation.chunks[0].chunk_id == "c-caption"
    assert "sqlite_anchor" in figure.engines
    assert "sqlite_anchor" in table.engines
    assert "sqlite_anchor" in equation.engines


@pytest.mark.asyncio
async def test_retrieval_orchestrator_matches_appendix_anchor(sqlite_store):
    await sqlite_store.add_document(
        SourceDocument(
            "doc-appendix",
            "Synthetic Appendix",
            "appendix.pdf",
            "application/pdf",
            100,
            "hash-appendix",
            "papers",
        )
    )
    await sqlite_store.replace_chunks(
        "doc-appendix",
        [
            DocumentChunk(
                "c-appendix",
                "doc-appendix",
                0,
                "Appendix A\nA.1 Extra setup\nSynthetic appendix body.",
                "h-appendix",
                metadata={
                    "section_label": "A.1",
                    "section_labels": ["Appendix A", "A.1"],
                    "section_path": ["Appendix A", "A.1"],
                    "section_paths": [["Appendix A"], ["Appendix A", "A.1"]],
                    "chunk_schema": "clean_md_structural_v3",
                },
            )
        ],
    )
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
    )

    appendix = await orchestrator.retrieve_with_outcome(
        "papers", "appendix A extra setup", top_k=1
    )
    subsection = await orchestrator.retrieve_with_outcome("papers", "A.1", top_k=1)

    assert appendix.chunks[0].chunk_id == "c-appendix"
    assert subsection.chunks[0].chunk_id == "c-appendix"
    assert "sqlite_anchor" in appendix.engines
    assert "sqlite_anchor" in subsection.engines


@pytest.mark.asyncio
async def test_lightrag_context_queries_workspace_regardless_of_doc_status(tmp_path):
    """构建完成（含部分失败）后查询不应因单文档状态而阻断。"""
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    class Registry:
        calls = 0

        def has_workspace(self, collection: str) -> bool:
            return True

        async def query(
            self, collection: str, query: str, *, only_need_context: bool = False
        ) -> dict:
            self.calls += 1
            return {"context": "graph context"}

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument("d1", "Doc", "/d1.pdf", "application/pdf", 1, "h", "papers")
    )
    await store.add_document(
        SourceDocument("d2", "Doc2", "/d2.pdf", "application/pdf", 1, "h2", "papers")
    )
    # d1 indexed, d2 failed — 模拟 partial_failure 构建场景
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    await store.set_lightrag_index_status("d2", "papers", "error", "LLM timeout")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    registry = Registry()
    orchestrator = RetrievalOrchestrator(
        source_store=store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
        lightrag_registry=registry,  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    # 即使 d2 失败，查询仍应正常到达 LightRAG
    result = await orchestrator.retrieve_lightrag_context("papers", "q")
    assert result == "graph context"
    assert registry.calls == 1


@pytest.mark.asyncio
async def test_lightrag_context_rejects_missing_workspace(tmp_path):
    """workspace 不存在时应拒绝查询。"""
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return False

        async def query(self, collection: str, query: str, **kwargs) -> dict:
            return {"context": "should not reach"}

    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument("d1", "Doc", "/d1.pdf", "application/pdf", 1, "h", "papers")
    )
    await store.set_lightrag_index_status("d1", "papers", "indexed")
    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    orchestrator = RetrievalOrchestrator(
        source_store=store,
        kb_reader=MockKnowledgeBaseReader(),
        config=Config({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    with pytest.raises(RuntimeError, match="workspace has not been built"):
        await orchestrator.retrieve_lightrag_context("papers", "q")
