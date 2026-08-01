"""DeepThinkingOrchestrator 的 FAIR-RAG 循环契约测试。

用脚本化 LLM（返回固定 JSON 或抛异常）+ NoopReranker + mock 检索，离线覆盖：
收敛、LLM 调用异常回退 baseline、critical 未满足回退、conflicting 循环后过滤、
JSON 不合格重试降级、达 max_rounds 正常返回。
"""
from __future__ import annotations

import pytest

from kacore.config import DeepThinkingConfig, RerankConfig
from kacore.domain.deep_thinking import Checklist, ChecklistItem, EvidenceItem
from kacore.domain.models import DocumentChunk
from kacore.pipelines.deep_thinking_evidence import select_final_evidence
from kacore.pipelines.deep_thinking_orchestrator import DeepThinkingOrchestrator
from kacore.pipelines.deep_thinking_prompts import (
    build_plan_prompt,
    build_sea_prompt,
    build_verify_prompt,
    parse_plan,
    parse_sea,
    parse_verify,
)
from kacore.pipelines.retrieval_orchestrator import ChunkSignal, RetrievalOutcome
from kacore.repository.reranker.noop import NoopReranker

# ── 脚本化 JSON 响应 ────────────────────────────────────────
PLAN_1ITEM = '{"checklist":[{"id":"c1","text":"方法","critical":false}],"sub_queries":["q1"]}'
PLAN_3ITEM = (
    '{"checklist":[{"id":"c1","text":"A","critical":false},'
    '{"id":"c2","text":"B","critical":false},'
    '{"id":"c3","text":"C","critical":false}],"sub_queries":["q1"]}'
)
PLAN_CRITICAL = '{"checklist":[{"id":"c1","text":"必需","critical":true}],"sub_queries":["q1"]}'
PLAN_ENHANCED = (
    '{"answer_outline":["定义","对比"],"must_have_evidence":["direct_quote"],'
    '"search_hints":["T14"],'
    '"checklist":[{"id":"c1","text":"定义核心概念","critical":true,'
    '"evidence_type":"definition","search_hints":["concept"]}],'
    '"sub_queries":[{"query":"concept definition","type":"keyword"}]}'
)
SEA_SUFFICIENT = '{"satisfied_ids":["c1"],"gaps":[],"conflicting_chunk_ids":[],"sufficient":true}'
SEA_COVERAGE_PARTIAL = (
    '{"coverage":[{"checklist_id":"c1","status":"supported","supporting_chunk_ids":["c1"],'
    '"confidence":0.9},{"checklist_id":"c2","status":"partial","supporting_chunk_ids":["c2"],'
    '"confidence":0.4,"why_missing":"缺少原文定义","next_action":"direct_quote",'
    '"gap_query":"exact definition quote"}],"satisfied_ids":[],"gaps":[],'
    '"conflicting_chunk_ids":[],"sufficient":false}'
)
SEA_INSUFF_SMALLGAP = (
    '{"satisfied_ids":["c1","c2"],"gaps":[{"checklist_id":"c3","text":"缺C"}],'
    '"conflicting_chunk_ids":[],"sufficient":false}'
)
SEA_INSUFF_NOGAP = (
    '{"satisfied_ids":[],"gaps":[],"conflicting_chunk_ids":[],"sufficient":false}'
)
SEA_ONE_ITEM_MULTI_GAPS = (
    '{"satisfied_ids":[],"gaps":["缺定义","缺原文"],"conflicting_chunk_ids":[],'
    '"sufficient":false}'
)
SEA_CONFLICT = (
    '{"satisfied_ids":["c1"],"gaps":[],"conflicting_chunk_ids":["c2"],"sufficient":true}'
)
SEA_TRUE_NO_SATISFIED = (
    '{"satisfied_ids":[],"gaps":[],"conflicting_chunk_ids":[],"sufficient":true}'
)
# v0.30.0：REFINE 并入 SEA——insufficient 时 SEA 直接携带下一轮补检 next_sub_queries。
SEA_INSUFF_WITH_NEXT = (
    '{"satisfied_ids":[],"gaps":["缺C"],"conflicting_chunk_ids":[],"sufficient":false,'
    '"next_sub_queries":[{"query":"Paper X Table 3","type":"section_anchor"}]}'
)


# ── 测试替身 ────────────────────────────────────────────────
def _chunk(cid: str) -> DocumentChunk:
    return DocumentChunk(cid, "doc1", 0, f"text of {cid}", f"h-{cid}")


def _doc_chunk(cid: str, doc_id: str) -> DocumentChunk:
    return DocumentChunk(cid, doc_id, 0, f"text of {cid}", f"h-{cid}")


