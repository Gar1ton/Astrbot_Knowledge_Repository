"""增强召回编排（pipelines 层，A-RAG「2+1」形态）。

介于 default 与 deep_thinking 之间的中间档：
1. PLAN-lite（1 次 LLM）：改写 + 拆解 ≤N 个互补子查询；
2. 并行混合检索（复用 RetrievalOrchestrator 内核）+ 合并池 cross-encoder 重排 +
   adaptive_cutoff（0 次 LLM，全程不涉 LightRAG）；
3. SYNTH+CHECK（1 次 LLM）：deep 模板合成 + 尾部 verdict 内嵌 CRAG 式充分性自检；
4. 自检不充分且开启纠偏时：并行补检（0 次 LLM）→ 重合成（1 次 LLM，复用同一
   SYNTH+CHECK 契约，产出补检后的真实充分性判定，不是纯文本重写）。

典型 2 次 LLM 调用、最坏 3–4 次（含 JSON 重试）。产出复用 DeepThinkingOutcome——
api.ask 的 deep 下游（sources 组装、兜底合成、告警、trace 序列化）零改动直接消费。
LLM 调用异常优雅回退：PLAN 挂 → 降级单轮 baseline（镜像 deep_degraded 先例）；
SYNTH 挂 → answer=None 由 api.ask 兜底合成；重合成挂 → 保留首轮答案与首轮充分性判定。

verified 语义：直接取「最后一次实际执行的 SYNTH+CHECK 自检」的 sufficient——首轮充分
则用首轮结果；首轮不充分且完成纠偏，则用纠偏轮重新自检的结果（不是把「跑完一轮纠偏」
本身当作「已验证」）；纠偏轮 LLM 不可用时，保留首轮已知的 sufficient/insufficiency_reasons，
不虚报为 True（见 ingest-evidence-upgrade-plan.md 对本文件「纠偏完成即 verified=True」
契约差异的修正要求）。不为此新增独立 VERIFY 调用，复用既有 SYNTH+CHECK 契约即可。
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
from kacore.pipelines.evidence_session import current_evidence_session, evidence_request
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

    @evidence_request
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
        except JsonContractError as exc:
            # calls/tokens 来自异常上携带的重试耗尽前真实消费，不再用重试次数硬编码估算。
            plan_calls = exc.calls
            plan_tokens = exc.tokens
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
            except JsonContractError as exc:
                synth, synth_calls = None, exc.calls
                total_tokens += exc.tokens
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
        session = current_evidence_session.get()
        has_actions = session.request_actions(synth.actions) if session else False
        needs_corrective = (
            not synth.sufficient
            and self._cfg.corrective_enabled
            and (bool(synth.corrective_queries) or has_actions)
            and (total_tokens
                 + est_tokens(build_synth_check_prompt(final_question, evidence, labels))
                 + self._cfg.output_reserve < self._cfg.token_budget)
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

        # 阶段5：一轮纠正检索（0 次 LLM）→ 重合成（1 次 LLM，复用 SYNTH+CHECK 契约，
        # 产出纠偏后的真实充分性判定，而不是纯文本重写）。
        corrective = synth.corrective_queries[: self._cfg.max_corrective_queries]
        _progress("enhanced_corrective", 78, live_detail("round", checklist, trace))
        query_outcomes.extend(await self._retrieve_many(collection, corrective, scope))
        # 首轮答案的 [n] 是按**纠正前**证据池编号的；重合成失败时必须连同证据池一起回滚，
        # 否则返回的答案与证据错位。v1.1.0 起 [n] 会被改写成含作者姓名的 Harvard 短引，
        # 错位不再只是「点错来源卡片」，而是正文明文把 A 的结论归给 B。
        first_round_evidence, first_round_kept_ids = evidence, kept_ids
        evidence, kept_ids = await self._rank_pool(query_outcomes)
        _progress("enhanced_resynthesize", 88, live_detail("finalize", checklist, trace))
        answer = synth.answer
        # 默认沿用首轮已知的充分性判定；只有纠偏轮成功产出新 verdict 才覆盖——绝不能把
        # 「跑完一轮纠偏」本身当作「已验证」（修正原有 verified=True 的契约差异）。
        resynth_sufficient = synth.sufficient
        resynth_reasons = synth.insufficiency_reasons
        resynth_calls = 0
        try:
            labels = await self._retrieval.document_labels(c.doc_id for c in evidence)
            resynth, resynth_calls, resynth_tokens = await llm_json_call(
                self._llm,
                build_synth_check_prompt(final_question, evidence, labels),
                build_synth_check_system(answer_language, self._cfg.max_corrective_queries),
                parse_synth_check,
                self._cfg.json_max_retries,
                retry_suffix=SYNTH_CHECK_RETRY_SUFFIX,
            )
            total_tokens += resynth_tokens
            if resynth.answer:
                answer = resynth.answer
                resynth_sufficient = resynth.sufficient
                resynth_reasons = resynth.insufficiency_reasons
            else:
                evidence, kept_ids = first_round_evidence, first_round_kept_ids
        except JsonContractError as exc:
            # 重试耗尽前的真实消费不能丢；无法产出新 verdict，沿用首轮已知判定。
            total_tokens += exc.tokens
            resynth_calls = exc.calls
            logger.warning("enhanced_recall re-synthesis JSON contract failed: %s", exc)
            evidence, kept_ids = first_round_evidence, first_round_kept_ids
        except Exception as exc:  # 重合成不可用 → 保留首轮答案 + 首轮证据池，不打崩。
            logger.warning("enhanced_recall re-synthesis unavailable: %s", exc)
            evidence, kept_ids = first_round_evidence, first_round_kept_ids
        trace.append(
            RoundTrace(
                round=2,
                queries=list(corrective),
                gaps=list(resynth_reasons),
                kept_chunk_ids=kept_ids,
                llm_calls=resynth_calls,
                est_tokens=total_tokens - trace[0].est_tokens,
            )
        )
        return self._outcome(
            evidence,
            checklist,
            trace,
            base_mode,
            total_tokens,
            answer=answer,
            verified=resynth_sufficient,
            verify_notes=resynth_reasons,
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
        session = current_evidence_session.get()
        if session is not None:
            # 传入的是累积列表，只吸收新增轮次；同轮的 seen 在 gather 后才变更。
            session.absorb(query_outcomes[len(session.outcomes):])
            final = await session.select(
                self._reranker, limit=self._cfg.max_final_evidence,
                weight=self._cfg.rerank_weight,
                pinned=set(session.requested_reads),
            )
            store = getattr(self._retrieval, "_source_store", None)
            if store is not None:
                final = await session.expand(final, store, limit=self._cfg.max_final_evidence)
            return final, [c.chunk_id for c in final]
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
        answer_generation_status: str = "",
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
            answer_generation_status=answer_generation_status,
            verified=verified,
            verify_missing=[],
            verify_notes=list(verify_notes or []),
        )


__all__ = ["EnhancedRecallOrchestrator", "MODE_ENHANCED", "MODE_ENHANCED_DEGRADED"]
