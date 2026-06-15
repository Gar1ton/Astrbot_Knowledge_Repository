"""Deep Thinking 各 LLM 步骤的 prompt 模板与严格 JSON 解析（pipelines 层）。

为何独立成文件：把 PLAN / SEA / REFINE 三步的 prompt 与解析契约集中，使
orchestrator 只关心控制流。解析失败抛 JsonContractError（与「LLM 调用异常」区分）——
前者由 orchestrator 重试/按步降级，后者触发 baseline 回退。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.domain.deep_thinking import ChecklistItem
from core.pipelines.answer_synthesis import source_tag

if TYPE_CHECKING:
    from core.domain.deep_thinking import Checklist, EvidenceItem
    from core.domain.models import DocumentChunk

# 单条证据注入 prompt 时的文本截断长度，防止 prompt 体积随证据线性膨胀。
_EVIDENCE_TEXT_CLIP = 320


class JsonContractError(ValueError):
    """LLM 有响应但 JSON 不符合契约（缺字段/非对象/无法解析）。

    与 LLM 调用异常（generate 抛出）语义不同：本错误可重试/按步降级，调用异常则回退。
    """


def _str_list(value: Any) -> list[str]:
    """宽容解析 LLM 输出中的字符串列表；非列表按单个字符串处理。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 通用 JSON 抽取 ──────────────────────────────────────────
