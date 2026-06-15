"""Deep thinking 与 ask 共享的答案合成（pipelines 层）。

把「证据 → 带 [n] 引用的答案」抽为可复用单元，供 orchestrator 的 verification 闭环
与 api.ask 共用，避免重复合成逻辑。不含 persona / lightrag 包装（那是 api.ask 展示层）。
[n] 按 evidence 顺序编号，调用方据同序拼 sources，保证引用对齐。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.adapters.llm import LLMAdapter
    from core.domain.models import DocumentChunk

# 每条证据可能来自不同来源文档；禁止跨来源张冠李戴的统一约束（防跨文档知识串线）。
_SOURCE_ISOLATION_RULE = (
    "Each evidence item is labeled with its source document (来源). "
    "Findings, methods and limitations from different sources MUST NOT be conflated or "
    "mis-attributed: attribute every claim only to its true source and cite it with that "
    "source's [n]. When the question is scoped to one specific paper, answer only what that "
    "paper's evidence supports; other sources may be used solely for explicitly named "
    "comparison, never silently merged into that paper's claims. "
)

# 与 api.ask 一致的合成 system 基模板（answer_language 指令追加在后）。
_SYNTH_SYSTEM_BASE = (
    "You are a helpful academic assistant. "
    "Answer the question based solely on the provided context. "
    "If the context is insufficient, state the limitation clearly and only answer what the "
    "context supports. "
    "Do not fill gaps with outside knowledge. "
    "Cite sources using [n] notation (e.g. [1], [2]). "
    + _SOURCE_ISOLATION_RULE
)

# Deep Thinking 专用：在严格 grounded 的前提下要求机制级、分维度、带跨实体对比的深度回答。
_SYNTH_SYSTEM_DEEP = (
    "You are a rigorous research assistant writing an in-depth, evidence-grounded answer. "
    "Answer based solely on the provided context; do not use outside knowledge; "
    "cite every claim with [n] notation; only flag a limitation where the context truly "
    "lacks support. "
    "Go as deep as the evidence allows: name the specific mechanisms, techniques and terms "
    "that appear in the context rather than generic abstractions. "
    "Adapt structure to the question: for comparison or 'shared X of A and B' questions, "
    "enumerate the concrete dimensions; under each dimension give each entity's specific "
    "mechanism with its citation, then add one synthesis line on how they align. "
    "Prefer mechanism-level specificity over vague summary. "
    + _SOURCE_ISOLATION_RULE
)


def _lang_instruction(answer_language: str) -> str:
    if answer_language == "zh":
        return "Answer in Chinese (中文)."
    if answer_language == "en":
        return "Answer in English."
    return "Answer in the same language as the question."


def source_tag(doc_id: str, source_labels: dict[str, str] | None) -> str:
    """据 doc_id 取来源标签，拼成 `（来源：X）` 前缀；无映射时返回空串（向后兼容）。

    防跨文档知识串线：每条证据带上其来源文档，模型才能区分多篇拼接的证据池。
    """
    if not source_labels:
        return ""
    label = source_labels.get(doc_id)
    return f"（来源：{label}）" if label else ""


async def synthesize_answer(
    llm: LLMAdapter,
    question: str,
    evidence: list[DocumentChunk],
    answer_language: str = "auto",
    style: str = "default",
    source_labels: dict[str, str] | None = None,
) -> str:
    """用证据合成带 [n] 引用的答案。

    契约：[n] 按 evidence 顺序编号（调用方据同序拼 sources）；evidence 为空返回空串
    （由调用方决定兜底）；LLM 调用异常向上抛（由调用方处理，禁用 mock 兜底）。
    style="deep" 选用机制级/分维度/带对比的 deep 合成模板，否则用通用模板。
    source_labels（doc_id→来源标签）给每条证据标注来源文档，防跨文档串线；None 时不标注。
    """
    if not evidence:
        return ""
    base = _SYNTH_SYSTEM_DEEP if style == "deep" else _SYNTH_SYSTEM_BASE
    system = base + _lang_instruction(answer_language)
    context = "\n\n---\n\n".join(
        f"[{i + 1}]{source_tag(chunk.doc_id, source_labels)} {chunk.text}"
        for i, chunk in enumerate(evidence)
    )
    user = f"Context:\n\n{context}\n\nQuestion: {question}"
    return await llm.generate(user, system_prompt=system, allow_mock=False)


__all__ = ["synthesize_answer", "source_tag"]
