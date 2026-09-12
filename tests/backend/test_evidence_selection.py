"""确定性证据覆盖选择器的测试（无 I/O）。

覆盖验收矩阵 R01（多方面保留不因来源类型扣分）、R02（重复降优先级、反驳不因词汇相似
被删除）、R03（多 aspect 共用同一证据）及 tie-break 稳定性、预算耗尽信号的正确性。
"""
from __future__ import annotations

from kacore.pipelines.evidence_selection import (
    AspectCandidates,
    EvidenceCandidate,
    select_evidence,
)


def _cand(
    eid: str, doc_id: str = "d1", rev: str = "r1", ordinal: int = 0, sig: str = ""
) -> EvidenceCandidate:
    return EvidenceCandidate(
        evidence_id=eid, doc_id=doc_id, revision_id=rev, ordinal=ordinal,
        text_signature=sig or eid,
    )


def test_multiple_aspects_each_get_their_top_candidate_first() -> None:
    """R01：多个不同方面各自保留代表性证据，不因单一来源类型被挤占。"""
    candidates = {
        "book1": _cand("book1"),
        "book2": _cand("book2"),
        "paper1": _cand("paper1"),
    }
    aspects = [
        AspectCandidates("a1", {"book1": 0.9}),
        AspectCandidates("a2", {"book2": 0.8}),
        AspectCandidates("a3", {"paper1": 0.7}),
    ]

    result = select_evidence(aspects, candidates, max_evidence=3)

    assert set(result.selected_ids) == {"book1", "book2", "paper1"}
    assert result.uncovered_aspect_ids == []


def test_single_aspect_does_not_greedily_consume_entire_budget_first_round() -> None:
    candidates = {
        "e1": _cand("e1"), "e2": _cand("e2"), "e3": _cand("e3"), "other": _cand("other"),
    }
    aspects = [
        AspectCandidates("a1", {"e1": 0.9, "e2": 0.8, "e3": 0.7}),
        AspectCandidates("a2", {"other": 0.5}),
    ]

    result = select_evidence(aspects, candidates, max_evidence=2)

    # a2 唯一候选必须被覆盖，不能被 a1 的三条候选在第一轮全部吃满预算。
    assert "other" in result.selected_ids
    assert result.aspect_coverage["a2"] == ["other"]


def test_duplicate_content_deprioritized_but_not_deleted_when_budget_allows() -> None:
    """R02：重复内容降优先级，预算充裕时仍可入选（不是强删）。"""
    candidates = {
        "e1": _cand("e1", sig="same-text"),
        "e2": _cand("e2", sig="same-text"),  # 与 e1 文本重复
        "e3": _cand("e3", sig="unique-text"),
    }
    aspects = [AspectCandidates("a1", {"e1": 0.9, "e2": 0.85, "e3": 0.5})]

    result = select_evidence(aspects, candidates, max_evidence=3)

    assert set(result.selected_ids) == {"e1", "e2", "e3"}  # 预算够，重复也保留


def test_duplicate_content_excluded_when_budget_tight() -> None:
    candidates = {
        "e1": _cand("e1", sig="same-text"),
        "e2": _cand("e2", sig="same-text"),
        "e3": _cand("e3", sig="unique-text"),
    }
    aspects = [AspectCandidates("a1", {"e1": 0.9, "e2": 0.85, "e3": 0.5})]

    result = select_evidence(aspects, candidates, max_evidence=2)

    # 预算紧张时，非重复的 e3 优先于重复的 e2 被选中，即便 e2 分数更高。
    assert "e1" in result.selected_ids
    assert "e3" in result.selected_ids
    assert "e2" not in result.selected_ids


def test_lexically_similar_rebuttal_is_not_deleted_when_signature_differs() -> None:
    """R02：含否定/结论不同的反驳证据即使词汇相似，只要调用方判定 signature 不同就不能被删。"""
    candidates = {
        "claim": _cand("claim", sig="X causes Y"),
        "rebuttal": _cand("rebuttal", sig="X does NOT cause Y"),  # 调用方判定为不同 signature
    }
    aspects = [AspectCandidates("a1", {"claim": 0.9, "rebuttal": 0.85})]

    result = select_evidence(aspects, candidates, max_evidence=2)

    assert set(result.selected_ids) == {"claim", "rebuttal"}


