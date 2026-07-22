"""增强召回编排（pipelines 层，A-RAG「2+1」形态）。

介于 default 与 deep_thinking 之间的中间档：
1. PLAN-lite（1 次 LLM）：改写 + 拆解 ≤N 个互补子查询；
2. 并行混合检索（复用 RetrievalOrchestrator 内核）+ 合并池 cross-encoder 重排 +
   adaptive_cutoff（0 次 LLM，全程不涉 LightRAG）；
3. SYNTH+CHECK（1 次 LLM）：deep 模板合成 + 尾部 verdict 内嵌 CRAG 式充分性自检；
4. 自检不充分且开启纠偏时：并行补检（0 次 LLM）→ 重合成（1 次 LLM）。

典型 2 次 LLM 调用、最坏 3–4 次（含 JSON 重试）。产出复用 DeepThinkingOutcome——
api.ask 的 deep 下游（sources 组装、兜底合成、告警、trace 序列化）零改动直接消费。
LLM 调用异常优雅回退：PLAN 挂 → 降级单轮 baseline（镜像 deep_degraded 先例）；
SYNTH 挂 → answer=None 由 api.ask 兜底合成；重合成挂 → 保留首轮答案。

verified 语义（有意决策）：首轮自检充分 → verified=True；不充分但完成一轮纠偏 →
verified=True + verify_notes 携带 insufficiency_reasons（透明进「思考过程」，
不堆正文告警墙）——一轮纠偏即本模式的设计闭环，不做 deep 式多轮 claim 级审计。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kacore.domain.deep_thinking import Checklist, DeepThinkingOutcome, RoundTrace
from kacore.pipelines.agent_evidence import (
    rank_pool as rank_agent_pool,
)
from kacore.pipelines.agent_evidence import (
    retrieve_many as retrieve_agent_many,
)
from kacore.pipelines.answer_synthesis import synthesize_answer
from kacore.pipelines.deep_thinking_prompts import JsonContractError
from kacore.pipelines.deep_thinking_view import live_detail
from kacore.pipelines.enhanced_recall_prompts import (
    PLAN_LITE_SYSTEM,
    SYNTH_CHECK_RETRY_SUFFIX,
    SynthCheckResult,
    build_plan_lite_prompt,
    build_synth_check_prompt,
    build_synth_check_system,
    parse_plan_lite,
    parse_synth_check,
)
from kacore.pipelines.llm_json import est_tokens, llm_json_call

if TYPE_CHECKING:
    from kacore.adapters.llm import LLMAdapter
    from kacore.config import EnhancedRecallConfig, RerankConfig
    from kacore.domain.models import DocumentChunk
    from kacore.pipelines.retrieval_orchestrator import (
        RetrievalOrchestrator,
        RetrievalOutcome,
        RetrievalScope,
    )
    from kacore.repository.reranker.base import Reranker

logger = logging.getLogger("EnhancedRecall")

# baseline 保底证据条数：PLAN LLM 挂掉时至少回退到这批单轮高分证据（与 deep 对齐）。
_BASELINE_FLOOR_N = 5

# actual_mode 两态（杜绝魔法字面量散落）。
MODE_ENHANCED = "enhanced_recall"
MODE_ENHANCED_DEGRADED = "enhanced_degraded_to_default"


class EnhancedRecallOrchestrator:
    """增强召回编排器。构造器注入依赖，不读全局单例。"""

    def __init__(
        self,
        *,
        retrieval_orchestrator: RetrievalOrchestrator,
        reranker: Reranker,
        llm_adapter: LLMAdapter,
        er_config: EnhancedRecallConfig,
        rerank_config: RerankConfig,
    ) -> None:
        self._retrieval = retrieval_orchestrator
        self._reranker = reranker
        self._llm = llm_adapter
        self._cfg = er_config
        self._rerank_cfg = rerank_config

    def update_reranker(self, reranker: Reranker, rerank_config: RerankConfig) -> None:
        """热替换 reranker，供数据流 AB test 即时切换使用（与 deep 对齐）。"""
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
        progress: Callable[[str, int, dict[str, Any] | None], None] | None = None,
        answer_language: str = "auto",
        answer_question: str | None = None,
    ) -> DeepThinkingOutcome:
        def _progress(stage: str, pct: int, detail: dict[str, Any] | None = None) -> None:
            if progress is not None:
                progress(stage, pct, detail)

        final_question = answer_question or query
        checklist = Checklist()
        trace: list[RoundTrace] = []
        total_tokens = 0

        # 阶段1：PLAN-lite（1 次 LLM）。LLM 异常 → 降级单轮 baseline；JSON 坏 → 用原 query。
        _progress("enhanced_plan", 10, live_detail("plan", checklist, trace))
        rewritten = ""
        subs: list[str] = []
        plan_calls = plan_tokens = 0
        try:
            (rewritten, subs), plan_calls, plan_tokens = await llm_json_call(
                self._llm,
                build_plan_lite_prompt(query, self._cfg.max_sub_queries),
                PLAN_LITE_SYSTEM,
                parse_plan_lite,
                self._cfg.json_max_retries,
            )
        except JsonContractError:
            plan_calls = self._cfg.json_max_retries + 1
        except Exception as exc:  # LLM 调用异常/不可用 → 回退单轮 baseline。
            logger.warning("enhanced_recall PLAN-lite llm unavailable: %s", exc)
            return await self._degraded(collection, query, scope, reason=str(exc))
        total_tokens += plan_tokens

        queries: list[str] = []
        for q in [rewritten or query, *subs]:
            if q and q not in queries:
                queries.append(q)
        queries = queries[: self._cfg.max_sub_queries + 1]

        # 阶段2：并行混合检索 + 合并池重排 + cutoff（0 次 LLM）。
        _progress("enhanced_retrieve", 30, live_detail("round", checklist, trace))
        query_outcomes = await self._retrieve_many(collection, queries, scope)
        evidence, kept_ids = await self._rank_pool(query_outcomes)
        base_mode = MODE_ENHANCED

        # 阶段3：SYNTH+CHECK（1 次 LLM）。LLM 异常 → answer=None，api.ask 兜底合成。
        _progress("enhanced_synthesize", 60, live_detail("round", checklist, trace))
        labels = await self._retrieval.document_labels(c.doc_id for c in evidence)
        synth: SynthCheckResult | None = None
        synth_calls = 0
        if evidence:
            try:
                synth, synth_calls, synth_tokens = await llm_json_call(
                    self._llm,
                    build_synth_check_prompt(final_question, evidence, labels),
                    build_synth_check_system(
                        answer_language, self._cfg.max_corrective_queries
                    ),
                    parse_synth_check,
                    self._cfg.json_max_retries,
                    retry_suffix=SYNTH_CHECK_RETRY_SUFFIX,
                )
                total_tokens += synth_tokens
            except JsonContractError:
                synth, synth_calls = None, self._cfg.json_max_retries + 1
            except Exception as exc:
                logger.warning("enhanced_recall SYNTH llm unavailable: %s", exc)
                synth, synth_calls = None, 1
        trace.append(
            RoundTrace(
                round=1,
                queries=list(queries),
                kept_chunk_ids=kept_ids,
                llm_calls=plan_calls + synth_calls,
                est_tokens=total_tokens,
            )
        )
        if synth is None:
            # 无证据或合成不可用：答案交 api.ask 兜底（default 风格），证据保留。
            return self._outcome(
                evidence, checklist, trace, base_mode, total_tokens, answer=None
            )

        # 阶段4：充分 / 纠偏关闭 / 无补检 query → 直接返回。
        needs_corrective = (
            not synth.sufficient
            and self._cfg.corrective_enabled
            and bool(synth.corrective_queries)
        )
        if not needs_corrective:
            return self._outcome(
                evidence,
                checklist,
                trace,
                base_mode,
                total_tokens,
                answer=synth.answer,
                verified=synth.sufficient,
                verify_notes=synth.insufficiency_reasons,
            )

        # 阶段5：一轮纠正检索（0 次 LLM）→ 重合成（1 次 LLM，纯文本无 verdict）。
        corrective = synth.corrective_queries[: self._cfg.max_corrective_queries]
        _progress("enhanced_corrective", 78, live_detail("round", checklist, trace))
        query_outcomes.extend(await self._retrieve_many(collection, corrective, scope))
        evidence, kept_ids = await self._rank_pool(query_outcomes)
        _progress("enhanced_resynthesize", 88, live_detail("finalize", checklist, trace))
        answer = synth.answer
        resynth_calls = 0
        try:
            labels = await self._retrieval.document_labels(c.doc_id for c in evidence)
            draft = await synthesize_answer(
                self._llm,
                final_question,
                evidence,
                answer_language,
                style="deep",
                source_labels=labels,
            )
            resynth_calls = 1
            total_tokens += est_tokens(
                final_question, draft, *(c.text for c in evidence)
            )
            if draft:
                answer = draft
        except Exception as exc:  # 重合成不可用 → 保留首轮答案，不打崩。
            logger.warning("enhanced_recall re-synthesis unavailable: %s", exc)
        trace.append(
            RoundTrace(
                round=2,
                queries=list(corrective),
                gaps=list(synth.insufficiency_reasons),
                kept_chunk_ids=kept_ids,
                llm_calls=resynth_calls,
                est_tokens=total_tokens - trace[0].est_tokens,
            )
        )
        # 一轮纠偏即本模式设计闭环 → verified=True；缺口原因透明进 verify_notes。
        return self._outcome(
            evidence,
            checklist,
            trace,
            base_mode,
            total_tokens,
            answer=answer,
            verified=True,
            verify_notes=synth.insufficiency_reasons,
        )

    # ── 内部 helper ─────────────────────────────────────────
    async def _retrieve_many(
        self,
        collection: str,
        queries: list[str],
        scope: RetrievalScope | None,
    ) -> list[tuple[str, RetrievalOutcome]]:
        """并行执行各 query 的混合召回（宽候选池，不传内核 reranker——重排统一在合并池做）。"""
        return await retrieve_agent_many(
            self._retrieval,
            collection,
            queries,
            scope,
            top_k=self._cfg.wide_top_k,
            candidate_k=self._cfg.candidate_k,
        )

    async def _rank_pool(
        self, query_outcomes: list[tuple[str, RetrievalOutcome]]
    ) -> tuple[list[DocumentChunk], list[str]]:
        """合并各 query 候选池：anchor pinned 前置无条件保留，非 pinned 经
        rank_candidates（rrf×cross-encoder 混合）+ adaptive_cutoff，总量截 max_final_evidence。
        """
        return await rank_agent_pool(
            query_outcomes,
            self._reranker,
            rerank_weight=self._cfg.rerank_weight,
            max_evidence=self._cfg.max_final_evidence,
        )

    async def _degraded(
        self,
        collection: str,
        query: str,
        scope: RetrievalScope | None,
        reason: str,
    ) -> DeepThinkingOutcome:
        """PLAN LLM 不可用的降级路径：单轮混合召回取前 N 当证据（镜像 deep_degraded 先例）。"""
        baseline = await self._retrieval.retrieve_with_outcome(
            collection, query, self._cfg.wide_top_k, scope
        )
        return DeepThinkingOutcome(
            evidence=list(baseline.chunks[:_BASELINE_FLOOR_N]),
            checklist=Checklist(),
            trace=[],
            degraded=True,
            actual_mode=MODE_ENHANCED_DEGRADED,
            est_total_tokens=0,
            degraded_reason=reason,
        )

    @staticmethod
    def _outcome(
        evidence: list[DocumentChunk],
        checklist: Checklist,
        trace: list[RoundTrace],
        actual_mode: str,
        est_total_tokens: int,
        *,
        answer: str | None,
        verified: bool = False,
        verify_notes: list[str] | None = None,
    ) -> DeepThinkingOutcome:
        return DeepThinkingOutcome(
            evidence=evidence,
            checklist=checklist,
            trace=trace,
            degraded=False,
            actual_mode=actual_mode,
            est_total_tokens=est_total_tokens,
            answer=answer,
            verified=verified,
            verify_missing=[],
            verify_notes=list(verify_notes or []),
        )


__all__ = ["EnhancedRecallOrchestrator", "MODE_ENHANCED", "MODE_ENHANCED_DEGRADED"]
