"""Deep Thinking 迭代检索编排（pipelines 层，FAIR-RAG 循环）。

在不重写混合召回内核的前提下，于其上层做：baseline 先行 → PLAN 分解 → 多轮
（检索 → pinned 结构保护 → 重排截断 → SEA 审计 → REFINE 补检）→ 收敛或回退。
verification 关闭时只产出证据/清单/轨迹，合成由 api.ask 负责；verification 开启时额外
做「合成 draft → 校验 → 不合格则补检再合成」闭环并产出 answer。LLM 调用异常一律优雅
回退（baseline 或退回 api.ask 合成），绝不打崩请求；JSON 不合格则按步降级。
"""
from __future__ import annotations

import asyncio
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
from core.pipelines.deep_thinking_evidence import rank_candidates, select_final_evidence
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
from core.pipelines.deep_thinking_view import live_detail
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

    def update_reranker(self, reranker: Reranker, rerank_config: RerankConfig) -> None:
        """热替换 reranker，供数据流 AB test 即时切换使用。"""
        self._reranker = reranker
        self._rerank_cfg = rerank_config

    @property
    def reranker_status(self) -> dict[str, str | bool | None]:
        return self._reranker.status

    async def run(
        self,
        collection: str,
        query: str,
        scope: RetrievalScope | None = None,
        progress: Callable[[str, int, dict | None], None] | None = None,
        answer_language: str = "auto",
        answer_question: str | None = None,
    ) -> DeepThinkingOutcome:
        def _progress(stage: str, pct: int, detail: dict | None = None) -> None:
            if progress is not None:
                progress(stage, pct, detail)

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
        # PLAN 完成 → 推送信息点清单，前端即可先看到「拆解出哪些信息点」。
        _progress("deep_plan", 25, live_detail("plan", checklist, trace))

        evidence: dict[str, EvidenceItem] = {}
        pinned_ids: set[str] = set()
        conflicting_ids: set[str] = set()
        sufficient = False
        # 软项：SEA 的非关键 gap，仅入「思考过程」展示，不进正文告警（不堆告警墙）。
        soft_gaps: list[str] = []
        # 已开放式发现并入 checklist 的 aspect 累计数（受 max_discovered_total 限）。
        discovered_total = 0

        for rnd in range(1, self._cfg.max_rounds + 1):
            round_pct = min(30 + rnd * 15, 80)

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
                if gap not in soft_gaps:
                    soft_gaps.append(gap)
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
            # 本轮 SEA 审计完成 → 增量推送该轮 trace，前端逐轮可见推演过程。
            _progress(f"deep_round_{rnd}", round_pct, live_detail("round", checklist, trace))

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
        _progress("deep_finalize", 90, live_detail("finalize", checklist, trace))
        final = select_final_evidence(
            evidence, pinned_ids, conflicting_ids, self._cfg.max_final_evidence
        )
        if not final:
            return self._degraded(
                baseline_floor, trace, est_tokens,
                checklist=checklist,
                reason="无最终证据",
            )
        # 关键检查项未满足是硬缺失（代表回答必需的信息点真缺）——计入正文告警。
        hard_notes: list[str] = []
        for item in checklist.items:
            if item.critical and not item.satisfied:
                text = item.why_missing or item.text
                msg = f"关键检查项未满足：{text}"
                if msg not in hard_notes:
                    hard_notes.append(msg)

        # 阶段4：答案级 verification 闭环（可选）。合成 draft → 校验 → 不合格补检再合成。
        # verify_missing=硬项（计入正文告警）；verify_notes=软项（仅入「思考过程」展示）。
        answer: str | None = None
        verified = False
        verify_missing: list[str] = list(hard_notes)
        verify_notes: list[str] = list(soft_gaps)
        if self._cfg.verify_enabled:
            try:
                (
                    answer, qualified, v_hard, v_soft, final, est_tokens
                ) = await self._run_verification(
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
                verify_missing = self._merge_missing(hard_notes, v_hard)
                verify_notes = self._merge_missing(soft_gaps, v_soft)
                verified = qualified and not verify_missing
            except Exception as exc:  # 兜底：verify 任何异常都不打崩，退回 api.ask 合成。
                logger.warning("deep_thinking verification failed: %s", exc)
                answer, verified = None, False
                verify_missing, verify_notes = list(hard_notes), list(soft_gaps)

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
            verify_notes=verify_notes,
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
        # 多个 sub_query 检索彼此独立 → 并发执行（纯提速、不改语义；gather 保序）。
        query_outcomes: list[tuple[str, RetrievalOutcome]] = []
        if include_baseline is not None:
            query_outcomes.append((query, include_baseline))
        if queries:
            outcomes = await asyncio.gather(
                *(
                    self._retrieval.retrieve_with_outcome(
                        collection, q, self._cfg.wide_top_k, scope
                    )
                    for q in queries
                )
            )
            query_outcomes.extend(zip(queries, outcomes))
        candidates: dict[str, DocumentChunk] = {}
        anchor_ids: set[str] = set()
        for _q, oc in query_outcomes:
            for chunk in oc.chunks:
                candidates.setdefault(chunk.chunk_id, chunk)
                sig = oc.per_chunk_signals.get(chunk.chunk_id)
                if sig and sig.anchor_hit:
                    anchor_ids.add(chunk.chunk_id)
        non_pinned = [c for cid, c in candidates.items() if cid not in anchor_ids]
        scored = await rank_candidates(
            query_outcomes, non_pinned, anchor_ids, self._reranker, self._cfg.rerank_weight
        )
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
    ) -> tuple[str | None, bool, list[str], list[str], list[DocumentChunk], int]:
        """合成 draft → 校验 → 不合格则用软项当 gap 补检再合成，受 max_verify_rounds 限。

        返回 (answer, qualified, hard_missing, soft_notes, final_evidence, est_tokens)。
        qualified = supported ∧ complete ∧ 无硬违规（partial/info_gap 不阻塞）。
        合成不可用 → answer=None（退回 api.ask）；校验不可用 → 用 draft、qualified=False。
        """
        answer = ""
        hard: list[str] = []
        soft: list[str] = []
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
                return None, False, hard, soft, final, est_tokens
            if not draft:
                return None, False, hard, soft, final, est_tokens
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
                return answer, False, [], [], final, est_tokens
            except Exception as exc:  # 校验 LLM 不可用 → 用 draft，标记未校验。
                logger.warning("deep_thinking VERIFY llm unavailable: %s", exc)
                return answer, False, [], [], final, est_tokens
            hard = verify_result.hard_missing
            soft = verify_result.soft_notes
            qualified = verify_result.supported and verify_result.complete and not hard
            recheck_gaps = soft or hard
            if qualified or vround == self._cfg.max_verify_rounds or not recheck_gaps:
                return answer, qualified, hard, soft, final, est_tokens
            # 不合格且有轮次 + 有补充方向：软/硬项当 gap 再检索补证据，重算 final。
            await self._gather_round(
                collection,
                retrieval_query,
                recheck_gaps[: self._cfg.max_sub_queries],
                scope,
                [],
                evidence,
                pinned_ids,
                include_baseline=None,
            )
            final = select_final_evidence(
                evidence, pinned_ids, conflicting_ids, self._cfg.max_final_evidence
            )
        return answer, False, hard, soft, final, est_tokens

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