def extract_json_object(raw: str) -> dict[str, Any]:
    """从 LLM 原始输出中抽取首个 JSON 对象。

    容忍 ```json fence 包裹与前后说明文字：去 fence 后截取首个 '{' 到末个 '}'。
    无法定位或解析失败、根非对象 → JsonContractError。
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise JsonContractError("no JSON object found")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise JsonContractError(str(exc)) from exc
    if not isinstance(obj, dict):
        raise JsonContractError("JSON root is not an object")
    return obj


# ── PLAN：分解 + checklist（合并单次调用）──────────────────
PLAN_SYSTEM = (
    "你是研究规划助手。把用户问题拆为可验证的信息点清单、检索子查询和证据计划。"
    "优先识别关键实体、时间范围、术语、章节/图表锚点和必须找到的证据类型。"
    "只输出 JSON，不要任何额外文字。"
)


def build_plan_prompt(query: str, max_sub_queries: int) -> str:
    return (
        f"用户问题：{query}\n\n"
        "请输出 JSON，格式：\n"
        '{"answer_outline":["回答结构要点"],'
        '"must_have_evidence":["必须找到的证据类型"],'
        '"search_hints":["关键实体/术语/章节锚点"],'
        '"checklist":[{"id":"c1","text":"需要回答的一个信息点","critical":true,'
        '"evidence_type":"definition|direct_quote|comparison|timeline|section_anchor",'
        '"search_hints":["可用于检索的术语"]}],'
        '"sub_queries":[{"query":"聚焦某方面且含关键词的检索query","type":"semantic|keyword|anchor"}]}\n'
        f"要求：checklist 每项给稳定 id（c1,c2,...）；critical=true 表示缺它就无法回答；"
        f"sub_queries 给 1~{max_sub_queries} 个、彼此覆盖不同方面；"
        "优先让 sub_queries 分散覆盖：定义/背景、机制、对比、时间线、章节锚点、原文证据；"
        "若问题在比较多个对象或问『A 与 B 共享的 X』，必须为每个对象分别铺机制探针"
        "（如『A 的机制/设计』『B 的机制/设计』），再加跨对象对比探针，确保两侧的具体机制都被召回；"
        "若问题涉及「这批文献」「多篇论文」「共同探讨」「横向对比」「纵观文献」，sub_queries 必须覆盖"
        "候选论文名/年份/arXiv id、数据集名、模型名、方法名、表格/图/章节锚点，避免只查一个泛化概念；"
        "不要生成答案，只规划需要哪些证据。"
    )


def parse_plan(raw: str) -> tuple[list[ChecklistItem], list[str]]:
    """解析 PLAN 输出为 (checklist items, sub_queries)。两者缺失或空 → JsonContractError。"""
    obj = extract_json_object(raw)
    raw_items = obj.get("checklist")
    raw_queries = obj.get("sub_queries")
    if not isinstance(raw_items, list) or not isinstance(raw_queries, list):
        raise JsonContractError("checklist/sub_queries must be lists")
    items: list[ChecklistItem] = []
    global_hints = _str_list(obj.get("search_hints"))
    for index, entry in enumerate(raw_items):
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        item_hints = _str_list(entry.get("search_hints"))
        items.append(
            ChecklistItem(
                id=str(entry.get("id") or f"c{index + 1}"),
                text=text,
                critical=bool(entry.get("critical", False)),
                evidence_type=str(entry.get("evidence_type") or "").strip(),
                search_hints=item_hints or global_hints,
            )
        )
    sub_queries: list[str] = []
    for q in raw_queries:
        if isinstance(q, dict):
            text = str(q.get("query") or q.get("text") or q.get("q") or "").strip()
        else:
            text = str(q).strip()
        if text:
            sub_queries.append(text)
    if not items or not sub_queries:
        raise JsonContractError("empty checklist or sub_queries")
    return items, sub_queries


# ── SEA：结构化充分性审计 ───────────────────────────────────
SEA_SYSTEM = (
    "你是证据审计助手。依据信息点清单审计已收集证据，输出逐项 coverage matrix。"
    "必须区分 supported、partial、missing、contradicted，并指出支撑 chunk、缺口原因、"
    "下一步检索动作和整体是否足以回答。"
    "比较多篇论文或多个对象时，supported 必须满足来源约束：不能用单篇/单来源证据支撑跨论文结论；"
    "若证据来源与断言对象不一致，标为 partial 或 contradicted。"
    "同时主动从已召回证据里发现 checklist 尚未覆盖、但与问题高度相关的新机制/新论点，"
    "列入 discovered_aspects 以供深挖。只输出 JSON，不要任何额外文字。"
)


@dataclass
class SeaCoverageItem:
    checklist_id: str = ""
    status: str = ""
    supporting_chunk_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    why_missing: str = ""
    next_action: str = ""
    gap_type: str = ""
    gap_query: str = ""


@dataclass
class SeaDiscoveredItem:
    """SEA 从已召回证据里新发现、checklist 尚未覆盖的探索性 aspect。

    与「答案阻塞缺口」(gaps) 严格区分：discovered 只驱动 REFINE/trace 深挖，
    **不进** soft_missing/verify_missing/正文告警，避免开放式深挖重造告警墙。
    """

    text: str = ""
    why_relevant: str = ""
    search_hints: list[str] = field(default_factory=list)
    gap_type: str = ""


@dataclass
class SeaResult:
    satisfied_ids: set[str] = field(default_factory=set)
    gaps: list[str] = field(default_factory=list)
    conflicting_chunk_ids: set[str] = field(default_factory=set)
    sufficient: bool = False
    coverage: list[SeaCoverageItem] = field(default_factory=list)
    discovered: list[SeaDiscoveredItem] = field(default_factory=list)


def build_sea_prompt(
    query: str,
    checklist: Checklist,
    evidence: list[EvidenceItem],
    clip: int = _EVIDENCE_TEXT_CLIP,
    source_labels: dict[str, str] | None = None,
) -> str:
    checklist_lines = "\n".join(
        f'- {item.id}{"[关键]" if item.critical else ""}: {item.text}'
        for item in checklist.items
    )
    evidence_lines = "\n".join(
        f"[{item.chunk.chunk_id}]{source_tag(item.chunk.doc_id, source_labels)} "
        f"{item.chunk.text[:clip]}"
        for item in evidence
    )
    return (
        f"原始问题：{query}\n\n"
        f"信息点清单：\n{checklist_lines or '（空）'}\n\n"
        f"已收集证据（每条前缀为 chunk_id）：\n{evidence_lines or '（空）'}\n\n"
        "请输出 JSON，格式：\n"
        '{"coverage":[{"checklist_id":"c1","status":"supported|partial|missing|contradicted",'
        '"supporting_chunk_ids":["chunk_id"],"confidence":0.8,"why_missing":"缺什么",'
        '"next_action":"definition|direct_quote|comparison|timeline|conflict_resolution|section_anchor",'
        '"gap_query":"下一轮补检 query"}],'
        '"satisfied_ids":["c1"],"gaps":[{"checklist_id":"c2","text":"还缺什么"}],'
        '"discovered_aspects":[{"text":"证据里出现、清单未覆盖的新机制/论点",'
        '"why_relevant":"为何与问题相关","search_hints":["可检索术语"],'
        '"gap_type":"definition|comparison|section_anchor"}],'
        '"conflicting_chunk_ids":["chunk_id"],"sufficient":false}\n'
        "satisfied_ids 用清单里的 id；conflicting_chunk_ids 用上面的 chunk_id；"
        "gaps 是「回答必需但仍缺」的阻塞缺口；discovered_aspects 是「证据里值得深挖的新角度」"
        "（两者不要混填，没有就给空数组）；"
        "sufficient 仅当核心信息点已 supported 且无高价值未探索 aspect 时才为 true；"
        "多来源对比题中，单一来源证据不得支撑跨来源结论；引用对象与来源不一致时必须标 partial 或 contradicted；"
        "不要把只有主题相关但不能支撑断言的片段标为 supported。"
    )


def parse_sea(raw: str) -> SeaResult:
    """解析 SEA 输出。缺 sufficient 字段 → JsonContractError（核心判据必须有）。"""
    obj = extract_json_object(raw)
    if "sufficient" not in obj:
        raise JsonContractError("missing 'sufficient'")
    coverage: list[SeaCoverageItem] = []
    coverage_satisfied: set[str] = set()
    coverage_conflicts: set[str] = set()
    coverage_gaps: list[str] = []
    for entry in obj.get("coverage", []) or []:
        if not isinstance(entry, dict):
            continue
        checklist_id = str(entry.get("checklist_id") or entry.get("id") or "").strip()
        status = str(entry.get("status") or "").strip().lower()
        supporting_ids = _str_list(entry.get("supporting_chunk_ids"))
        item = SeaCoverageItem(
            checklist_id=checklist_id,
            status=status,
            supporting_chunk_ids=supporting_ids,
            confidence=_float_or_none(entry.get("confidence")),
            why_missing=str(entry.get("why_missing") or "").strip(),
            next_action=str(entry.get("next_action") or "").strip(),
            gap_type=str(entry.get("gap_type") or entry.get("next_action") or "").strip(),
            gap_query=str(entry.get("gap_query") or "").strip(),
        )
        coverage.append(item)
        if checklist_id and status == "supported":
            coverage_satisfied.add(checklist_id)
        if status in {"partial", "missing", "contradicted"}:
            gap_text = item.gap_query or item.why_missing or item.next_action or checklist_id
            if gap_text:
                coverage_gaps.append(gap_text)
        if status == "contradicted":
            coverage_conflicts.update(supporting_ids)
        coverage_conflicts.update(_str_list(entry.get("conflicting_chunk_ids")))
    gaps: list[str] = []
    for entry in obj.get("gaps", []) or []:
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
        else:
            text = str(entry).strip()
        if text:
            gaps.append(text)
    for gap in coverage_gaps:
        if gap not in gaps:
            gaps.append(gap)
    discovered: list[SeaDiscoveredItem] = []
    for entry in obj.get("discovered_aspects", []) or []:
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            discovered.append(
                SeaDiscoveredItem(
                    text=text,
                    why_relevant=str(entry.get("why_relevant") or "").strip(),
                    search_hints=_str_list(entry.get("search_hints")),
                    gap_type=str(entry.get("gap_type") or "").strip(),
                )
            )
        else:
            text = str(entry).strip()
            if text:
                discovered.append(SeaDiscoveredItem(text=text))
    return SeaResult(
        satisfied_ids={str(x) for x in (obj.get("satisfied_ids") or [])} | coverage_satisfied,
        gaps=gaps,
        conflicting_chunk_ids={str(x) for x in (obj.get("conflicting_chunk_ids") or [])}
        | coverage_conflicts,
        sufficient=bool(obj.get("sufficient", False)),
        coverage=coverage,
        discovered=discovered,
    )


# ── REFINE：用缺口生成补充查询 ──────────────────────────────
REFINE_SYSTEM = (
    "你是检索优化助手。针对仍缺失的信息点和缺口类型，生成用于补齐证据的精准检索子查询。"
    "根据 definition、direct_quote、comparison、timeline、conflict_resolution、section_anchor "
    "等类型选择不同关键词和锚点策略。"
    "query 要可检索，优先包含论文名、方法名、数据集名、模型名、表格名、图号、章节名或 arXiv id；"
    "避免只输出「缺少定义」「缺少对比」这类泛化短语。"
    "只输出 JSON，不要任何额外文字。"
)


def build_refine_prompt(gaps: list[str]) -> str:
    gap_lines = "\n".join(f"- {g}" for g in gaps)
    return (
        f"仍缺失的信息点：\n{gap_lines or '（空）'}\n\n"
        '请输出 JSON：{"gap_queries":[{"query":"补充检索query",'
        '"type":"definition|direct_quote|comparison|timeline|conflict_resolution|section_anchor"}]}\n'
        "每个缺口给一个聚焦、含关键词或章节/图表锚点的检索 query。"
        "优先把缺口改写成包含论文名/数据集名/模型名/方法名/表格或章节锚点的短 query。"
    )


def parse_refine(raw: str) -> list[str]:
    obj = extract_json_object(raw)
    raw_queries = obj.get("gap_queries")
    if not isinstance(raw_queries, list):
        raise JsonContractError("gap_queries must be a list")
    queries: list[str] = []
    for q in raw_queries:
        if isinstance(q, dict):
            text = str(q.get("query") or q.get("text") or q.get("q") or "").strip()
        else:
            text = str(q).strip()
        if text:
            queries.append(text)
    return queries


# ── VERIFY：答案级 verification（response scoring）─────────────
VERIFY_SYSTEM = (
    "你是答案校验助手。逐条审计答案中的断言是否被证据和引用支撑，检查遗漏、"
    "引用错配、证据外断言和矛盾。每条证据都标注了来源文档（来源），"
    "若某断言把某来源文档的发现/方法/局限归到了另一来源（跨来源张冠李戴），"
    "一律计入 citation_mismatches。missing 应输出可直接补检的短句；citation_mismatches 必须写明"
    "「断言 X 引用了 [n]，但 [n] 属于 Y 来源/不支持该断言」。只输出 JSON，不要任何额外文字。"
)


@dataclass
class VerifyResult:
    supported: bool = False
    complete: bool = False
    missing: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    missing_citations: list[str] = field(default_factory=list)
    citation_mismatches: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)


def build_verify_prompt(
    question: str,
    answer: str,
    evidence: list[DocumentChunk],
    clip: int = _EVIDENCE_TEXT_CLIP,
    source_labels: dict[str, str] | None = None,
) -> str:
    evidence_lines = "\n".join(
        f"[{i + 1}]{source_tag(chunk.doc_id, source_labels)} {chunk.text[:clip]}"
        for i, chunk in enumerate(evidence)
    )
    return (
        f"问题：{question}\n\n"
        f"答案：\n{answer}\n\n"
        f"证据（每条前缀为编号）：\n{evidence_lines or '（空）'}\n\n"
        '请输出 JSON：{"supported":true,"complete":true,"missing":[],'
        '"unsupported_claims":[],"missing_citations":[],"citation_mismatches":[],'
        '"contradictions":[]}\n'
        "supported：答案的每个断言是否都能在证据中找到支撑（有任何证据外断言/幻觉则 false）；"
        "complete：是否完整回答了问题；missing：仍缺失或未被证据支撑的点（用于补充检索）；"
        "unsupported_claims 逐条列出无证据支撑的答案断言；"
        "missing_citations 列出需要引用但没有引用的断言；"
        "citation_mismatches 列出引用编号与证据不匹配的断言，格式应说明断言、引用编号和该编号实际来源；"
        "missing 里的每项都应能直接作为下一轮补检 query；contradictions 列出与证据冲突的断言。"
    )


def parse_verify(raw: str) -> VerifyResult:
    """解析 VERIFY 输出。缺 supported/complete → JsonContractError（核心判据必须有）。"""
    obj = extract_json_object(raw)
    if "supported" not in obj or "complete" not in obj:
        raise JsonContractError("missing 'supported'/'complete'")
    missing: list[str] = []
    for entry in obj.get("missing", []) or []:
        text = str(entry.get("text", "")).strip() if isinstance(entry, dict) else str(entry).strip()
        if text:
            missing.append(text)
    unsupported_claims = _str_list(obj.get("unsupported_claims"))
    missing_citations = _str_list(obj.get("missing_citations"))
    citation_mismatches = _str_list(obj.get("citation_mismatches"))
    contradictions = _str_list(obj.get("contradictions"))
    for text in unsupported_claims + missing_citations + citation_mismatches + contradictions:
        if text and text not in missing:
            missing.append(text)
    return VerifyResult(
        supported=bool(obj.get("supported", False)),
        complete=bool(obj.get("complete", False)),
        missing=missing,
        unsupported_claims=unsupported_claims,
        missing_citations=missing_citations,
        citation_mismatches=citation_mismatches,
        contradictions=contradictions,
    )


__all__ = [
    "JsonContractError",
    "extract_json_object",
    "PLAN_SYSTEM",
    "SEA_SYSTEM",
    "REFINE_SYSTEM",
    "VERIFY_SYSTEM",
    "SeaCoverageItem",
    "SeaDiscoveredItem",
    "SeaResult",
    "VerifyResult",
    "build_plan_prompt",
    "parse_plan",
    "build_sea_prompt",
    "parse_sea",
    "build_refine_prompt",
    "parse_refine",
    "build_verify_prompt",
    "parse_verify",
]
