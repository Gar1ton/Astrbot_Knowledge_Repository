from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from core.config import GraphConfig
from core.domain.models import DocumentChunk, SourceDocument
from core.lightrag_core import (
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
    assert "实际 LLM 调用次数和耗时可能更高" in result["estimate_notice"]


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
