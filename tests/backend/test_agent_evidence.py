"""Agent evidence retrieval contracts: mode budgets and zero plugin-LLM generation."""

from __future__ import annotations

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.config import DeepThinkingConfig, EnhancedRecallConfig
from kacore.domain.models import DocumentChunk, SourceDocument
from kacore.pipelines.agent_evidence import AgentEvidenceOrchestrator
from kacore.pipelines.retrieval_orchestrator import ChunkSignal, RetrievalOutcome
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.reranker.noop import NoopReranker
from kacore.repository.source_store.memory import InMemorySourceDocumentStore


class RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def retrieve_with_outcome(
        self,
        collection: str,
        query: str,
        top_k: int,
        scope=None,
        *,
        candidate_k: int | None = None,
    ) -> RetrievalOutcome:
        self.calls.append(
            {
                "collection": collection,
                "query": query,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "scope": scope,
            }
        )
        chunk = DocumentChunk(
            chunk_id=f"chunk-{len(self.calls)}",
            doc_id="doc-1",
            ordinal=len(self.calls) - 1,
            text=f"evidence for {query}",
            content_hash=f"hash-{len(self.calls)}",
            metadata={"pages": [len(self.calls)]},
        )
        return RetrievalOutcome(
            chunks=[chunk],
            engines=["milvus"],
            per_chunk_signals={
                chunk.chunk_id: ChunkSignal(rrf_score=1.0, anchor_hit=False)
            },
        )


def _orchestrator(retrieval: RecordingRetrieval) -> AgentEvidenceOrchestrator:
    return AgentEvidenceOrchestrator(
        retrieval_orchestrator=retrieval,  # type: ignore[arg-type]
        reranker=NoopReranker(),
        enhanced_config=EnhancedRecallConfig(
            max_sub_queries=3,
            wide_top_k=12,
            max_final_evidence=8,
            corrective_enabled=True,
        ),
        deep_config=DeepThinkingConfig(
            max_sub_queries=4,
            max_rounds=3,
            wide_top_k=15,
            max_final_evidence=10,
        ),
    )


async def test_mode_limits_are_explicit_and_default_rejects_fanout() -> None:
    retrieval = RecordingRetrieval()
    orchestrator = _orchestrator(retrieval)

    assert orchestrator.limits("default") == {
        "max_queries_per_round": 1,
        "max_rounds": 1,
        "max_evidence": 8,
    }
    assert orchestrator.limits("enhanced")["max_rounds"] == 2
    assert orchestrator.limits("deep_thinking")["max_rounds"] == 3

    with pytest.raises(ValueError, match="at most 1 queries"):
        await orchestrator.run(
            mode="default",
            collection="papers",
            queries=["first", "second"],
        )
    assert retrieval.calls == []


async def test_enhanced_runs_agent_queries_without_an_llm_dependency() -> None:
    retrieval = RecordingRetrieval()
    orchestrator = _orchestrator(retrieval)

    result = await orchestrator.run(
        mode="enhanced",
        collection="papers",
        queries=["alpha mechanism", "beta comparison"],
    )

    assert result.queries == ["alpha mechanism", "beta comparison"]
    assert len(result.evidence) == 2
    assert result.engines == ["milvus"]
    assert [call["query"] for call in retrieval.calls] == result.queries
    assert not hasattr(orchestrator, "_llm_adapter")


async def test_api_serializes_compact_evidence_and_never_claims_full_text() -> None:
    retrieval = RecordingRetrieval()
    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument(
            doc_id="doc-1",
            title="Alpha Paper",
            file_path="/data/alpha.pdf",
            content_type="application/pdf",
            size_bytes=1,
            content_hash="hash",
            collection="papers",
        )
    )
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        agent_evidence_orchestrator=_orchestrator(retrieval),
    )

    result = await api.retrieve_agent_evidence(
        question="Explain Alpha",
        queries=["alpha mechanism"],
        collection="papers",
        retrieval_mode="default",
    )

    assert result["actual_retrieval_mode"] == "agent_default"
    assert result["requires_agent_assessment"] is True
    assert result["plugin_llm_used"] is False
    assert result["full_text_used"] is False
    assert result["evidence"][0]["title"] == "Alpha Paper"
    assert result["evidence"][0]["text"] == "evidence for alpha mechanism"


async def test_deep_thinking_evidence_requires_a_collection() -> None:
    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        agent_evidence_orchestrator=_orchestrator(RecordingRetrieval()),
    )
    with pytest.raises(ValueError, match="requires a collection"):
        await api.retrieve_agent_evidence(
            question="Synthesize everything",
            queries=["broad question"],
            retrieval_mode="deep_thinking",
        )