def _outcome(chunks: list[DocumentChunk], anchor_ids: set[str] = frozenset()) -> RetrievalOutcome:
    signals = {
        c.chunk_id: ChunkSignal(rrf_score=1.0 / (i + 1), anchor_hit=c.chunk_id in anchor_ids)
        for i, c in enumerate(chunks)
    }
    return RetrievalOutcome(chunks=list(chunks), engines=["milvus"], per_chunk_signals=signals)


class MockRetrieval:
    def __init__(self, outcome: RetrievalOutcome) -> None:
        self._outcome = outcome
        self.queries: list[str] = []
        # 记录每次 document_labels 实际请求的 doc_id（验证跨轮缓存只查缺失项）。
        self.label_requests: list[list[str]] = []

    async def retrieve_with_outcome(self, collection, query, top_k, scope=None):
        self.queries.append(query)
        return self._outcome

    async def document_labels(self, doc_ids):
        ids = [d for d in doc_ids if d]
        self.label_requests.append(ids)
        return {d: d for d in ids}


class SequenceRetrieval:
    def __init__(self, outcomes: list[RetrievalOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.queries: list[str] = []

    async def retrieve_with_outcome(self, collection, query, top_k, scope=None):
        self.queries.append(query)
        if len(self._outcomes) > 1:
            return self._outcomes.pop(0)
        return self._outcomes[0]

    async def document_labels(self, doc_ids):
        return {d: d for d in doc_ids if d}


class ScriptedLLM:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    async def generate(self, prompt, system_prompt="", *, allow_mock=True):
        result = await self.generate_result(prompt, system_prompt, allow_mock=allow_mock)
        return result.text

    async def generate_result(self, prompt, system_prompt="", *, allow_mock=True):
        from kacore.domain.llm_generation import GenerationResult

        self.calls += 1
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return GenerationResult(text=item)


def _make(outcome, responses, **cfg_over):
    # 默认关 verify，聚焦 loop 行为；verify 闭环由专门用例覆盖。
    dt_defaults = dict(
        max_rounds=1, max_sub_queries=2, wide_top_k=5, json_max_retries=1, verify_enabled=False
    )
    dt_defaults.update(cfg_over)
    return DeepThinkingOrchestrator(
        retrieval_orchestrator=MockRetrieval(outcome),
        reranker=NoopReranker(),
        llm_adapter=ScriptedLLM(responses),
        dt_config=DeepThinkingConfig(**dt_defaults),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )


# ── 用例 ────────────────────────────────────────────────────
def test_parse_plan_accepts_enhanced_schema():
    items, queries = parse_plan(PLAN_ENHANCED)
    assert queries == ["concept definition"]
    assert items[0].evidence_type == "definition"
    assert items[0].search_hints == ["concept"]
    assert items[0].critical is True


def test_parse_sea_coverage_matrix_derives_legacy_fields():
    sea = parse_sea(SEA_COVERAGE_PARTIAL)
    assert sea.satisfied_ids == {"c1"}
    assert sea.gaps == ["exact definition quote"]
    assert sea.coverage[1].status == "partial"
    assert sea.coverage[1].next_action == "direct_quote"
    assert sea.coverage[1].confidence == 0.4


def test_parse_verify_splits_hard_and_soft():
    # 旧契约向后兼容：missing→info_gaps（软）；missing_citations→并入 citation_mismatches（硬）。
    result = parse_verify(VERIFY_CLAIM_BAD)
    assert result.supported is False
    assert result.complete is False
    assert result.unsupported_claims == ["断言A无证据"]
    assert result.citation_mismatches == ["[2]不支持断言C", "断言B缺引用"]
    assert result.contradictions == ["断言D与证据冲突"]
    assert result.info_gaps == ["缺少背景"]
    # 硬项（违规）进告警；软项（信息缺口）仅供展示，不堆告警墙。
    assert result.hard_missing == [
        "断言A无证据",
        "[2]不支持断言C",
        "断言B缺引用",
        "断言D与证据冲突",
    ]
    assert result.soft_notes == ["缺少背景"]


def test_parse_verify_three_tier_partial_is_soft():
    raw = (
        '{"supported":true,"complete":true,"unsupported_claims":[],'
        '"citation_mismatches":[],"contradictions":[],'
        '"partial_claims":["范式转变为有据推断"],"info_gaps":["缺X定义"]}'
    )
    result = parse_verify(raw)
    assert result.supported is True
    assert result.hard_missing == []
    assert result.soft_notes == ["范式转变为有据推断", "缺X定义"]


def test_prompt_contracts_include_reliability_constraints():
    plan = build_plan_prompt("纵观这批文献，比较数据集和模型", 4)
    sea = build_sea_prompt(
        "比较多篇论文",
        Checklist(items=[ChecklistItem(id="c1", text="跨论文结论")]),
        [EvidenceItem(_doc_chunk("a1", "docA"), "rerank_score")],
        max_next_queries=3,
    )
    verify = build_verify_prompt("q", "answer [1]", [_doc_chunk("a1", "docA")])

    assert "arXiv id" in plan
    assert "数据集名" in plan and "模型名" in plan and "表格/图/章节锚点" in plan
    assert "单一来源证据不得支撑跨来源结论" in sea
    assert "partial 或 contradicted" in sea
    # REFINE 并入 SEA：补检 query 契约（关键词化、上限、sufficient=true 给空数组）在 SEA prompt 中。
    assert "next_sub_queries" in sea
    assert "1~3" in sea
    assert all(term in sea for term in ["论文名", "方法名", "数据集名", "模型名"])
    assert "断言、引用编号和该编号实际来源" in verify


@pytest.mark.asyncio
async def test_converges_when_sea_sufficient():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch = _make(outcome, [PLAN_1ITEM, SEA_SUFFICIENT])
    result = await orch.run("papers", "综述问题")
    assert result.degraded is False
    assert result.actual_mode == "milvus_deep"
    assert len(result.evidence) > 0
    assert result.checklist.items[0].satisfied is True
    # 正常收敛时 degraded_reason 为空。
    assert result.degraded_reason == ""


@pytest.mark.asyncio
async def test_llm_unavailable_degrades_to_baseline():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch = _make(outcome, [RuntimeError("no real llm")])
    result = await orch.run("papers", "综述问题")
    assert result.degraded is True
    assert result.actual_mode == "deep_degraded_to_default"
    # degraded 时 evidence 严格等于 baseline_floor。
    assert [c.chunk_id for c in result.evidence] == ["c1", "c2", "c3"]
    # degraded_reason 应携带原始异常信息，方便前端展示诊断。
    assert result.degraded_reason == "no real llm"


@pytest.mark.asyncio
async def test_sea_llm_unavailable_degrades_to_baseline():
    """PLAN 成功，SEA LLM 失败 → 同样回退 baseline 并携带原因。"""
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make(outcome, [PLAN_1ITEM, RuntimeError("sea llm down")])
    result = await orch.run("papers", "综述问题")
    assert result.degraded is True
    assert result.actual_mode == "deep_degraded_to_default"
    assert [c.chunk_id for c in result.evidence] == ["c1", "c2"]
    assert result.degraded_reason == "sea llm down"


@pytest.mark.asyncio
async def test_second_round_sea_llm_unavailable_degrades_to_baseline():
    """round1 SEA insufficient（确定性兜底续轮），round2 SEA LLM 失败 → 回退 baseline。

    REFINE 并入 SEA 后，「补检后 LLM 失败」的降级路径由第二轮 SEA 承担。
    """
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch = _make(
        outcome,
        [PLAN_3ITEM, SEA_INSUFF_SMALLGAP, RuntimeError("sea llm down in round 2")],
        max_rounds=2,
    )
    result = await orch.run("papers", "综述问题")
    assert result.degraded is True
    assert result.degraded_reason == "sea llm down in round 2"


@pytest.mark.asyncio
async def test_critical_unmet_returns_partial_evidence_without_degrade():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch = _make(outcome, [PLAN_CRITICAL, SEA_INSUFF_NOGAP])
    result = await orch.run("papers", "综述问题")
    assert result.degraded is False
    assert result.actual_mode == "milvus_deep"
    assert [c.chunk_id for c in result.evidence] == ["c1", "c2", "c3"]
    assert result.verified is False
    assert result.verify_missing == ["关键检查项未满足：必需"]
    assert result.degraded_reason == ""


@pytest.mark.asyncio
async def test_sufficient_with_unmet_critical_refines_instead_of_converging():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_CRITICAL, SEA_TRUE_NO_SATISFIED, SEA_SUFFICIENT])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=2,
            max_sub_queries=2,
            wide_top_k=5,
            json_max_retries=1,
            verify_enabled=False,
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )

    result = await orch.run("papers", "综述问题")

    assert len(result.trace) == 2
    assert result.degraded is False
    # SEA 未给 next_sub_queries → 确定性兜底：未满足 critical 项反推为补检 query。
    assert "必需" in retrieval.queries
    assert result.trace[0].gaps == ["必需"]


