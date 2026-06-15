"""Deep Thinking 迭代检索编排（pipelines 层，FAIR-RAG 循环）。

在不重写混合召回内核的前提下，于其上层做：baseline 先行 → PLAN 分解 → 多轮
（检索 → pinned 结构保护 → 重排截断 → SEA 审计 → REFINE 补检）→ 收敛或回退。
verification 关闭时只产出证据/清单/轨迹，合成由 api.ask 负责；verification 开启时额外
做「合成 draft → 校验 → 不合格则补检再合成」闭环并产出 answer。LLM 调用异常一律优雅
回退（baseline 或退回 api.ask 合成），绝不打崩请求；JSON 不合格则按步降级。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from core.domain.deep_thinking import (
    Checklist,
    ChecklistItem,
    DeepThinkingOutcome,
    EvidenceItem,
    RoundTrace,
)
from core.pipelines.answer_synthesis import synthesize_answer
from core.pipelines.deep_thinking_prompts import (
    PLAN_SYSTEM,
    REFINE_SYSTEM,
    SEA_SYSTEM,
    VERIFY_SYSTEM,
    JsonContractError,
    SeaDiscoveredItem,
    SeaResult,
    build_plan_prompt,
    build_refine_prompt,
    build_sea_prompt,
    build_verify_prompt,
    parse_plan,
    parse_refine,
    parse_sea,
    parse_verify,
)
from core.repository.reranker.base import ScoredChunk
from core.utils.cutoff import adaptive_cutoff

if TYPE_CHECKING:
    from core.adapters.llm import LLMAdapter
    from core.config import DeepThinkingConfig, RerankConfig
    from core.domain.models import DocumentChunk
    from core.pipelines.retrieval_orchestrator import (
        RetrievalOrchestrator,
        RetrievalOutcome,
        RetrievalScope,
    )
    from core.repository.reranker.base import Reranker

logger = logging.getLogger("DeepThinking")

T = TypeVar("T")

# baseline 保底证据条数：LLM 全挂或迭代失败时至少回退到这批单轮高分证据。
_BASELINE_FLOOR_N = 5

# actual_mode 三态（杜绝魔法字面量散落）。
MODE_MILVUS_DEEP = "milvus_deep"
MODE_ASTRBOT_DEEP_FALLBACK = "astrbot_deep_fallback"
MODE_DEGRADED = "deep_degraded_to_default"


def _est_tokens(*texts: str) -> int:
    """字符近似的 token 估算（≈ len/4）。非精确，仅用于成本可观测与安全阀。"""
    return sum(len(t) for t in texts) // 4


def _minmax(value: float, lo: float, hi: float) -> float:
    """把 value 线性归一化到 [0,1]；区间退化（hi<=lo）返回 0，避免除零。"""
    if hi <= lo:
        return 0.0
    return (value - lo) / (hi - lo)


class DeepThinkingOrchestrator:
    """FAIR-RAG 式迭代检索的编排器。构造器注入依赖，不读全局单例。"""

    def __init__(
        self,
        *,
        retrieval_orchestrator: RetrievalOrchestrator,
        reranker: Reranker,
        llm_adapter: LLMAdapter,
        dt_config: DeepThinkingConfig,
        rerank_config: RerankConfig,
    ) -> None:
        self._retrieval = retrieval_orchestrator
        self._reranker = reranker
        self._llm = llm_adapter
        self._cfg = dt_config
        self._rerank_cfg = rerank_config

    async def run(
        self,
        collection: str,
        query: str,
        scope: RetrievalScope | None = None,
        progress: Callable[[str, int], None] | None = None,
        answer_language: str = "auto",
        answer_question: str | None = None,
    ) -> DeepThinkingOutcome:
        def _progress(stage: str, pct: int) -> None:
            if progress is not None:
                progress(stage, pct)

        # 阶段0：baseline 先行（纯 embedding+SQL，无 LLM）——LLM 全挂也能据此回退。
        final_question = answer_question or query
        _progress("deep_baseline", 10)
        baseline_outcome = await self._retrieval.retrieve_with_outcome(
            collection, query, self._cfg.wide_top_k, scope
        )
        baseline_floor = list(baseline_outcome.chunks[:_BASELINE_FLOOR_N])
        base_mode = (
            MODE_MILVUS_DEEP
            if "milvus" in baseline_outcome.engines
            else MODE_ASTRBOT_DEEP_FALLBACK
        )

        est_tokens = 0
        calls_used = 0  # 全局 LLM 调用计数（PLAN+SEA+REFINE），call_budget 安全阀以此为准。
        trace: list[RoundTrace] = []

        # 阶段1：PLAN（合并 checklist + sub_queries）。
        _progress("deep_plan", 20)
        try:
            (items, sub_queries), plan_calls, tokens = await self._llm_json(
                build_plan_prompt(query, self._cfg.max_sub_queries), PLAN_SYSTEM, parse_plan
            )
            est_tokens += tokens
            calls_used += plan_calls
        except JsonContractError:
            items = [ChecklistItem(id="c0", text=query, critical=True)]
            sub_queries = [query]
        except Exception as exc:  # LLM 调用异常/不可用 → 回退 baseline。
            logger.warning("deep_thinking PLAN llm unavailable: %s", exc)
            return self._degraded(baseline_floor, trace, est_tokens, reason=str(exc))

        checklist = Checklist(items=items)
        queries = sub_queries[: self._cfg.max_sub_queries] or [query]

        evidence: dict[str, EvidenceItem] = {}
        pinned_ids: set[str] = set()
        conflicting_ids: set[str] = set()
        sufficient = False
        soft_missing: list[str] = []
        # 已开放式发现并入 checklist 的 aspect 累计数（受 max_discovered_total 限）。
        discovered_total = 0

        for rnd in range(1, self._cfg.max_rounds + 1):
            _progress(f"deep_round_{rnd}", min(30 + rnd * 15, 80))

            # 2a-2e 检索 → pinned 保护 → rerank+cutoff → 累积证据（round1 并入 baseline）。
            kept_ids = await self._gather_round(
                collection,
                query,
                queries,
                scope,
                baseline_floor,
                evidence,
                pinned_ids,
                include_baseline=baseline_outcome if rnd == 1 else None,
            )

            # 2f SEA。每条证据标注来源文档，防跨文档知识串线。
            ev_items = list(evidence.values())
            sea_labels = await self._retrieval.document_labels(
                it.chunk.doc_id for it in ev_items
            )
            try:
                sea, round_calls, round_tokens = await self._llm_json(
                    build_sea_prompt(
                        query,
                        checklist,
                        ev_items,
                        self._cfg.sea_evidence_clip,
                        sea_labels,
                    ),
                    SEA_SYSTEM,
                    parse_sea,
                )
            except JsonContractError:
                sea, round_calls, round_tokens = SeaResult(sufficient=False), 1, 0
            except Exception as exc:  # LLM 调用异常 → 回退 baseline。
                logger.warning("deep_thinking SEA llm unavailable: %s", exc)
                return self._degraded(baseline_floor, trace, est_tokens, reason=str(exc))

            checklist.apply_satisfied(sea.satisfied_ids)
            self._apply_coverage(checklist, sea)
            conflicting_ids |= sea.conflicting_chunk_ids
            for gap in sea.gaps:
                if gap not in soft_missing:
                    soft_missing.append(gap)
            fallback_refine_gaps = self._checklist_refine_gaps(checklist)
            # 开放式发现：新 aspect 追加为非 critical checklist 项，**不进** soft_missing/告警。
            round_discovered = self._absorb_discovered(checklist, sea.discovered, discovered_total)
            discovered_total += len(round_discovered)
            sufficient = sea.sufficient
            est_tokens += round_tokens
            calls_used += round_calls
            trace.append(
                RoundTrace(
                    round=rnd,
                    queries=list(queries),
                    gaps=list(sea.gaps or fallback_refine_gaps),
                    discovered=round_discovered,
                    kept_chunk_ids=kept_ids,
                    llm_calls=round_calls,
                    est_tokens=round_tokens,
                )
            )

            # 2g 收敛 / 预算安全阀。本轮有新发现则再追一轮深挖（即便 sufficient）。
            converged = (
                sufficient
                and not round_discovered
                and not self._has_unmet_critical(checklist)
            )
            if converged or rnd == self._cfg.max_rounds or self._over_budget(
                calls_used, est_tokens
            ):
                break

            # 2h REFINE（discovered 优先驱动深挖，其次填 typed gaps）。
            try:
                refine_gaps = round_discovered + (
                    self._refine_gaps(sea) or sea.gaps or fallback_refine_gaps
                )
                gap_queries, refine_calls, tokens = await self._llm_json(
                    build_refine_prompt(refine_gaps), REFINE_SYSTEM, parse_refine
                )
                est_tokens += tokens
                calls_used += refine_calls
                queries = gap_queries[: self._cfg.max_sub_queries] or [query]
            except JsonContractError:
                break
            except Exception as exc:
                logger.warning("deep_thinking REFINE llm unavailable: %s", exc)
                return self._degraded(baseline_floor, trace, est_tokens, reason=str(exc))

        # 阶段3：循环后一次性过滤非 pinned 的 conflicting；只有无证据才硬降级。
        _progress("deep_finalize", 90)
        final = self._compute_final(evidence, pinned_ids, conflicting_ids)
        if not final:
            return self._degraded(
                baseline_floor, trace, est_tokens,
                checklist=checklist,
                reason="无最终证据",
            )
        for item in checklist.items:
            if item.critical and not item.satisfied:
                text = item.why_missing or item.text
                msg = f"关键检查项未满足：{text}"
                if msg not in soft_missing:
                    soft_missing.append(msg)

        # 阶段4：答案级 verification 闭环（可选）。合成 draft → 校验 → 不合格补检再合成。
        answer: str | None = None
        verified = False
        verify_missing: list[str] = list(soft_missing)
        if self._cfg.verify_enabled:
            try:
                answer, verified, verify_missing, final, est_tokens = await self._run_verification(
                    collection,
                    query,
                    final_question,
                    answer_language,
                    scope,
                    final,
                    evidence,
                    pinned_ids,
                    conflicting_ids,
                    est_tokens,
                )
                verify_missing = self._merge_missing(soft_missing, verify_missing)
                verified = verified and not verify_missing
            except Exception as exc:  # 兜底：verify 任何异常都不打崩，退回 api.ask 合成。
                logger.warning("deep_thinking verification failed: %s", exc)
                answer, verified, verify_missing = None, False, list(soft_missing)

        return DeepThinkingOutcome(
            evidence=final,
            checklist=checklist,
            trace=trace,
            degraded=False,
            actual_mode=base_mode,
            est_total_tokens=est_tokens,
            answer=answer,
            verified=verified,
            verify_missing=verify_missing,
        )

    # ── 内部 helper ─────────────────────────────────────────
    @staticmethod
    def _merge_missing(first: list[str], second: list[str]) -> list[str]:
        merged: list[str] = []
        for item in first + second:
            if item and item not in merged:
                merged.append(item)
        return merged

    @staticmethod
    def _has_unmet_critical(checklist: Checklist) -> bool:
        """只要 critical 项未被 SEA/coverage 支持，就不能把本轮视为真正收敛。"""
        return any(item.critical and not item.satisfied for item in checklist.items)

    @staticmethod
    def _checklist_refine_gaps(checklist: Checklist) -> list[str]:
        """SEA 未给 gaps 时，从未满足的 critical/coverage 项反推可检索补检输入。"""
        gaps: list[str] = []
        for item in checklist.items:
            status = item.status.lower()
            needs_refine = status in {"partial", "missing", "contradicted"} or (
                item.critical and not item.satisfied
            )
            if not needs_refine:
                continue
            pieces = [
                " ".join(item.search_hints[:3]),
                item.evidence_type,
                item.why_missing or item.next_action,
                item.text,
            ]
            text = " | ".join(piece for piece in pieces if piece)
            if text and text not in gaps:
                gaps.append(text)
        return gaps

    @staticmethod
    def _apply_coverage(checklist: Checklist, sea: SeaResult) -> None:
        """把 SEA coverage matrix 回填到 checklist，供 trace/API 展示与关键项判定复用。"""
        by_id = {item.id: item for item in checklist.items}
        for coverage in sea.coverage:
            item = by_id.get(coverage.checklist_id)
            if item is None:
                continue
            item.status = coverage.status
            item.supporting_chunk_ids = list(coverage.supporting_chunk_ids)
            item.confidence = coverage.confidence
            item.why_missing = coverage.why_missing
            item.next_action = coverage.next_action
            if coverage.status == "supported":
                item.satisfied = True

    @staticmethod
    def _refine_gaps(sea: SeaResult) -> list[str]:
        """优先把 typed coverage 缺口转为 REFINE 输入；旧格式无 coverage 时返回空。"""
        gaps: list[str] = []
        for coverage in sea.coverage:
            if coverage.status not in {"partial", "missing", "contradicted"}:
                continue
            pieces = [
                coverage.gap_type or coverage.next_action,
                coverage.gap_query or coverage.why_missing,
            ]
            text = "：".join(piece for piece in pieces if piece)
            if text and text not in gaps:
                gaps.append(text)
        return gaps

    def _absorb_discovered(
        self,
        checklist: Checklist,
        discovered: list[SeaDiscoveredItem],
        total_so_far: int,
    ) -> list[str]:
        """把 SEA 新发现的 aspect 去重后追加为非 critical checklist 项（双重上限约束）。

        返回本轮真正新增的 aspect 文本（供 trace 与 REFINE 深挖）。这些项是探索性的，
        **不进** soft_missing/verify_missing/正文告警，避免开放式深挖重造告警墙。
        """
        existing = {item.text.strip() for item in checklist.items}
        added: list[str] = []
        remaining = self._cfg.max_discovered_total - total_so_far
        for item in discovered:
            if len(added) >= self._cfg.max_discovered_per_round or len(added) >= remaining:
                break
            text = item.text.strip()
            if not text or text in existing:
                continue
            existing.add(text)
            checklist.items.append(
                ChecklistItem(
                    id=f"d{total_so_far + len(added) + 1}",
                    text=text,
                    critical=False,
                    origin="discovered",
                    status="missing",
                    search_hints=list(item.search_hints),
                    why_missing=item.why_relevant,
                )
            )
            added.append(text)
        return added

    async def _gather_round(
        self,
        collection: str,
        query: str,
        queries: list[str],
        scope: RetrievalScope | None,
        baseline_floor: list[DocumentChunk],
        evidence: dict[str, EvidenceItem],
        pinned_ids: set[str],
        *,
        include_baseline: RetrievalOutcome | None,
    ) -> list[str]:
        """一轮检索：sub_queries 检索 → pinned 结构保护 → per-aspect 排序+cutoff → 累积进 evidence。

        pinned（anchor_hit）与 baseline_floor 无条件保留；非 pinned 以「每个 sub_query 的
        rrf_score 取 max」为主排序信号（reranker 可缺席），再经 cutoff。返回本轮保留的
        chunk_id 列表（供 trace）。
        """
        query_outcomes: list[tuple[str, RetrievalOutcome]] = []
        if include_baseline is not None:
            query_outcomes.append((query, include_baseline))
        for q in queries:
            query_outcomes.append(
                (
                    q,
                    await self._retrieval.retrieve_with_outcome(
                        collection, q, self._cfg.wide_top_k, scope
                    ),
                )
            )
        candidates: dict[str, DocumentChunk] = {}
        anchor_ids: set[str] = set()
        for _q, oc in query_outcomes:
            for chunk in oc.chunks:
                candidates.setdefault(chunk.chunk_id, chunk)
                sig = oc.per_chunk_signals.get(chunk.chunk_id)
                if sig and sig.anchor_hit:
                    anchor_ids.add(chunk.chunk_id)
        non_pinned = [c for cid, c in candidates.items() if cid not in anchor_ids]
        scored = await self._rank_non_pinned(query_outcomes, non_pinned, anchor_ids)
        kept = adaptive_cutoff(scored, keep_max=self._cfg.deep_keep)
        for cid in anchor_ids:
            evidence.setdefault(cid, EvidenceItem(candidates[cid], "structural_anchor"))
            pinned_ids.add(cid)
        for chunk in baseline_floor:
            evidence.setdefault(chunk.chunk_id, EvidenceItem(chunk, "baseline_floor"))
        for sc in kept:
            evidence.setdefault(
                sc.chunk.chunk_id, EvidenceItem(sc.chunk, "rerank_score", sc.score)
            )
        return list(anchor_ids) + [sc.chunk.chunk_id for sc in kept]

    async def _rank_non_pinned(
        self,
        query_outcomes: list[tuple[str, RetrievalOutcome]],
        non_pinned: list[DocumentChunk],
        anchor_ids: set[str],
    ) -> list[ScoredChunk]:
        """以「每个 sub_query 的 rrf_score 取 max」为主信号给非 pinned 候选打分排序。

        无真实 reranker（rerank_weight=0 或 reranker.is_passthrough）时纯按 rrf 排序——
        让被任一 aspect 强召回的具体机制 chunk 浮出，而非退化为候选插入顺序。
        rerank_weight>0 且 reranker 非 passthrough 时，**按 query 分池** rerank（每个 query
        只 rerank 自己召回的池，避免 max_candidates 跨 query 截断），逐池取 max 后与归一化
        rrf 线性混合。返回按分数降序的 ScoredChunk。
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

        if self._cfg.rerank_weight <= 0.0 or self._reranker.is_passthrough:
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
            for sc in await self._reranker.rerank(q, pool):
                cid = sc.chunk.chunk_id
                if sc.score > rerank.get(cid, float("-inf")):
                    rerank[cid] = sc.score

        rrf_vals = [rrf.get(c.chunk_id, 0.0) for c in non_pinned]
        rr_vals = [rerank.get(c.chunk_id, 0.0) for c in non_pinned]
        rrf_lo, rrf_hi = min(rrf_vals), max(rrf_vals)
        rr_lo, rr_hi = min(rr_vals), max(rr_vals)
        w = self._cfg.rerank_weight
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

    def _compute_final(
        self, evidence: dict[str, EvidenceItem], pinned_ids: set[str], conflicting_ids: set[str]
    ) -> list[DocumentChunk]:
        """循环后过滤 conflicting，并按证据角色/分数/doc 多样性截断。"""
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
        limit = max(1, self._cfg.max_final_evidence)
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

    async def _run_verification(
        self,
        collection: str,
        retrieval_query: str,
        answer_question: str,
        answer_language: str,
        scope: RetrievalScope | None,
        final: list[DocumentChunk],
        evidence: dict[str, EvidenceItem],
        pinned_ids: set[str],
        conflicting_ids: set[str],
        est_tokens: int,
    ) -> tuple[str | None, bool, list[str], list[DocumentChunk], int]:
        """合成 draft → 校验 → 不合格则 missing 当 gap 补检再合成，受 max_verify_rounds 限。

        返回 (answer, verified, missing, final_evidence, est_tokens)。合成 LLM 不可用 →
        answer=None（退回 api.ask 合成）；校验 LLM 不可用 → 用当前 draft、verified=False。
        """
        answer = ""
        verified = False
        missing: list[str] = []
        for vround in range(self._cfg.max_verify_rounds + 1):
            # 每条证据标注来源文档，合成与校验同享，防跨文档知识串线。
            source_labels = await self._retrieval.document_labels(c.doc_id for c in final)
            try:
                draft = await synthesize_answer(
                    self._llm,
                    answer_question,
                    final,
                    answer_language,
                    style="deep",
                    source_labels=source_labels,
                )
            except Exception as exc:  # 合成 LLM 不可用 → 放弃 verify，让 api.ask 兜底合成。
                logger.warning("deep_thinking synth-for-verify unavailable: %s", exc)
                return None, False, missing, final, est_tokens
            if not draft:
                return None, False, missing, final, est_tokens
            answer = draft
            est_tokens += _est_tokens(answer_question, draft, *(chunk.text for chunk in final))
            try:
                verify_result, _, vtokens = await self._llm_json(
                    build_verify_prompt(
                        answer_question,
                        draft,
                        final,
                        self._cfg.verify_evidence_clip,
                        source_labels,
                    ),
                    VERIFY_SYSTEM,
                    parse_verify,
                )
                est_tokens += vtokens
            except JsonContractError:
                return answer, False, [], final, est_tokens
            except Exception as exc:  # 校验 LLM 不可用 → 用 draft，标记未校验。
                logger.warning("deep_thinking VERIFY llm unavailable: %s", exc)
                return answer, False, [], final, est_tokens
            missing = verify_result.missing
            qualified = verify_result.supported and verify_result.complete
            if qualified or vround == self._cfg.max_verify_rounds or not missing:
                return answer, qualified, missing, final, est_tokens
            # 不合格且有轮次 + 有补充方向：missing 当 gap 再检索补证据，重算 final。
            await self._gather_round(
                collection,
                retrieval_query,
                missing[: self._cfg.max_sub_queries],
                scope,
                [],
                evidence,
                pinned_ids,
                include_baseline=None,
            )
            final = self._compute_final(evidence, pinned_ids, conflicting_ids)
        return answer, verified, missing, final, est_tokens

    async def _llm_json(
        self, prompt: str, system: str, parse_fn: Callable[[str], T]
    ) -> tuple[T, int, int]:
        """调 LLM 并解析 JSON：JSON 不合格重试 json_max_retries 次后抛 JsonContractError；
        LLM 调用异常向上抛（由 run 捕获回退）。返回 (parsed, calls, est_tokens)。"""
        calls = 0
        tokens = 0
        last_err: JsonContractError | None = None
        for attempt in range(self._cfg.json_max_retries + 1):
            text = prompt if attempt == 0 else prompt + "\n\n只输出合法 JSON，不要任何额外文字。"
            raw = await self._llm.generate(text, system_prompt=system, allow_mock=False)
            calls += 1
            tokens += _est_tokens(system, text, raw)
            try:
                return parse_fn(raw), calls, tokens
            except JsonContractError as exc:
                last_err = exc
        raise last_err or JsonContractError("unparseable")

    def _over_budget(self, calls_used: int, est_tokens: int) -> bool:
        """call_budget 以全局 calls_used（PLAN+SEA+REFINE 真实调用数）为准，替代旧的
        「仅 trace 内 SEA 调用」口径，避免安全阀名义与实际不一致。VERIFY/合成的调用
        另由 max_verify_rounds 限界，不计入本闸门。"""
        return calls_used >= self._cfg.call_budget or est_tokens >= self._cfg.token_budget

    def _degraded(
        self,
        baseline_floor: list[DocumentChunk],
        trace: list[RoundTrace],
        est_tokens: int,
        checklist: Checklist | None = None,
        reason: str = "",
    ) -> DeepThinkingOutcome:
        """统一回退：final_evidence 严格等于 baseline_floor（不带入探索证据）。"""
        return DeepThinkingOutcome(
            evidence=list(baseline_floor),
            checklist=checklist or Checklist(),
            trace=trace,
            degraded=True,
            actual_mode=MODE_DEGRADED,
            est_total_tokens=est_tokens,
            degraded_reason=reason,
        )


__all__ = ["DeepThinkingOrchestrator"]