def test_multiple_aspects_share_same_evidence() -> None:
    """R03：一个候选可以覆盖多个方面，共用同一条证据不重复计数预算。"""
    candidates = {"shared": _cand("shared")}
    aspects = [
        AspectCandidates("a1", {"shared": 0.9}),
        AspectCandidates("a2", {"shared": 0.8}),
    ]

    result = select_evidence(aspects, candidates, max_evidence=5)

    assert result.selected_ids == ["shared"]
    assert result.aspect_coverage["a1"] == ["shared"]
    assert result.aspect_coverage["a2"] == ["shared"]


def test_pinned_anchor_always_included_regardless_of_score() -> None:
    candidates = {
        "pinned": EvidenceCandidate(
            evidence_id="pinned", doc_id="d1", revision_id="r1", ordinal=0,
            text_signature="pinned", is_pinned=True,
        ),
        "high_score": _cand("high_score", sig="high"),
    }
    aspects = [AspectCandidates("a1", {"high_score": 0.99})]

    result = select_evidence(aspects, candidates, max_evidence=1)

    assert "pinned" in result.selected_ids
    assert result.selection_reasons["pinned"] == "pinned_anchor"


def test_tie_break_is_deterministic_by_doc_revision_ordinal() -> None:
    candidates = {
        "z": _cand("z", doc_id="docB", rev="r1", ordinal=0),
        "a": _cand("a", doc_id="docA", rev="r1", ordinal=0),
    }
    aspects = [AspectCandidates("a1", {"z": 0.5, "a": 0.5})]  # 分数相同，靠 tie-break

    result = select_evidence(aspects, candidates, max_evidence=1)

    assert result.selected_ids == ["a"]  # docA < docB 字典序在前


def test_uncovered_aspect_with_no_candidates() -> None:
    aspects = [AspectCandidates("a1", {}), AspectCandidates("a2", {"e1": 0.5})]
    candidates = {"e1": _cand("e1")}

    result = select_evidence(aspects, candidates, max_evidence=5)

    assert result.uncovered_aspect_ids == ["a1"]
    assert result.budget_exhausted is False  # 没有候选不算「预算耗尽」


def test_budget_exhausted_true_when_relevant_candidates_left_out() -> None:
    candidates = {f"e{i}": _cand(f"e{i}", sig=f"sig{i}") for i in range(5)}
    aspects = [AspectCandidates("a1", {eid: 1.0 - i * 0.01 for i, eid in enumerate(candidates)})]

    result = select_evidence(aspects, candidates, max_evidence=2)

    assert len(result.selected_ids) == 2
    assert result.budget_exhausted is True


def test_zero_budget_selects_nothing_including_pinned() -> None:
    candidates = {
        "pinned": EvidenceCandidate(
            evidence_id="pinned", doc_id="d1", revision_id="r1", ordinal=0,
            text_signature="pinned", is_pinned=True,
        ),
    }
    aspects = [AspectCandidates("a1", {"pinned": 0.5})]

    result = select_evidence(aspects, candidates, max_evidence=0)

    # 明确锚点优先，但不能突破总预算。
    assert result.selected_ids == []


def test_shared_coverage_is_recorded_after_budget_fills() -> None:
    result = select_evidence(
        [AspectCandidates("a", {"e": 1}), AspectCandidates("b", {"e": 1})],
        {"e": _cand("e")}, max_evidence=1,
    )
    assert result.aspect_coverage == {"a": ["e"], "b": ["e"]}
    assert not result.uncovered_aspect_ids


def test_fill_recomputes_redundancy_after_each_selection() -> None:
    candidates = {"a": _cand("a"), "b": _cand("b", sig="repeat"),
                  "c": _cand("c", sig="repeat"), "d": _cand("d")}
    result = select_evidence(
        [AspectCandidates("topic", {"a": 1, "b": .9, "c": .8, "d": .7})],
        candidates, max_evidence=3,
    )
    assert result.selected_ids == ["a", "b", "d"]