@pytest.mark.asyncio
async def test_progress_pushes_incremental_round_detail():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    events: list[tuple[str, int, dict | None]] = []
    orch = _make(outcome, [PLAN_1ITEM, SEA_SUFFICIENT])
    await orch.run(
        "papers",
        "综述",
        progress=lambda stage, pct, detail: events.append((stage, pct, detail)),
    )
    # PLAN 后推送带 checklist 的 detail；某轮 SEA 后推送带 rounds 的增量 trace。
    plan_details = [d for s, _, d in events if s == "deep_plan" and d]
    assert plan_details and plan_details[0]["checklist"]
    round_details = [d for s, _, d in events if s.startswith("deep_round") and d]
    assert round_details and round_details[-1]["rounds"][0]["round"] == 1


@pytest.mark.asyncio
async def test_explicit_gaps_return_partial_evidence_without_degrade():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make(outcome, [PLAN_1ITEM, SEA_ONE_ITEM_MULTI_GAPS])
    result = await orch.run("papers", "综述问题")
    assert result.degraded is False
    # 非关键 SEA gap 不再进正文告警，改入软项 verify_notes（仅供「思考过程」展示）。
    assert result.verify_missing == []
    assert result.verify_notes == ["缺定义", "缺原文"]
    assert result.degraded_reason == ""


