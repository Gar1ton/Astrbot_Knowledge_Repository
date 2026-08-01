from __future__ import annotations

import copy
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from kacore.config import GraphConfig
from kacore.domain.models import DocumentChunk, SourceDocument
from kacore.lightrag_core import (
    LightRAGCoreRegistry,
    LightRAGEmbeddingAdapter,
    LightRAGLLMAdapter,
    estimate_lightrag_build,
    parse_lightrag_csv,
    sanitize_collection_name,
)


def test_sanitize_collection_name_handles_unsafe_and_case_conflicts() -> None:
    first = sanitize_collection_name("Papers/AI 2026", set())
    second = sanitize_collection_name("papers/ai 2026", {first})

    assert "/" not in first and ".." not in first and first
    assert first != second


def test_estimate_lightrag_build_uses_existing_chunks_without_model_calls() -> None:
    docs = [SourceDocument("d1", "Doc", "/tmp/d.pdf", "application/pdf", 1, "h", "papers")]
    chunks = {
        "d1": [DocumentChunk("c1", "d1", 0, "abc", "h1"), DocumentChunk("c2", "d1", 1, "def", "h2")]
    }

    result = estimate_lightrag_build(docs, chunks)

    assert result["docs_count"] == 1
    assert result["chunks_count"] == 2
    assert result["chars_count"] == len("abc\n\ndef")
    assert result["estimated_lrag_chunks"] == 1
    assert "LRAG chunk" in result["estimate_notice"]


def test_parse_lightrag_csv_entities_and_relations(tmp_path: Path) -> None:
    export = tmp_path / "graph.csv"
    export.write_text(
        "# ENTITIES\n"
        "entity_name,source_id,graph_data\n"
        "Transformer,c1,\"{'entity_type': 'Method', 'description': 'Model', 'source_id': 'c1'}\"\n"
        "Attention,c2,\"{'entity_type': 'Concept', 'description': 'Mechanism', "
        "'source_id': 'c2'}\"\n"
        "\n\n# RELATIONS\n"
        "src_entity,tgt_entity,source_id,graph_data\n"
        "Transformer,Attention,c1,\"{'keywords': 'uses', "
        "'description': 'Transformer uses attention', 'weight': 2.0, "
        "'source_id': 'c1'}\"\n",
        encoding="utf-8",
    )

    payload = parse_lightrag_csv(export, "papers")

    assert payload["status"] == "success"
    assert payload["engine"] == "lightrag_core"
    assert [node["id"] for node in payload["nodes"]] == ["Transformer", "Attention"]
    assert payload["edges"][0]["source"] == "Transformer"
    assert payload["edges"][0]["target"] == "Attention"
    assert payload["edges"][0]["relation"] == "uses"


async def test_lightrag_llm_adapter_flattens_history_and_disables_mock() -> None:
    class StubLLM:
        async def generate(self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True):
            self.call = (prompt, system_prompt, allow_mock)
            return "answer"

    stub = StubLLM()
    adapter = LightRAGLLMAdapter(stub)  # type: ignore[arg-type]
    result = await adapter(
        "current", system_prompt="system", history_messages=[{"role": "user", "content": "old"}]
    )

    assert result == "answer"
    assert stub.call == ("user: old\n\ncurrent", "system", False)


def test_lightrag_llm_adapter_survives_deepcopy() -> None:
    class LockingLLM:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        async def generate(self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True):
            return "answer"

    adapter = LightRAGLLMAdapter(LockingLLM())  # type: ignore[arg-type]
    # 模拟 LightRAG 对 global_config 的 dataclasses.asdict() 风格深拷贝。
    global_config = {"llm_model_func": adapter, "nested": {"llm_model_func": adapter}}

    copied = copy.deepcopy(global_config)

    assert copied["llm_model_func"] is adapter
    assert copied["nested"]["llm_model_func"] is adapter


