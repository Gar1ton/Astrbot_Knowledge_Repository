"""EnhancedRecallOrchestrator（A-RAG「2+1」中间档）契约测试。

用脚本化 LLM（固定响应/抛异常）+ NoopReranker + mock 检索，离线覆盖：
两步契约解析（PLAN-lite / SYNTH+CHECK fail-open）、happy path 恰 2 次 LLM、
纠偏路径 3 次 LLM、PLAN 异常降级 baseline、SYNTH 异常交 api.ask 兜底、
anchor pinned 保留、跨子查询去重、corrective 开关。
"""
from __future__ import annotations

import pytest

from core.config import EnhancedRecallConfig, RerankConfig
from core.domain.models import DocumentChunk
from core.pipelines.deep_thinking_prompts import JsonContractError
from core.pipelines.enhanced_recall_orchestrator import EnhancedRecallOrchestrator
from core.pipelines.enhanced_recall_prompts import (
    build_synth_check_system,
    parse_plan_lite,
    parse_synth_check,
)
from core.pipelines.retrieval_orchestrator import ChunkSignal, RetrievalOutcome
from core.repository.reranker.noop import NoopReranker

# ── 脚本化响应 ──────────────────────────────────────────────
PLAN_OK = '{"rewritten_query":"rewritten q","sub_queries":["sub a","sub b"]}'
SYNTH_SUFFICIENT = (
    "answer body [1]\n===VERDICT===\n"
    '{"sufficient":true,"insufficiency_reasons":[],"corrective_queries":[]}'
)
SYNTH_INSUFFICIENT = (
    "draft answer [1]\n===VERDICT===\n"
    '{"sufficient":false,"insufficiency_reasons":["缺对比证据"],'
    '"corrective_queries":["Paper Y Table 2"]}'
)
SYNTH_NO_VERDICT = "plain answer without verdict [1]"


# ── 测试替身 ────────────────────────────────────────────────
def _chunk(cid: str, doc_id: str = "doc1") -> DocumentChunk:
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

    async def retrieve_with_outcome(
        self, collection, query, top_k, scope=None, candidate_k=None, reranker=None
    ):
        self.queries.append(query)
        return self._outcome

    async def document_labels(self, doc_ids):
        return {d: d for d in doc_ids if d}


class ScriptedLLM:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    async def generate(self, prompt, system_prompt="", *, allow_mock=True):
        self.calls += 1
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make(outcome, responses, **cfg_over):
    retrieval = MockRetrieval(outcome)
    llm = ScriptedLLM(responses)
    orch = EnhancedRecallOrchestrator(
        retrieval_orchestrator=retrieval,
        reranker=NoopReranker(),
        llm_adapter=llm,
        er_config=EnhancedRecallConfig(**cfg_over),
        rerank_config=RerankConfig(provider="noop", keep=5),
    )
    return orch, retrieval, llm


# ── 契约解析 ────────────────────────────────────────────────
def test_parse_plan_lite_valid_and_mixed_items():
    rewritten, subs = parse_plan_lite(PLAN_OK)
    assert rewritten == "rewritten q"
    assert subs == ["sub a", "sub b"]
    # 元素可为对象；rewritten 缺失由调用方回退原 query。
    rewritten2, subs2 = parse_plan_lite('{"sub_queries":[{"query":"only sub"}]}')
    assert rewritten2 == ""
    assert subs2 == ["only sub"]


def test_parse_plan_lite_empty_raises():
    with pytest.raises(JsonContractError):
        parse_plan_lite('{"rewritten_query":"","sub_queries":[]}')


def test_parse_synth_check_three_states():
    ok = parse_synth_check(SYNTH_SUFFICIENT)
    assert ok.answer == "answer body [1]"
    assert ok.sufficient is True and not ok.corrective_queries
    bad = parse_synth_check(SYNTH_INSUFFICIENT)
    assert bad.sufficient is False
    assert bad.insufficiency_reasons == ["缺对比证据"]
    assert bad.corrective_queries == ["Paper Y Table 2"]
    # 标记缺失 → fail-open：整段视为答案、sufficient=True（不浪费重试）。
    open_ = parse_synth_check(SYNTH_NO_VERDICT)
    assert open_.answer == SYNTH_NO_VERDICT
    assert open_.sufficient is True


def test_parse_synth_check_empty_body_raises():
    with pytest.raises(JsonContractError):
        parse_synth_check("   ")
    with pytest.raises(JsonContractError):
        parse_synth_check('===VERDICT===\n{"sufficient":true}')


def test_synth_check_system_embeds_verdict_contract():
    system = build_synth_check_system("zh", max_corrective_queries=3)
    assert "===VERDICT===" in system
    assert '"sufficient"' in system
    assert "at most 3" in system
    assert "中文" in system  # answer_language 指令保留。


# ── 编排流程 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_happy_path_exactly_two_llm_calls():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")])
    orch, retrieval, llm = _make(outcome, [PLAN_OK, SYNTH_SUFFICIENT])
    result = await orch.run("papers", "原始问题")
    assert llm.calls == 2  # PLAN-lite + SYNTH+CHECK，无第三次调用。
    assert retrieval.queries == ["rewritten q", "sub a", "sub b"]
    assert result.answer == "answer body [1]"
    assert result.verified is True
    assert result.degraded is False
    assert result.actual_mode == "enhanced_recall"
    assert len(result.trace) == 1
    assert result.trace[0].queries == ["rewritten q", "sub a", "sub b"]
    assert result.trace[0].llm_calls == 2