@pytest.mark.asyncio
async def test_conflicting_filtered_but_pinned_kept():
    # c1 命中结构锚点 → pinned；SEA 把 c1、c2 标 conflicting。
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")], anchor_ids={"c1"})
    orch = _make(outcome, [PLAN_1ITEM, SEA_CONFLICT])
    result = await orch.run("papers", "综述问题")
    ids = {c.chunk_id for c in result.evidence}
    assert result.degraded is False
    assert "c1" in ids  # pinned 的 conflicting 仍保留。
    assert "c2" not in ids  # 非 pinned 的 conflicting 被过滤。
    assert "c3" in ids


@pytest.mark.asyncio
async def test_sea_json_invalid_retries_then_continues():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    llm = ScriptedLLM([PLAN_1ITEM, "not json", "still not json"])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=MockRetrieval(outcome),
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=1, json_max_retries=1, wide_top_k=5, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    result = await orch.run("papers", "综述问题")
    # PLAN(1) + SEA 重试 2 次 = 3 次调用；不崩溃、非 critical 不回退。
    assert llm.calls == 3
    assert result.degraded is False


@pytest.mark.asyncio
async def test_reaches_max_rounds_without_degrade():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch = _make(
        outcome,
        [PLAN_3ITEM, SEA_INSUFF_SMALLGAP, SEA_INSUFF_SMALLGAP],
        max_rounds=2,
    )
    result = await orch.run("papers", "综述问题")
    # 小 gap 比例（1/3 < 0.5）、无 critical → 达 max_rounds 仍正常返回。
    assert result.degraded is False
    assert len(result.trace) == 2


@pytest.mark.asyncio
async def test_final_evidence_can_exceed_baseline_floor_but_is_capped():
    baseline = _outcome([_chunk(f"c{i}") for i in range(1, 6)])
    expanded_chunks = [_chunk(f"c{i}") for i in range(6, 21)]
    expanded = _outcome(expanded_chunks, anchor_ids={chunk.chunk_id for chunk in expanded_chunks})
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=SequenceRetrieval([baseline, expanded]),
        reranker=NoopReranker(),
        llm_adapter=ScriptedLLM([PLAN_1ITEM, SEA_SUFFICIENT]),
        dt_config=DeepThinkingConfig(
            max_rounds=1,
            max_sub_queries=2,
            wide_top_k=20,
            json_max_retries=1,
            verify_enabled=False,
            max_final_evidence=8,
        ),
        rerank_config=RerankConfig(provider="noop", keep=20),
    )

    result = await orch.run("papers", "综述问题")

    assert result.degraded is False
    assert len(result.evidence) == 8
    assert {chunk.chunk_id for chunk in result.evidence} - {f"c{i}" for i in range(1, 6)}


def test_compute_final_interleaves_documents_within_same_role():
    chunks = [
        _doc_chunk("a1", "docA"),
        _doc_chunk("a2", "docA"),
        _doc_chunk("a3", "docA"),
        _doc_chunk("b1", "docB"),
        _doc_chunk("c1", "docC"),
    ]
    evidence = {
        chunk.chunk_id: EvidenceItem(chunk, "rerank_score", 1.0 / (i + 1))
        for i, chunk in enumerate(chunks)
    }

    final = select_final_evidence(evidence, set(), set(), max_final_evidence=4)

    assert [chunk.doc_id for chunk in final] == ["docA", "docB", "docC", "docA"]