def test_lightrag_embedding_adapter_survives_deepcopy() -> None:
    class LockingEmbedding:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    adapter = LightRAGEmbeddingAdapter(
        LockingEmbedding(),  # type: ignore[arg-type]
        embedding_dim=1,
        max_token_size=100,
        model_name="stub",
    )
    global_config = {"embedding_func": adapter, "nested": {"embedding_func": adapter}}

    copied = copy.deepcopy(global_config)

    assert copied["embedding_func"] is adapter
    assert copied["nested"]["embedding_func"] is adapter


async def test_lightrag_construction_with_locking_adapters_does_not_raise_pickle_error(
    tmp_path: Path,
) -> None:
    """回归 LightRAG 1.5.5rc1 构造期 `cannot pickle '_thread.lock' object`。

    真实场景中适配器间接持有的运行时 provider 对象含 threading.Lock；不 mock lightrag-hku，
    直接走真实构造路径，确保 __deepcopy__ 修复对上游库的实际行为生效。
    """
    lightrag = pytest.importorskip("lightrag")
    from lightrag.utils import EmbeddingFunc

    class LockingLLM:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        async def generate(self, prompt: str, system_prompt: str = "", *, allow_mock: bool = True):
            return "answer"

    class LockingEmbedding:
        def __init__(self) -> None:
            self._lock = threading.Lock()

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.0, 0.0] for _ in texts]

    llm_adapter = LightRAGLLMAdapter(LockingLLM())  # type: ignore[arg-type]
    embedding_adapter = LightRAGEmbeddingAdapter(
        LockingEmbedding(),  # type: ignore[arg-type]
        embedding_dim=2,
        max_token_size=100,
        model_name="stub",
    )

    rag = lightrag.LightRAG(
        working_dir=str(tmp_path / "lightrag_ws"),
        embedding_func=EmbeddingFunc(
            embedding_dim=embedding_adapter.embedding_dim,
            max_token_size=embedding_adapter.max_token_size,
            func=embedding_adapter,
        ),
        llm_model_func=llm_adapter,
    )

    assert rag is not None


async def test_estimate_lightrag_build_local_profile_is_conservative() -> None:
    docs = [SourceDocument("d1", "Doc", "/tmp/d.pdf", "application/pdf", 1, "h", "papers")]
    long_text = "x" * 9000
    chunks = {"d1": [DocumentChunk("c1", "d1", 0, long_text, "h1")]}

    remote = estimate_lightrag_build(docs, chunks, seconds_per_chunk_remote=10)
    local = estimate_lightrag_build(
        docs,
        chunks,
        is_local_lightrag_llm=True,
        seconds_per_chunk_local=90,
    )

    assert local["runtime_profile"] == "local"
    assert local["estimated_lrag_chunks"] == remote["estimated_lrag_chunks"]
    assert local["estimated_duration_seconds_max"] > remote["estimated_duration_seconds_max"]


async def test_registry_chunk_document_uses_lightrag_chunking_func() -> None:
    class Tokenizer:
        def encode(self, text: str) -> list[int]:
            return list(range(len(text)))

    class Rag:
        tokenizer = Tokenizer()
        chunk_overlap_token_size = 1
        chunk_token_size = 4

        def chunking_func(self, tokenizer, text, split, split_only, overlap, size):
            self.call = (text, split, split_only, overlap, size)
            return [{"content": "aa"}, {"content": "bb"}]

    rag = Rag()
    registry = object.__new__(LightRAGCoreRegistry)

    async def get(collection: str):
        assert collection == "papers"
        return rag

    registry.get = get  # type: ignore[method-assign]

    chunks, basis = await registry.chunk_document("papers", "aabb")

    assert chunks == ["aa", "bb"]
    assert basis == "lrag_chunks"
    assert rag.call == ("aabb", None, False, 1, 4)


async def test_registry_insert_custom_kg_calls_official_non_llm_path() -> None:
    class Rag:
        def __init__(self) -> None:
            self.calls: list[tuple[dict, str | None]] = []

        async def ainsert_custom_kg(
            self, custom_kg: dict, full_doc_id: str | None = None
        ) -> None:
            self.calls.append((custom_kg, full_doc_id))

    rag = Rag()
    registry = object.__new__(LightRAGCoreRegistry)
    registry._collection_locks = {}

    async def get(collection: str):
        assert collection == "papers"
        return rag

    registry.get = get  # type: ignore[method-assign]
    payload = {
        "chunks": [{"content": "bounded", "source_id": "task-1"}],
        "entities": [],
        "relationships": [],
    }

    await registry.insert_custom_kg("papers", "doc-1", payload)

    assert rag.calls == [(payload, "doc-1")]