@pytest.mark.asyncio
async def test_insufficient_triggers_corrective_round_and_resynthesis():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch, retrieval, llm = _make(
        outcome, [PLAN_OK, SYNTH_INSUFFICIENT, "final answer [1]"]
    )
    result = await orch.run("papers", "原始问题")
    assert llm.calls == 3  # PLAN + SYNTH+CHECK + 重合成。
    assert retrieval.queries[-1] == "Paper Y Table 2"  # 纠偏 query 进入检索。
    assert result.answer == "final answer [1]"
    assert result.verified is True  # 一轮纠偏即闭环。
    assert result.verify_notes == ["缺对比证据"]  # 缺口透明进思考过程。
    assert len(result.trace) == 2
    assert result.trace[1].queries == ["Paper Y Table 2"]
    assert result.trace[1].gaps == ["缺对比证据"]


@pytest.mark.asyncio
async def test_plan_llm_unavailable_degrades_to_single_round_baseline():
    outcome = _outcome([_chunk(f"c{i}") for i in range(1, 8)])
    orch, retrieval, llm = _make(outcome, [RuntimeError("no real llm")])
    result = await orch.run("papers", "原始问题")
    assert result.degraded is True
    assert result.actual_mode == "enhanced_degraded_to_default"
    assert result.degraded_reason == "no real llm"
    # 降级证据严格等于单轮 baseline 前 5 条；答案交 api.ask 兜底。
    assert [c.chunk_id for c in result.evidence] == ["c1", "c2", "c3", "c4", "c5"]
    assert result.answer is None
    assert retrieval.queries == ["原始问题"]


@pytest.mark.asyncio
async def test_plan_json_invalid_falls_back_to_original_query_without_degrade():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch, retrieval, llm = _make(
        outcome, ["not json", "still not json", SYNTH_SUFFICIENT], json_max_retries=1
    )
    result = await orch.run("papers", "原始问题")
    assert result.degraded is False
    assert retrieval.queries[0] == "原始问题"  # JSON 坏 → 原 query 检索，不降级。
    assert result.answer == "answer body [1]"


@pytest.mark.asyncio
async def test_synth_llm_unavailable_keeps_evidence_with_no_answer():
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch, _retrieval, _llm = _make(outcome, [PLAN_OK, RuntimeError("synth down")])
    result = await orch.run("papers", "原始问题")
    # SYNTH 挂 → answer=None（api.ask deep-fallback 合成兜底），证据保留、不降级。
    assert result.answer is None
    assert result.degraded is False
    assert len(result.evidence) > 0


@pytest.mark.asyncio
async def test_corrective_disabled_returns_first_answer_without_extra_call():
    outcome = _outcome([_chunk("c1")])
    orch, _retrieval, llm = _make(
        outcome, [PLAN_OK, SYNTH_INSUFFICIENT], corrective_enabled=False
    )
    result = await orch.run("papers", "原始问题")
    assert llm.calls == 2  # 不追加纠偏检索与重合成。
    assert result.answer == "draft answer [1]"
    assert result.verified is False  # 自检不充分如实透传。
    assert result.verify_notes == ["缺对比证据"]
    assert len(result.trace) == 1


@pytest.mark.asyncio
async def test_resynthesis_failure_keeps_first_answer():
    outcome = _outcome([_chunk("c1")])
    orch, _retrieval, llm = _make(
        outcome, [PLAN_OK, SYNTH_INSUFFICIENT, RuntimeError("resynth down")]
    )
    result = await orch.run("papers", "原始问题")
    assert llm.calls == 3
    assert result.answer == "draft answer [1]"  # 重合成挂 → 保留首轮答案。
    assert result.verified is True


@pytest.mark.asyncio
async def test_anchor_pinned_chunks_survive_cutoff():
    outcome = _outcome([_chunk("c1"), _chunk("c2"), _chunk("c3")], anchor_ids={"c3"})
    orch, _retrieval, _llm = _make(outcome, [PLAN_OK, SYNTH_SUFFICIENT])
    result = await orch.run("papers", "原始问题")
    assert "c3" in {c.chunk_id for c in result.evidence}


@pytest.mark.asyncio
async def test_cross_subquery_candidates_deduped():
    # 同一 outcome 被三个 query 命中 → 证据无重复 chunk_id。
    outcome = _outcome([_chunk("c1"), _chunk("c2")])
    orch, _retrieval, _llm = _make(outcome, [PLAN_OK, SYNTH_SUFFICIENT])
    result = await orch.run("papers", "原始问题")
    ids = [c.chunk_id for c in result.evidence]
    assert len(ids) == len(set(ids)) == 2


@pytest.mark.asyncio
async def test_answer_question_used_for_synthesis_not_retrieval_query():
    outcome = _outcome([_chunk("c1")])
    orch, retrieval, llm = _make(outcome, [PLAN_OK, SYNTH_SUFFICIENT])
    await orch.run(
        "papers", "translated retrieval query", answer_question="用户原始问题"
    )
    assert retrieval.queries[0] == "rewritten q"
    synth_prompt = llm.prompts[1]
    assert "Question: 用户原始问题" in synth_prompt
    assert "Question: translated retrieval query" not in synth_prompt


@pytest.mark.asyncio
async def test_progress_stages_pushed_in_order():
    outcome = _outcome([_chunk("c1")])
    orch, _retrieval, _llm = _make(
        outcome, [PLAN_OK, SYNTH_INSUFFICIENT, "final [1]"]
    )
    stages: list[str] = []
    await orch.run(
        "papers",
        "原始问题",
        progress=lambda stage, pct, detail=None: stages.append(stage),
    )
    assert stages == [
        "enhanced_plan",
        "enhanced_retrieve",
        "enhanced_synthesize",
        "enhanced_corrective",
        "enhanced_resynthesize",
    ]