def test_compute_final_keeps_structural_anchor_before_doc_interleaving():
    anchor = _doc_chunk("anchor", "docA")
    other = _doc_chunk("b1", "docB")
    evidence = {
        anchor.chunk_id: EvidenceItem(anchor, "structural_anchor", 0.1),
        other.chunk_id: EvidenceItem(other, "rerank_score", 1.0),
    }

    final = select_final_evidence(evidence, {"anchor"}, set(), max_final_evidence=1)

    assert [chunk.chunk_id for chunk in final] == ["anchor"]


@pytest.mark.asyncio
async def test_sea_coverage_updates_checklist_and_typed_gap_drives_next_round():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_3ITEM, SEA_COVERAGE_PARTIAL, SEA_SUFFICIENT])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=2,
            max_sub_queries=2,
            wide_top_k=5,
            json_max_retries=1,
            verify_enabled=False,
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )

    result = await orch.run("papers", "综述问题")

    assert result.checklist.items[0].status == "supported"
    assert result.checklist.items[0].supporting_chunk_ids == ["c1"]
    assert result.checklist.items[1].status == "partial"
    assert result.checklist.items[1].why_missing == "缺少原文定义"
    # typed coverage 缺口（gap_type：gap_query）作为确定性兜底直接进入下一轮检索。
    assert "direct_quote：exact definition quote" in retrieval.queries


# ── verification 闭环 ───────────────────────────────────────
VERIFY_OK = '{"supported":true,"complete":true,"missing":[]}'
VERIFY_BAD = '{"supported":false,"complete":false,"missing":["缺X"]}'
VERIFY_CLAIM_BAD = (
    '{"supported":false,"complete":false,"missing":["缺少背景"],'
    '"unsupported_claims":["断言A无证据"],"missing_citations":["断言B缺引用"],'
    '"citation_mismatches":["[2]不支持断言C"],"contradictions":["断言D与证据冲突"]}'
)


def _make_verify(outcome, responses, **cfg_over):
    cfg = dict(
        max_rounds=1, max_sub_queries=2, wide_top_k=5, json_max_retries=1, verify_enabled=True
    )
    cfg.update(cfg_over)
    return DeepThinkingOrchestrator(
        retrieval_orchestrator=MockRetrieval(outcome),
        reranker=NoopReranker(),
        llm_adapter=ScriptedLLM(responses),
        dt_config=DeepThinkingConfig(**cfg),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )


@pytest.mark.asyncio
async def test_verify_pass_returns_answer():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make_verify(outcome, [PLAN_1ITEM, SEA_SUFFICIENT, "答案A [1]", VERIFY_OK])
    result = await orch.run("papers", "综述", answer_language="zh")
    assert result.answer == "答案A [1]"
    assert result.verified is True
    assert result.degraded is False


@pytest.mark.asyncio
async def test_verify_ok_is_overruled_by_soft_missing():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make_verify(
        outcome,
        [PLAN_CRITICAL, SEA_TRUE_NO_SATISFIED, "答案A [1]", VERIFY_OK],
        max_rounds=1,
    )

    result = await orch.run("papers", "综述", answer_language="zh")

    assert result.answer == "答案A [1]"
    assert result.verified is False
    assert result.verify_missing == ["关键检查项未满足：必需"]


@pytest.mark.asyncio
async def test_answer_question_used_for_synthesis_and_verify_not_retrieval_query():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_1ITEM, SEA_SUFFICIENT, "answer [1]", VERIFY_OK])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=1,
            max_sub_queries=2,
            wide_top_k=5,
            json_max_retries=1,
            verify_enabled=True,
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )

    result = await orch.run(
        "papers",
        "translated retrieval query",
        answer_question="用户原始问题",
    )

    assert result.answer == "answer [1]"
    assert retrieval.queries[:2] == ["translated retrieval query", "q1"]
    synth_prompt = llm.prompts[2]
    verify_prompt = llm.prompts[3]
    assert "Question: 用户原始问题" in synth_prompt
    assert "问题：用户原始问题" in verify_prompt
    assert "Question: translated retrieval query" not in synth_prompt


@pytest.mark.asyncio
async def test_verify_fail_triggers_recheck_then_passes():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make_verify(
        outcome, [PLAN_1ITEM, SEA_SUFFICIENT, "草稿1", VERIFY_BAD, "草稿2 [1]", VERIFY_OK]
    )
    result = await orch.run("papers", "综述")
    # 首版不合格→missing 当 gap 再检索→重合成→第二版通过。
    assert result.answer == "草稿2 [1]"
    assert result.verified is True


