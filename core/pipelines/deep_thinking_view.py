"""Deep Thinking「思考过程」序列化（pipelines 层·展示视图）。

把 checklist 与逐轮 trace 序列化为前端可渲染的纯 dict。orchestrator 的实时增量进度
（live_detail）与 api.ask 的最终 thinking_trace（serialize_outcome）共用同一套底层序列化，
从根上保证「实时格式 == 最终格式」，杜绝两处各写一份导致的漂移。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.domain.deep_thinking import Checklist, DeepThinkingOutcome, RoundTrace


def serialize_checklist(checklist: Checklist) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "text": item.text,
            "critical": item.critical,
            "satisfied": item.satisfied,
            "origin": item.origin,
        }
        for item in checklist.items
    ]


def serialize_rounds(trace: list[RoundTrace]) -> list[dict[str, Any]]:
    return [
        {
            "round": r.round,
            "queries": r.queries,
            "gaps": r.gaps,
            "discovered": r.discovered,
            "kept_chunk_ids": r.kept_chunk_ids,
            "llm_calls": r.llm_calls,
            "est_tokens": r.est_tokens,
        }
        for r in trace
    ]


def live_detail(phase: str, checklist: Checklist, trace: list[RoundTrace]) -> dict[str, Any]:
    """orchestrator 增量进度详情：阶段标识 + 已拆解清单 + 已完成的逐轮 trace。"""
    return {
        "phase": phase,
        "checklist": serialize_checklist(checklist),
        "rounds": serialize_rounds(trace),
    }


def serialize_outcome(outcome: DeepThinkingOutcome) -> dict[str, Any]:
    """api.ask 的最终 thinking_trace：在 live_detail 同形 checklist/rounds 之上附校验结论。"""
    return {
        "degraded": outcome.degraded,
        "degraded_reason": outcome.degraded_reason,
        "verified": outcome.verified,
        "verify_missing": outcome.verify_missing,
        "verify_notes": getattr(outcome, "verify_notes", []),
        "est_total_tokens": outcome.est_total_tokens,
        "checklist": serialize_checklist(outcome.checklist),
        "rounds": serialize_rounds(outcome.trace),
    }


__all__ = ["serialize_checklist", "serialize_rounds", "live_detail", "serialize_outcome"]