async def test_lightrag_embedding_adapter_returns_numpy_batch() -> None:
    class StubEmbedding:
        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[float(i), float(i + 1)] for i, _ in enumerate(texts)]

    adapter = LightRAGEmbeddingAdapter(
        StubEmbedding(),  # type: ignore[arg-type]
        embedding_dim=2,
        max_token_size=100,
        model_name="stub",
    )
    result = await adapter(["a", "b"])

    assert result.shape == (2, 2)
    assert result.tolist() == [[0.0, 1.0], [1.0, 2.0]]


async def test_registry_query_only_need_context_skips_final_answer(
    monkeypatch,
) -> None:
    class QueryParam:
        def __init__(self, *, mode: str, only_need_context: bool) -> None:
            self.mode = mode
            self.only_need_context = only_need_context

    class Rag:
        async def aquery(self, query: str, *, param: QueryParam) -> str:
            self.call = (query, param)
            return "context only"

    rag = Rag()
    registry = object.__new__(LightRAGCoreRegistry)
    registry._config = GraphConfig(enabled=True, query_mode="mix")
    registry.has_workspace = lambda collection: collection == "papers"  # type: ignore[method-assign]

    async def get(collection: str):
        assert collection == "papers"
        return rag

    registry.get = get  # type: ignore[method-assign]
    monkeypatch.setitem(sys.modules, "lightrag", SimpleNamespace(QueryParam=QueryParam))

    result = await registry.query("papers", "question", only_need_context=True)

    assert result["answer"] == ""
    assert result["context"] == "context only"
    assert rag.call[1].only_need_context is True


async def test_registry_reset_workspace_finalizes_and_deletes_derived_data(
    tmp_path: Path,
) -> None:
    class Rag:
        finalized = False

        async def finalize_storages(self) -> None:
            self.finalized = True

    root = tmp_path / "lightrag"
    workspace = root / "papers_safe"
    workspace.mkdir(parents=True)
    (workspace / "data.json").write_text("{}", encoding="utf-8")
    rag = Rag()
    registry = object.__new__(LightRAGCoreRegistry)
    registry._root = root
    registry._map_path = root / "workspace_map.json"
    registry._workspace_map = {"papers": "papers_safe"}
    registry._instances = {"papers": rag}

    await registry.reset_workspace("papers")

    assert rag.finalized is True
    assert not workspace.exists()
    assert registry._workspace_map == {}
    assert registry._instances == {}


async def test_registry_has_workspace_true_and_false(tmp_path: Path) -> None:
    registry = object.__new__(LightRAGCoreRegistry)
    registry._root = tmp_path / "lr"
    registry._workspace_map = {"papers": "papers_safe"}

    # 目录不存在时 → False
    assert not registry.has_workspace("papers")

    # 创建对应目录后 → True
    (registry._root / "papers_safe").mkdir(parents=True)
    assert registry.has_workspace("papers")

    # map 中不存在的 collection → False
    assert not registry.has_workspace("unknown")


async def test_registry_manual_probe_returns_error_on_init_failure(tmp_path: Path) -> None:
    registry = object.__new__(LightRAGCoreRegistry)
    registry._config = GraphConfig(enabled=True, query_mode="mix")
    registry._root = tmp_path / "lr"
    registry._map_path = registry._root / "workspace_map.json"
    registry._workspace_map = {}
    registry._instances = {}

    async def failing_get(collection: str):
        raise RuntimeError("storage init failed")

    registry.get = failing_get  # type: ignore[method-assign]

    result = await registry.manual_probe(
        collection="test_col", text="hello world", doc_id="doc1", query="what is this?"
    )

    assert result["status"] == "error"
    assert any(
        s["step"] == "initialize_storages" and s["status"] == "error" for s in result["steps"]
    )