@pytest.mark.asyncio
async def test_verify_missing_retrieval_adds_new_final_evidence():
    retrieval = SequenceRetrieval([
        _outcome([_chunk("c1")]),
        _outcome([_chunk("c1")]),
        _outcome([_chunk("c2")]),
    ])
    llm = ScriptedLLM([PLAN_1ITEM, SEA_SUFFICIENT, "草稿1", VERIFY_BAD, "草稿2 [1]", VERIFY_OK])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=1,
            max_sub_queries=2,
            wide_top_k=5,
            json_max_retries=1,
            verify_enabled=True,
            max_verify_rounds=1,
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )

    result = await orch.run("papers", "综述")

    assert result.verified is True
    assert [chunk.chunk_id for chunk in result.evidence] == ["c1", "c2"]
    assert retrieval.queries[-1] == "缺X"


@pytest.mark.asyncio
async def test_verify_reaches_max_verify_rounds():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make_verify(
        outcome, [PLAN_1ITEM, SEA_SUFFICIENT, "草稿1", VERIFY_BAD, "草稿2", VERIFY_BAD]
    )
    result = await orch.run("papers", "综述")
    # 达 max_verify_rounds 仍不合格 → 用最后一版 draft，verified=False。
    assert result.answer == "草稿2"
    assert result.verified is False


@pytest.mark.asyncio
async def test_verify_json_contract_error_marks_answer_unverified():
    outcome = _outcome([_chunk("c1")])
    orch = _make_verify(
        outcome,
        [PLAN_1ITEM, SEA_SUFFICIENT, "草稿OK [1]", "not json", "still not json"],
    )
    result = await orch.run("papers", "综述")
    assert result.answer == "草稿OK [1]"
    assert result.verified is False


@pytest.mark.asyncio
async def test_verify_claim_level_hard_to_warning_soft_to_notes():
    outcome = _outcome([_chunk("c1")])
    orch = _make_verify(
        outcome,
        [PLAN_1ITEM, SEA_SUFFICIENT, "草稿 [1]", VERIFY_CLAIM_BAD],
        max_verify_rounds=0,
    )
    result = await orch.run("papers", "综述")
    assert result.verified is False
    # 硬违规（臆造/矛盾/引用错配）进正文告警 verify_missing。
    assert result.verify_missing == [
        "断言A无证据",
        "[2]不支持断言C",
        "断言B缺引用",
        "断言D与证据冲突",
    ]
    # 信息缺口属软项，仅入 verify_notes（不堆告警墙）。
    assert result.verify_notes == ["缺少背景"]


@pytest.mark.asyncio
async def test_verify_synth_llm_unavailable_returns_no_answer():
    outcome = _outcome([_chunk("c1")])
    orch = _make_verify(outcome, [PLAN_1ITEM, SEA_SUFFICIENT, RuntimeError("synth down")])
    result = await orch.run("papers", "综述")
    # 合成 LLM 不可用 → answer=None，退回 api.ask 合成；不打崩、证据仍在。
    assert result.answer is None
    assert result.degraded is False
    assert len(result.evidence) > 0


@pytest.mark.asyncio
async def test_verify_llm_unavailable_uses_draft():
    outcome = _outcome([_chunk("c1")])
    orch = _make_verify(
        outcome, [PLAN_1ITEM, SEA_SUFFICIENT, "草稿OK [1]", RuntimeError("verify down")]
    )
    result = await orch.run("papers", "综述")
    # 校验 LLM 不可用 → 用已合成的 draft、verified=False，不打崩。
    assert result.answer == "草稿OK [1]"
    assert result.verified is False


@pytest.mark.asyncio
async def test_verify_failure_after_critical_gap_keeps_partial_evidence():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch = _make_verify(outcome, [PLAN_CRITICAL, SEA_INSUFF_NOGAP])
    result = await orch.run("papers", "综述")
    # critical 缺口不再丢弃探索证据；verification 不可用时由 api.ask 兜底合成。
    assert result.degraded is False
    assert result.answer is None
    assert [chunk.chunk_id for chunk in result.evidence] == ["c1", "c2"]
    assert result.verify_missing == ["关键检查项未满足：必需"]


