"""Codex/外部 agent 使用的无生成式 LLM 证据召回编排（pipelines 层）。

该模块只执行已有检索引擎、RRF、可选 cross-encoder reranker 与 adaptive cutoff。
问题拆解、充分性判断、纠偏决策和最终合成都由调用方 agent 完成，绝不调用 LLMAdapter。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kacore.pipelines.deep_thinking_evidence import rank_candidates
from kacore.retrieval_modes import MODE_DEEP_THINKING, MODE_DEFAULT, MODE_ENHANCED
from kacore.utils.cutoff import adaptive_cutoff

if TYPE_CHECKING:
    from kacore.config import DeepThinkingConfig, EnhancedRecallConfig
    from kacore.domain.models import DocumentChunk
    from kacore.pipelines.retrieval_orchestrator import (
        RetrievalOrchestrator,
        RetrievalOutcome,
        RetrievalScope,
    )
    from kacore.repository.reranker.base import Reranker


AGENT_EVIDENCE_MODES = frozenset({MODE_DEFAULT, MODE_ENHANCED, MODE_DEEP_THINKING})


@dataclass
class AgentEvidenceResult:
    """一次 agent 驱动召回轮次的确定性结果。"""

    mode: str
    queries: list[str]
    evidence: list[DocumentChunk]
    kept_chunk_ids: list[str]
    engines: list[str] = field(default_factory=list)
    fallback_reasons: list[str] = field(default_factory=list)
    query_outcomes: list[tuple[str, RetrievalOutcome]] = field(default_factory=list, repr=False)


async def retrieve_many(
    retrieval: RetrievalOrchestrator,
    collection: str,
    queries: list[str],
    scope: RetrievalScope | None,
    *,
    top_k: int,
    candidate_k: int,
) -> list[tuple[str, RetrievalOutcome]]:
    """并行执行多查询召回；单查询失败跳过，全部失败才上抛。"""
    if not queries:
        return []
    outcomes = await asyncio.gather(
        *(
            retrieval.retrieve_with_outcome(
                collection,
                query,
                top_k,
                scope,
                candidate_k=candidate_k,
            )
            for query in queries
        ),
        return_exceptions=True,
    )
    results: list[tuple[str, RetrievalOutcome]] = []
    failures: list[BaseException] = []
    for query, outcome in zip(queries, outcomes):
        if isinstance(outcome, asyncio.CancelledError):
            raise outcome
        if isinstance(outcome, BaseException):
            failures.append(outcome)
        else:
            results.append((query, outcome))
    if not results and failures:
        raise failures[0]
    return results


async def rank_pool(
    query_outcomes: list[tuple[str, RetrievalOutcome]],
    reranker: Reranker,
    *,
    rerank_weight: float,
    max_evidence: int,
) -> tuple[list[DocumentChunk], list[str]]:
    """跨查询合并、保留结构锚点并执行统一重排与 cutoff。"""
    candidates: dict[str, DocumentChunk] = {}
    anchor_ids: set[str] = set()
    for _query, outcome in query_outcomes:
        for chunk in outcome.chunks:
            candidates.setdefault(chunk.chunk_id, chunk)
            signal = outcome.per_chunk_signals.get(chunk.chunk_id)
            if signal and signal.anchor_hit:
                anchor_ids.add(chunk.chunk_id)
    non_pinned = [chunk for cid, chunk in candidates.items() if cid not in anchor_ids]
    scored = await rank_candidates(
        query_outcomes,
        non_pinned,
        anchor_ids,
        reranker,
        rerank_weight,
    )
    kept = adaptive_cutoff(scored, keep_max=max_evidence)
    final: list[DocumentChunk] = []
    seen: set[str] = set()
    for chunk in [candidates[cid] for cid in anchor_ids] + [item.chunk for item in kept]:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        final.append(chunk)
        if len(final) >= max_evidence:
            break
    return final, [chunk.chunk_id for chunk in final]


class AgentEvidenceOrchestrator:
    """按 Ask 模式应用固定证据预算，不承担任何 LLM 规划或合成。"""

    def __init__(
        self,
        *,
        retrieval_orchestrator: RetrievalOrchestrator,
        reranker: Reranker,
        enhanced_config: EnhancedRecallConfig,
        deep_config: DeepThinkingConfig,
    ) -> None:
        self._retrieval = retrieval_orchestrator
        self._reranker = reranker
        self._enhanced = enhanced_config
        self._deep = deep_config

    def update_reranker(self, reranker: Reranker) -> None:
        """热替换共享 reranker。"""
        self._reranker = reranker

    def limits(self, mode: str) -> dict[str, int]:
        """返回 Codex 必须遵守的每轮查询数、轮数和最终证据上限。"""
        if mode == MODE_DEFAULT:
            return {"max_queries_per_round": 1, "max_rounds": 1, "max_evidence": 8}
        if mode == MODE_ENHANCED:
            return {
                "max_queries_per_round": self._enhanced.max_sub_queries + 1,
                "max_rounds": 2 if self._enhanced.corrective_enabled else 1,
                "max_evidence": self._enhanced.max_final_evidence,
            }
        if mode == MODE_DEEP_THINKING:
            return {
                "max_queries_per_round": self._deep.max_sub_queries,
                "max_rounds": self._deep.max_rounds,
                "max_evidence": self._deep.max_final_evidence,
            }
        raise ValueError(f"unsupported agent evidence mode: {mode}")

    async def run(
        self,
        *,
        mode: str,
        collection: str,
        queries: list[str],
        scope: RetrievalScope | None = None,
        prior_outcomes: list[tuple[str, RetrievalOutcome]] | None = None,
    ) -> AgentEvidenceResult:
        """执行一轮由 agent 给定查询的确定性召回。"""
        if mode not in AGENT_EVIDENCE_MODES:
            raise ValueError(f"unsupported agent evidence mode: {mode}")
        clean_queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        limits = self.limits(mode)
        if not clean_queries:
            raise ValueError("at least one evidence query is required")
        if len(clean_queries) > limits["max_queries_per_round"]:
            raise ValueError(
                f"{mode} allows at most {limits['max_queries_per_round']} queries per round"
            )

        if mode == MODE_DEFAULT:
            top_k = max_evidence = limits["max_evidence"]
            candidate_k = top_k * 2
            rerank_weight = 1.0
        elif mode == MODE_ENHANCED:
            top_k = self._enhanced.wide_top_k
            candidate_k = self._enhanced.candidate_k
            max_evidence = self._enhanced.max_final_evidence
            rerank_weight = self._enhanced.rerank_weight
        else:
            top_k = self._deep.wide_top_k
            candidate_k = max(top_k * 2, self._deep.max_final_evidence)
            max_evidence = self._deep.max_final_evidence
            rerank_weight = self._deep.rerank_weight

        current = await retrieve_many(
            self._retrieval,
            collection,
            clean_queries,
            scope,
            top_k=top_k,
            candidate_k=candidate_k,
        )
        combined = list(prior_outcomes or []) + current
        evidence, kept_ids = await rank_pool(
            combined,
            self._reranker,
            rerank_weight=rerank_weight,
            max_evidence=max_evidence,
        )
        engines = list(
            dict.fromkeys(engine for _query, outcome in combined for engine in outcome.engines)
        )
        fallback_reasons = list(
            dict.fromkeys(
                outcome.fallback_reason
                for _query, outcome in combined
                if outcome.fallback_reason
            )
        )
        return AgentEvidenceResult(
            mode=mode,
            queries=clean_queries,
            evidence=evidence,
            kept_chunk_ids=kept_ids,
            engines=engines,
            fallback_reasons=fallback_reasons,
            query_outcomes=combined,
        )


__all__ = [
    "AGENT_EVIDENCE_MODES",
    "AgentEvidenceOrchestrator",
    "AgentEvidenceResult",
    "rank_pool",
    "retrieve_many",
]
