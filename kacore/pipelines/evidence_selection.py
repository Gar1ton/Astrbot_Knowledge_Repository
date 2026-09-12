"""确定性证据覆盖选择器（pipelines 层，纯函数/轻量类，无 I/O）。

按每个 aspect（子问题/信息点）建立候选与原始相关度映射，不跨池比较未经校准的绝对分数；
先遍历有相关证据的 aspect 挑选能补充尚未覆盖方面的候选，再用剩余预算按相关度与非重复
内容填充；不直接引入 Dartboard 或固定文档配额，不统一惩罚同文档不同章节，也不因为一个
候选覆盖多个方面就重复计数预算。

由增强和深度模式的请求级 EvidenceSession 复用。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvidenceCandidate:
    """单条候选证据在某次检索中的原始信息（供选择器消费，不涉及正文重复存储）。

    契约：evidence_id 在本次请求的共享证据池内唯一；doc_id/revision_id/ordinal 构成
    稳定 tie-break 顺序，不依赖 dict/set 遍历或异步完成顺序。text_signature 用于近似
    重复判断——具体算法（归一化摘要/simhash 等）由调用方决定，本模块只做等值比较；
    is_pinned 标记用户明确定位的锚点，始终保留，不参与预算竞争淘汰。
    """

    evidence_id: str
    doc_id: str
    revision_id: str
    ordinal: int
    text_signature: str
    is_pinned: bool = False


@dataclass(frozen=True)
class AspectCandidates:
    """一个 aspect 及其候选证据与原始相关度分数（分数只在本 aspect 内部比较）。"""

    aspect_id: str
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionResult:
    """选择结果：入选证据、aspect→evidence 映射、未覆盖 aspect、预算耗尽标记与选择理由。

    budget_exhausted 只在「达到 max_evidence 上限，且确有未入选的候选」时为 True——
    aspect 本身没有任何候选（检索未命中）不算预算耗尽，是另一种信号，不应混同。
    """

    selected_ids: list[str]
    aspect_coverage: dict[str, list[str]]
    uncovered_aspect_ids: list[str]
    selection_reasons: dict[str, str]
    budget_exhausted: bool


def _tie_break_key(candidates: dict[str, EvidenceCandidate], eid: str) -> tuple[str, str, int, str]:
    candidate = candidates.get(eid)
    if candidate is None:
        return "", "", 0, eid
    return candidate.doc_id, candidate.revision_id, candidate.ordinal, candidate.evidence_id


def select_evidence(
    aspects: list[AspectCandidates],
    candidates: dict[str, EvidenceCandidate],
    *,
    max_evidence: int,
) -> SelectionResult:
    """确定性贪心选择：先覆盖尚未覆盖的 aspect，再按相关度与非重复内容填充剩余预算。

    契约：
        - 明确锚点（is_pinned=True）优先保留，仍受 max_evidence 总数上限约束。
        - 章节路径不同不作为「必有新知识」的证明，也不因同文档而扣分——只有
          text_signature 相同才判定为重复，且重复只是降低填充阶段的优先级，预算充裕
          时仍可能入选（不同否定/数值/结论的证据即使被调用方判为重复也不强删）。
        - aspect 遍历顺序取 `aspects` 参数顺序；候选顺序取 (doc_id, revision_id, ordinal)。
    """
    if max_evidence < 0:
        raise ValueError("max_evidence must be >= 0")

    selected: list[str] = []
    selected_set: set[str] = set()
    seen_signatures: set[str] = set()
    aspect_coverage: dict[str, list[str]] = {a.aspect_id: [] for a in aspects}
    reasons: dict[str, str] = {}

    def _ordered_by_relevance(scores: dict[str, float]) -> list[str]:
        return sorted(
            scores.keys(),
            key=lambda eid: (-scores[eid], *_tie_break_key(candidates, eid)),
        )

    # 0) 明确锚点始终保留。
    for candidate in sorted(
        candidates.values(), key=lambda c: (c.doc_id, c.revision_id, c.ordinal, c.evidence_id)
    ):
        if len(selected) >= max_evidence:
            break
        if candidate.is_pinned and candidate.evidence_id not in selected_set:
            selected.append(candidate.evidence_id)
            selected_set.add(candidate.evidence_id)
            reasons[candidate.evidence_id] = "pinned_anchor"
            seen_signatures.add(candidate.text_signature)

    # 1) 优先遍历有相关证据的 aspect，每个 aspect 本轮只取一条最相关的未覆盖候选，
    #    避免单个 aspect 在第一轮就吃满预算，保证「多方面保留」优先于「单方面吃满」。
    for aspect in aspects:
        if len(selected) >= max_evidence or not aspect.scores:
            continue
        for eid in _ordered_by_relevance(aspect.scores):
            if eid in selected_set:
                aspect_coverage[aspect.aspect_id].append(eid)
                break
            candidate = candidates.get(eid)
            if candidate is None:
                continue
            if candidate.text_signature in seen_signatures:
                continue  # 本轮跳过重复内容，第 2 步预算充裕时仍可能选中
            if len(selected) >= max_evidence:
                break
            selected.append(eid)
            selected_set.add(eid)
            aspect_coverage[aspect.aspect_id].append(eid)
            reasons[eid] = f"covers_aspect:{aspect.aspect_id}"
            seen_signatures.add(candidate.text_signature)
            break

    # 2) 剩余预算按相关度与非重复内容填充；重复内容降优先级但不排除。
    all_candidate_ids: set[str] = set()
    if len(selected) < max_evidence:
        remaining: dict[str, float] = {}
        for aspect in aspects:
            for eid, score in aspect.scores.items():
                all_candidate_ids.add(eid)
                if eid in selected_set:
                    continue
                remaining[eid] = max(remaining.get(eid, score), score)

        def _fill_order(eid: str) -> tuple[bool, float, str, str, int, str]:
            candidate = candidates.get(eid)
            is_duplicate = candidate is not None and candidate.text_signature in seen_signatures
            return (is_duplicate, -remaining[eid], *_tie_break_key(candidates, eid))

        while remaining:
            if len(selected) >= max_evidence:
                break
            eid = min(remaining, key=_fill_order)
            remaining.pop(eid)
            candidate = candidates.get(eid)
            if candidate is None:
                continue
            selected.append(eid)
            selected_set.add(eid)
            reasons.setdefault(eid, "budget_fill")
            seen_signatures.add(candidate.text_signature)
            for aspect in aspects:
                if eid in aspect.scores:
                    aspect_coverage[aspect.aspect_id].append(eid)
    else:
        for aspect in aspects:
            all_candidate_ids.update(aspect.scores.keys())

    # 覆盖独立于选择时机：预算满了也必须记录共享证据对后续方面的支持。
    aspect_coverage = {
        a.aspect_id: [eid for eid in selected if eid in a.scores] for a in aspects
    }
    uncovered = [a.aspect_id for a in aspects if not aspect_coverage[a.aspect_id]]
    budget_exhausted = len(selected) >= max_evidence and bool(all_candidate_ids - selected_set)

    return SelectionResult(
        selected_ids=selected,
        aspect_coverage=aspect_coverage,
        uncovered_aspect_ids=uncovered,
        selection_reasons=reasons,
        budget_exhausted=budget_exhausted,
    )


__all__ = [
    "EvidenceCandidate",
    "AspectCandidates",
    "SelectionResult",
    "select_evidence",
]