# ── v0.25.9：开放式发现 / per-aspect 排序 / clip / deep 合成 / 全局预算 ──────
SEA_DISCOVER = (
    '{"satisfied_ids":["c1"],"gaps":[],'
    '"discovered_aspects":[{"text":"新机制X","why_relevant":"与主题相关",'
    '"search_hints":["X term"],"gap_type":"comparison"}],'
    '"conflicting_chunk_ids":[],"sufficient":false}'
)


def _oc(pairs, anchor_ids=frozenset()):
    """按 (chunk, rrf_score) 构造 outcome，便于精确控制 per-aspect 排序信号。"""
    chunks = [c for c, _ in pairs]
    signals = {
        c.chunk_id: ChunkSignal(rrf_score=s, anchor_hit=c.chunk_id in anchor_ids)
        for c, s in pairs
    }
    return RetrievalOutcome(chunks=chunks, engines=["milvus"], per_chunk_signals=signals)


def test_parse_sea_keeps_discovered_separate_from_gaps():
    sea = parse_sea(SEA_DISCOVER)
    assert [d.text for d in sea.discovered] == ["新机制X"]
    assert sea.discovered[0].search_hints == ["X term"]
    # discovered 不混入 gaps（避免开放式深挖重造告警墙）。
    assert sea.gaps == []


@pytest.mark.asyncio
async def test_discovered_absorbed_into_checklist_and_drives_next_round_not_warning():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_1ITEM, SEA_DISCOVER, SEA_SUFFICIENT])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=2, max_sub_queries=2, wide_top_k=5, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    result = await orch.run("papers", "综述问题")
    discovered_items = [i for i in result.checklist.items if i.origin == "discovered"]
    assert [i.text for i in discovered_items] == ["新机制X"]
    assert all(not i.critical for i in discovered_items)  # 探索性 → 非 critical。
    assert result.trace[0].discovered == ["新机制X"]  # 写入 trace 供可观测。
    assert "新机制X" in retrieval.queries  # discovered 驱动下一轮补检（确定性兜底）。
    assert "新机制X" not in result.verify_missing  # 不进告警。


@pytest.mark.asyncio
async def test_per_aspect_ranking_surfaces_high_rrf_subquery_chunk():
    base = _oc([(_chunk("c1"), 0.9), (_chunk("c2"), 0.5), (_chunk("c3"), 0.1)])
    sub = _oc([(_chunk("c3"), 0.95), (_chunk("c4"), 0.4)])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=SequenceRetrieval([base, sub]),
        reranker=NoopReranker(),
        llm_adapter=ScriptedLLM([PLAN_1ITEM, SEA_SUFFICIENT]),
        dt_config=DeepThinkingConfig(
            max_rounds=1, max_sub_queries=1, wide_top_k=5, deep_keep=5, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    result = await orch.run("papers", "big question")
    # c3 在 sub_query 里 rrf 最高 → per-aspect 排序顶到首位（旧实现按插入顺序它排第 3）。
    assert result.trace[0].kept_chunk_ids[0] == "c3"


def test_reranker_is_passthrough_flags():
    from kacore.repository.reranker.bge_local import CrossEncoderReranker

    assert NoopReranker().is_passthrough is True
    assert CrossEncoderReranker(model="x").is_passthrough is False


def test_verify_prompt_respects_clip_param():
    from kacore.pipelines.deep_thinking_prompts import build_verify_prompt

    chunk = DocumentChunk("c1", "d", 0, "X" * 100, "h")
    short = build_verify_prompt("q", "a", [chunk], 10)
    longer = build_verify_prompt("q", "a", [chunk], 80)
    assert "X" * 10 in short and "X" * 11 not in short
    assert "X" * 80 in longer


@pytest.mark.asyncio
async def test_synthesize_answer_deep_style_selects_deep_system():
    from kacore.pipelines.answer_synthesis import synthesize_answer

    llm = ScriptedLLM(["ans"])
    await synthesize_answer(llm, "q", [_chunk("c1")], "zh", style="deep")
    assert "mechanism" in llm.system_prompts[0].lower()
    llm2 = ScriptedLLM(["ans"])
    await synthesize_answer(llm2, "q", [_chunk("c1")], "zh")
    assert "mechanism" not in llm2.system_prompts[0].lower()


@pytest.mark.asyncio
async def test_call_budget_counts_plan_and_sea_not_only_sea():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    llm = ScriptedLLM([PLAN_1ITEM, SEA_INSUFF_SMALLGAP])  # 若进第二轮会因缺响应而 IndexError。
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=MockRetrieval(outcome),
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=3, max_sub_queries=2, wide_top_k=5, call_budget=2, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    result = await orch.run("papers", "综述")
    # PLAN(1)+SEA(1)=2 已达 call_budget=2 → round1 后即停（旧口径只数 SEA=1 不会停）。
    assert len(result.trace) == 1
    assert llm.calls == 2


# ── v0.30.0：SEA+REFINE 合并 / labels 缓存 / 并行重排 ────────
def test_parse_sea_parses_next_sub_queries():
    sea = parse_sea(SEA_INSUFF_WITH_NEXT)
    assert sea.sufficient is False
    assert sea.next_queries == ["Paper X Table 3"]
    # 旧输出无该字段 → 空列表（向后兼容，走确定性兜底）。
    assert parse_sea(SEA_INSUFF_SMALLGAP).next_queries == []


@pytest.mark.asyncio
async def test_sea_next_sub_queries_drive_next_round_without_refine_call():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_1ITEM, SEA_INSUFF_WITH_NEXT, SEA_SUFFICIENT])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=2, max_sub_queries=2, wide_top_k=5, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    result = await orch.run("papers", "综述问题")
    # SEA 自带补检 query → 直接进入 round2 检索，无独立 REFINE 调用。
    assert "Paper X Table 3" in retrieval.queries
    assert llm.calls == 3  # PLAN + SEA×2（旧流程为 PLAN+SEA+REFINE+SEA=4）。
    assert len(result.trace) == 2
    assert result.degraded is False


