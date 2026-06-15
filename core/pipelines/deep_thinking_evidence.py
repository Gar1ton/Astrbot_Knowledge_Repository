"""Deep Thinking 证据打分与最终选取（pipelines 层）。

从编排器剥离的无状态纯函数：① 给非 pinned 候选打分排序（每个 sub_query 的 rrf_score 取 max
为主信号，可选 reranker 按 query 分池加权混合）；② 循环后按证据角色/分数/doc 多样性选出
final evidence。剥离的目的：让 orchestrator 只关心控制流，并使排序/选取逻辑可独立单测与复用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.repository.reranker.base import ScoredChunk

if TYPE_CHECKING:
    from core.domain.deep_thinking import EvidenceItem
    from core.domain.models import DocumentChunk
    from core.pipelines.retrieval_orchestrator import RetrievalOutcome
    from core.repository.reranker.base import Reranker


def _minmax(value: float, lo: float, hi: float) -> float:
    """把 value 线性归一化到 [0,1]；区间退化（hi<=lo）返回 0，避免除零。"""
    if hi <= lo:
        return 0.0
    return (value - lo) / (hi - lo)


async def rank_candidates(
    query_outcomes: list[tuple[str, RetrievalOutcome]],
    non_pinned: list[DocumentChunk],
    anchor_ids: set[str],
    reranker: Reranker,
    rerank_weight: float,
) -> list[ScoredChunk]:
    """以「每个 sub_query 的 rrf_score 取 max」为主信号给非 pinned 候选打分排序。

    无真实 reranker（rerank_weight<=0 或 reranker.is_passthrough）时纯按 rrf 排序——让被任一
    aspect 强召回的具体机制 chunk 浮出，而非退化为候选插入顺序。否则**按 query 分池** rerank
    （每个 query 只 rerank 自己召回的池，避免 max_candidates 跨 query 截断），逐池取 max 后与
    归一化 rrf 线性混合。返回按分数降序的 ScoredChunk。
    """
    if not non_pinned:
        return []
    # 主信号：跨命中它的 query 取最大 rrf_score。
    rrf: dict[str, float] = {}
    for _q, oc in query_outcomes:
        for cid, sig in oc.per_chunk_signals.items():
            if cid in anchor_ids:
                continue
            if sig.rrf_score > rrf.get(cid, float("-inf")):
                rrf[cid] = sig.rrf_score

    if rerank_weight <= 0.0 or reranker.is_passthrough:
        scored = [ScoredChunk(chunk=c, score=rrf.get(c.chunk_id, 0.0)) for c in non_pinned]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return scored

    # 可选 rerank：按 query 分池打分，逐 chunk 取跨 query 最高 rerank 分。
    id_to_chunk = {c.chunk_id: c for c in non_pinned}
    rerank: dict[str, float] = {}
    for q, oc in query_outcomes:
        pool = [id_to_chunk[c.chunk_id] for c in oc.chunks if c.chunk_id in id_to_chunk]
        if not pool:
            continue
        for sc in await reranker.rerank(q, pool):
            cid = sc.chunk.chunk_id
            if sc.score > rerank.get(cid, float("-inf")):
                rerank[cid] = sc.score

    rrf_vals = [rrf.get(c.chunk_id, 0.0) for c in non_pinned]
    rr_vals = [rerank.get(c.chunk_id, 0.0) for c in non_pinned]
    rrf_lo, rrf_hi = min(rrf_vals), max(rrf_vals)
    rr_lo, rr_hi = min(rr_vals), max(rr_vals)
    w = rerank_weight
    blended = [
        ScoredChunk(
            chunk=c,
            score=(1 - w) * _minmax(rrf.get(c.chunk_id, 0.0), rrf_lo, rrf_hi)
            + w * _minmax(rerank.get(c.chunk_id, 0.0), rr_lo, rr_hi),
        )
        for c in non_pinned
    ]
    blended.sort(key=lambda sc: sc.score, reverse=True)
    return blended


def select_final_evidence(
    evidence: dict[str, EvidenceItem],
    pinned_ids: set[str],
    conflicting_ids: set[str],
    max_final_evidence: int,
) -> list[DocumentChunk]:
    """循环后过滤非 pinned 的 conflicting，并按证据角色/分数/doc 多样性截断。

    角色优先级：anchor/pinned(0) > baseline_floor(1) > rerank_score(2)；同角色内按分数降序，
    多 doc 时轮转选择以降低单篇文献垄断。
    """
    ranked: list[tuple[int, float, int, EvidenceItem]] = []
    for index, item in enumerate(evidence.values()):
        chunk_id = item.chunk.chunk_id
        if chunk_id not in pinned_ids and chunk_id in conflicting_ids:
            continue
        if chunk_id in pinned_ids or item.kept_reason == "structural_anchor":
            role_rank = 0
        elif item.kept_reason == "baseline_floor":
            role_rank = 1
        else:
            role_rank = 2
        score = item.rerank_score if item.rerank_score is not None else 0.0
        ranked.append((role_rank, -score, index, item))
    ranked.sort(key=lambda row: row[:3])
    limit = max(1, max_final_evidence)
    selected: list[EvidenceItem] = []
    for role_rank in sorted({row[0] for row in ranked}):
        rows = [row for row in ranked if row[0] == role_rank]
        doc_order: list[str] = []
        buckets: dict[str, list[tuple[int, float, int, EvidenceItem]]] = {}
        for row in rows:
            doc_id = row[3].chunk.doc_id
            if doc_id not in buckets:
                buckets[doc_id] = []
                doc_order.append(doc_id)
            buckets[doc_id].append(row)
        if len(buckets) <= 1:
            selected.extend(row[3] for row in rows[: limit - len(selected)])
        else:
            while buckets and len(selected) < limit:
                for doc_id in list(doc_order):
                    bucket = buckets.get(doc_id)
                    if not bucket:
                        continue
                    selected.append(bucket.pop(0)[3])
                    if not bucket:
                        buckets.pop(doc_id, None)
                        doc_order.remove(doc_id)
                    if len(selected) >= limit:
                        break
        if len(selected) >= limit:
            break
    return [item.chunk for item in selected]


__all__ = ["rank_candidates", "select_final_evidence"]
