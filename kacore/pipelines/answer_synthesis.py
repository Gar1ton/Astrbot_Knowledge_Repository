"""Deep thinking 与 ask 共享的答案合成（pipelines 层）。

把「证据 → 带 [n] 引用的答案」抽为可复用单元，供 orchestrator 的 verification 闭环
与 api.ask 共用，避免重复合成逻辑。不含 persona / lightrag 包装（那是 api.ask 展示层）。
[n] 按 evidence 顺序编号，调用方据同序拼 sources，保证引用对齐。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kacore.domain.llm_generation import STATUS_EMPTY, GenerationResult

if TYPE_CHECKING:
    from kacore.adapters.llm import LLMAdapter
    from kacore.domain.models import DocumentChunk

# 每条证据可能来自不同来源文档；禁止跨来源张冠李戴的统一约束（防跨文档知识串线）。
_SOURCE_ISOLATION_RULE = (
    "Each evidence item is labeled with its source document (来源). "
    "Findings, methods and limitations from different sources MUST NOT be conflated or "
    "mis-attributed: attribute every claim only to its true source and cite it with that "
    "source's [n]. When the question is scoped to one specific paper, answer only what that "
    "paper's evidence supports; other sources may be used solely for explicitly named "
    "comparison, never silently merged into that paper's claims. "
)

# 成段行文约束（v0.30.0 流畅性）：正文写成完整段落，杜绝碎片化单行 bullet 与流水长句。
_FLUENT_PROSE_RULE = (
    "Write the body in flowing, well-structured paragraphs (2-5 sentences each) separated by "
    "blank lines; use bullet lists only for genuinely enumerable items, never as fragmented "
    "one-line prose, and avoid run-on sentences. "
)

# 与 api.ask 一致的合成 system 基模板（answer_language 指令追加在后）。
_SYNTH_SYSTEM_BASE = (
    "You are a helpful academic assistant. "
    "Answer the question based solely on the provided context. "
    "If the context is insufficient, state the limitation clearly and only answer what the "
    "context supports. "
    "Do not fill gaps with outside knowledge. "
    "Cite sources using [n] notation (e.g. [1], [2]). "
    + _FLUENT_PROSE_RULE
    + _SOURCE_ISOLATION_RULE
)

# Deep Thinking 专用：在严格 grounded 的前提下要求机制级、分维度、带跨实体对比的**完整**回答。
# 去压缩关键：① 按信息点/维度分节展开，每节充分展开、勿人为缩短（修复「单次合成短而拘谨」）；
# ② 允许「有据推断」——证据部分相关但未逐字命中问题措辞时给出带 hedge 的推断，而非一律判
#   「无证据」全盘否定（修复「部分可支持→完全无证据」误判）。硬约束（禁臆造/禁跨源）保留。
_SYNTH_SYSTEM_DEEP = (
    "You are a rigorous research assistant writing a COMPREHENSIVE, in-depth, report-style "
    "evidence-grounded answer. Answer based solely on the provided context; do not use outside "
    "knowledge; cite every claim with [n] notation. "
    "Organize the answer into clearly-headed sections covering the distinct dimensions of the "
    "question (e.g. definition/background, mechanisms & methods, comparison across entities, "
    "timeline/trends, limitations, and a closing synthesis). Under each section develop the point "
    "fully, naming the specific mechanisms, techniques, datasets, models and terms that appear in "
    "the context rather than generic abstractions. "
    "Be thorough: when the evidence supports a point, expand it as far as the evidence allows and "
    "do NOT artificially shorten or compress; draw on every relevant retrieved source, not only "
    "the first few. "
    "When the question's framing (a claimed trend, shift, relationship or synthesis) is not "
    "stated verbatim in any single source but the evidence partially bears on it, do NOT "
    "refuse with 'no evidence'; instead synthesize a clearly hedged, evidence-grounded "
    "inference (e.g. '证据部分支持……' / 'the evidence partially supports …' / '可据 [n] 推断……') "
    "and cite the partial evidence. Reserve an explicit 'no evidence' statement only for points "
    "the context genuinely does not touch at all. Never invent facts or cross-attribute sources. "
    "For comparison or 'shared X of A and B' questions, enumerate the concrete dimensions; under "
    "each dimension give each entity's specific mechanism with its citation, then add a synthesis "
    "line on how they align. "
    + _FLUENT_PROSE_RULE
    + _SOURCE_ISOLATION_RULE
)


# 全文检索专用：上下文是**一整篇**文档，不是拼接的证据池。
# 故意不含 _SOURCE_ISOLATION_RULE——那条规则是防多篇证据张冠李戴的，单文档场景下没有可串的线，
# 硬塞进来只会让模型误以为还有别的来源。反过来要强调「覆盖全篇、别只答开头」。
_SYNTH_SYSTEM_FULLTEXT = (
    "You are a helpful academic assistant. The context below is the COMPLETE text of a single "
    "document. Answer the question based solely on this document; do not use outside knowledge. "
    "Draw on the whole document rather than only its opening sections, and when the question "
    "spans several parts of the text, cover each of them. "
    "If the document genuinely does not address the question, say so plainly instead of "
    "inventing an answer. "
    "Cite the document using [1] notation. "
    + _FLUENT_PROSE_RULE
)


def lang_instruction(answer_language: str) -> str:
    """把 answer_language（auto/zh/en）翻成给 LLM 的一句语言指令。

    公开导出而非私有：同一段 if/elif 在 api.ask 的 graph_only 与 deep 兜底分支各有一份，
    加第三、四份即踩中 CONVENTIONS §4「重复 3 次 → 提取」。
    """
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
) -> GenerationResult:
    """用证据合成带 [n] 引用的答案。

    契约：[n] 按 evidence 顺序编号（调用方据同序拼 sources）；evidence 为空返回
    `GenerationResult(text="", status=STATUS_EMPTY)`（由调用方决定兜底）；LLM 调用异常
    向上抛（由调用方处理，禁用 mock 兜底）。返回结构化结果而非裸字符串——调用方需要按
    status（reasoning_only/length/content_filter/…）分流，而不是只看 text 是否为空。
    style="deep" 选用机制级/分维度/带对比的 deep 合成模板，否则用通用模板。
    source_labels（doc_id→来源标签）给每条证据标注来源文档，防跨文档串线；None 时不标注。
    """
    if not evidence:
        return GenerationResult(text="", status=STATUS_EMPTY)
    base = _SYNTH_SYSTEM_DEEP if style == "deep" else _SYNTH_SYSTEM_BASE
    system = base + lang_instruction(answer_language)
    context = "\n\n---\n\n".join(
        f"[{i + 1}]{source_tag(chunk.doc_id, source_labels)} {chunk.text}"
        for i, chunk in enumerate(evidence)
    )
    user = f"Context:\n\n{context}\n\nQuestion: {question}"
    return await llm.generate_result(user, system_prompt=system, allow_mock=False)


async def synthesize_from_document(
    llm: LLMAdapter,
    question: str,
    document_text: str,
    *,
    title: str,
    answer_language: str = "auto",
) -> GenerationResult:
    """用**整篇文档**合成答案（全文检索模式）。

    契约：`document_text` **原样入 prompt，绝不截断**——全文检索的全部意义就在于模型看到全篇，
    在这里悄悄截断等于把功能变成一个更差的召回。因此超出模型上下文窗口时正确行为是**让调用
    失败**（`allow_mock=False` 保证不会掉进离线占位文本），由调用方转成明确错误告知用户，
    而不是返回半篇答案冒充完整回答。

    正文为空返回 `GenerationResult(text="", status=STATUS_EMPTY)`；LLM 调用异常向上抛。
    引用恒为 [1]（只有一个来源），调用方据此拼单条 sources。
    """
    if not document_text.strip():
        return GenerationResult(text="", status=STATUS_EMPTY)
    system = _SYNTH_SYSTEM_FULLTEXT + lang_instruction(answer_language)
    user = f"Document [1]: {title}\n\nFull text:\n\n{document_text}\n\nQuestion: {question}"
    return await llm.generate_result(user, system_prompt=system, allow_mock=False)


__all__ = [
    "lang_instruction",
    "source_tag",
    "synthesize_answer",
    "synthesize_from_document",
]