@pytest.mark.asyncio
async def test_document_labels_cached_across_rounds():
    # 两轮 SEA 的证据全部来自 doc1 → 第二轮命中缓存，不再请求 document_labels。
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM([PLAN_1ITEM, SEA_INSUFF_WITH_NEXT, SEA_SUFFICIENT])
    orch = DeepThinkingOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        dt_config=DeepThinkingConfig(
            max_rounds=2, max_sub_queries=2, wide_top_k=5, verify_enabled=False
        ),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    await orch.run("papers", "综述问题")
    assert retrieval.label_requests == [["doc1"]]


@pytest.mark.asyncio
async def test_rank_candidates_parallel_pools_match_serial_ordering():
    """并行分池 rerank 的混合排序与按池串行时一致（max 聚合与执行顺序无关）。"""
    from kacore.pipelines.deep_thinking_evidence import rank_candidates

    class EchoReranker:
        """按 chunk 文本内嵌分数打分的确定性 reranker。"""

        is_passthrough = False

        async def rerank(self, query, candidates, top_n=None):
            from kacore.repository.reranker.base import ScoredChunk

            scored = [
                ScoredChunk(chunk=c, score=float(c.text.rsplit("=", 1)[-1]))
                for c in candidates
            ]
            scored.sort(key=lambda sc: sc.score, reverse=True)
            return scored

    def _scored_chunk(cid: str, score: float) -> DocumentChunk:
        return DocumentChunk(cid, "doc1", 0, f"score={score}", f"h-{cid}")

    hi, mid, lo = _scored_chunk("hi", 0.9), _scored_chunk("mid", 0.5), _scored_chunk("lo", 0.1)
    oc1 = _oc([(hi, 0.2), (lo, 0.1)])
    oc2 = _oc([(mid, 0.3), (lo, 0.05)])
    ranked = await rank_candidates(
        [("q1", oc1), ("q2", oc2)], [hi, mid, lo], set(), EchoReranker(), rerank_weight=1.0
    )
    assert [sc.chunk.chunk_id for sc in ranked] == ["hi", "mid", "lo"]


# ── 部分失败降级（v1.0.0-rc.1）──────────────────────────────


async def test_gather_round_skips_failed_subquery():
    """单个 sub_query 检索瞬断不应废掉整轮推演，剩余结果照常累积证据。"""
    outcome = _outcome([_chunk("c1")])
    orch = _make(outcome, [])

    async def flaky(collection, query, top_k, scope=None):
        if query == "bad":
            raise RuntimeError("vector store down")
        return outcome

    orch._retrieval.retrieve_with_outcome = flaky
    evidence: dict = {}
    kept = await orch._gather_round(
        "col", "main q", ["good", "bad"], None, [], evidence, set(), include_baseline=None
    )
    assert "c1" in kept
    assert "c1" in evidence


async def test_gather_round_raises_when_all_subqueries_fail_without_baseline():
    outcome = _outcome([_chunk("c1")])
    orch = _make(outcome, [])

    async def broken(collection, query, top_k, scope=None):
        raise RuntimeError("vector store down")

    orch._retrieval.retrieve_with_outcome = broken
    with pytest.raises(RuntimeError):
        await orch._gather_round(
            "col", "main q", ["q1", "q2"], None, [], {}, set(), include_baseline=None
        )
