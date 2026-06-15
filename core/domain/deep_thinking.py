"""Deep Thinking（FAIR-RAG 迭代检索）领域模型（依赖图圆心，零依赖）。

只定义纯数据值对象：充分性检查清单、证据项、单轮轨迹、迭代产出。与 models.py
同属 domain 圆心，只允许标准库与类型注解，不 import 任何框架/仓储/上层。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


# ── 充分性检查清单 ──────────────────────────────────────────
@dataclass
class ChecklistItem:
    """问题被拆出的一个必需信息点。

    id 由 PLAN 阶段分配，SEA 阶段按 id 回填 satisfied（不靠 text 匹配，避免 LLM
    改写措辞导致误判）。critical 标记是否为「关键」点——关键点未满足触发 baseline 回退。
    """

    id: str
    text: str
    critical: bool = False
    satisfied: bool = False
    evidence_type: str = ""
    search_hints: list[str] = field(default_factory=list)
    status: str = ""
    supporting_chunk_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    why_missing: str = ""
    next_action: str = ""
    origin: str = "plan"  # plan（PLAN 阶段定下）| discovered（SEA 从证据里开放式发现）。


@dataclass
class Checklist:
    items: list[ChecklistItem] = field(default_factory=list)

    def apply_satisfied(self, satisfied_ids: set[str]) -> None:
        """按 SEA 返回的 satisfied_ids 回填各项 satisfied（累积，不回退已满足项）。"""
        for item in self.items:
            if item.id in satisfied_ids:
                item.satisfied = True

    def critical_unmet(self) -> bool:
        """是否存在未满足的关键项——baseline 回退判据之一。空清单视为无未满足。"""
        return any(item.critical and not item.satisfied for item in self.items)


# ── 证据与轨迹 ──────────────────────────────────────────────
@dataclass
class EvidenceItem:
    """orchestrator 内部跟踪的单条证据，附保留原因供 trace 解释。

    直接持有 DocumentChunk 引用以复用其全部字段；kept_reason ∈
    {rerank_score, structural_anchor, baseline_floor}。
    """

    chunk: DocumentChunk
    kept_reason: str
    rerank_score: float | None = None


@dataclass
class RoundTrace:
    """单轮迭代的可观测轨迹（供前端渲染「思考过程」与成本核算）。"""

    round: int
    queries: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)  # 本轮 SEA 开放式发现的新 aspect 文本。
    kept_chunk_ids: list[str] = field(default_factory=list)
    llm_calls: int = 0
    est_tokens: int = 0


@dataclass
class DeepThinkingOutcome:
    """迭代检索的产出。**不含 answer**——合成由 api.ask 负责（杜绝重复合成）。

    evidence 即 final_evidence：正常路径为收敛证据（已剔除非 pinned 的 conflicting），
    degraded 路径严格等于 baseline_floor。est_total_tokens 为字符近似估算（非精确）。
    """

    evidence: list[DocumentChunk] = field(default_factory=list)
    checklist: Checklist = field(default_factory=Checklist)
    trace: list[RoundTrace] = field(default_factory=list)
    degraded: bool = False
    actual_mode: str = "milvus_deep"
    est_total_tokens: int = 0
    # verification 启用时由 orchestrator 合成并校验后产出；否则 None，由 api.ask 合成。
    answer: str | None = None
    verified: bool = False
    # 硬缺失（臆造/矛盾/跨来源错配/关键项未满足）——驱动正文告警与 verified=False。
    verify_missing: list[str] = field(default_factory=list)
    # 软项（部分支持·有据推断 + 信息缺口）——仅入「思考过程」展示，不堆告警墙。
    verify_notes: list[str] = field(default_factory=list)
    degraded_reason: str = ""  # 降级原因；空字符串表示未降级


__all__ = [
    "ChecklistItem",
    "Checklist",
    "EvidenceItem",
    "RoundTrace",
    "DeepThinkingOutcome",
]
