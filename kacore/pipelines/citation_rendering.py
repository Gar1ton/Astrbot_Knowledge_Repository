"""`[n]` → Harvard 引用的确定性改写（pipelines 层·展示视图）。

为何存在：合成 prompt 要求 LLM 用 `[n]` 引用，`[n]` 与 sources 同序对齐（见
`answer_synthesis.py` 的契约）。但 `[n]` 对用户既不可读也不可核。本模块在**答案已生成之后**
把 `[n]` 按 sources 的书目元数据确定性替换为 Harvard in-text 短引，并拼出去重排序的参考文献表。

为何不让 LLM 直接写 `(Author, Year)`：模型会编造不存在的作者/年份组合，且会破坏
`[n]`↔sources 的同序对齐契约（那是 deep thinking 审计与前端点击跳转的共同地基）。
改写放在最外层，orchestrator 与 prompt 层完全不受影响。

本模块是 domain `citation.py` 与 api 层 source dict 之间的唯一映射点——domain 不认识
dict 键名，api 不认识 Harvard 规则。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from kacore.domain.citation import (
    CitationRef,
    harvard_in_text,
    harvard_in_text_group,
    harvard_reference,
    normalize_creators,
    reference_sort_key,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, MutableMapping, Sequence

# 引用标记：`[1]` / `[1,2]` / `[1，2]`。
# `(?<!\\)` 排除 markdown 转义 `\[1\]` 与 LaTeX 行间公式起始符 `\[`；
# `\d{1,3}` 上界使 `[2024]`（裸年份）不可能命中。
_MARKER_RE = re.compile(r"(?<!\\)\[(\d{1,3}(?:\s*[,，]\s*\d{1,3})*)\]")

# 相邻标记之间只允许这些字符时才合并成一组引用（`[1][2]` / `[1] [2]` / `[1]、[2]`）。
_JOINABLE_GAP_RE = re.compile(r"^[\s,，、;；和]{0,3}$")

# 保护区：行内代码与 markdown 链接/图片内部的 `[n]` 不是引用。
_PROTECTED_RE = re.compile(r"`[^`\n]*`|!?\[[^\]]*\]\([^)]*\)")

# 引用式链接定义整行跳过：`[1]: https://…`。
_LINK_DEF_RE = re.compile(r"^\s{0,3}\[\d+\]:\s")

# 围栏代码块开关。
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# LLM 自己写的参考文献小节标题。
_REF_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?(?:\*\*)?\s*"
    r"(?:参考文献|引用文献|参考资料|引用|References?|Bibliography|Sources?)"
    r"\s*(?:\*\*)?\s*[:：]?\s*$",
    re.IGNORECASE,
)

# 尾块里「像书目」的行：列表项，或含引用标记。
_LIST_ITEM_RE = re.compile(r"^\s{0,3}(?:[-*+]\s|\d{1,3}[.)]\s)")

_REFERENCE_HEADING_DEFAULT = "参考文献"


# ── source dict → CitationRef ─────────────────────────────────


def _first_str(meta: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = meta.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def build_citation_refs(sources: Sequence[Mapping[str, Any]]) -> dict[int, CitationRef]:
    """把 api 层的 source dict 列表映射为 `{n: CitationRef}`。

    只读取 dict，不写回（写回由 `render_answer_with_references` 负责）。`n` 缺失或非正数的
    条目静默跳过——这类条目不可能被正文的 `[n]` 引用到。
    """
    refs: dict[int, CitationRef] = {}
    for source in sources:
        try:
            n = int(source.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0 or n in refs:
            continue
        surnames, initials = normalize_creators(source.get("creators"))
        metadata = source.get("metadata")
        pages_raw = source.get("pages")
        if not pages_raw and isinstance(metadata, dict):
            page_number = metadata.get("page_number")
            pages_raw = [page_number] if page_number is not None else []
        pages: list[int] = []
        for page in pages_raw or ():
            try:
                pages.append(int(page))
            except (TypeError, ValueError):
                continue
        refs[n] = CitationRef(
            source_n=n,
            doc_id=str(source.get("doc_id") or source.get("document_id") or ""),
            title=str(source.get("title") or "").strip(),
            surnames=surnames,
            initials=initials,
            year=_first_str(source, "year"),
            pages=tuple(sorted({p for p in pages if p > 0})),
            venue=_first_str(source, "venue"),
            doi=_first_str(source, "doi"),
            url=_first_str(source, "url"),
            item_type=_first_str(source, "item_type"),
        )
    return refs


# ── LLM 自写参考文献尾块剥离 ──────────────────────────────────


def strip_llm_reference_section(answer: str) -> tuple[str, int]:
    """剥离 LLM 自行追加的「参考文献 / References」尾块，返回 `(正文, 尾块起始行号)`。

    只有当尾块里非空行的**过半**是列表项或带引用标记时才判定为书目并删除；否则保留原文，
    并把起始行号返回给调用方，让改写跳过该区间（正文里正常出现的「参考资料」小节不该被吞）。
    行号为 -1 表示没有识别到尾块。
    """
    lines = answer.split("\n")
    heading_idx = -1
    for idx in range(len(lines) - 1, -1, -1):
        if _REF_HEADING_RE.match(lines[idx]):
            heading_idx = idx
            break
    if heading_idx < 0:
        return answer, -1
    body = [line for line in lines[heading_idx + 1 :] if line.strip()]
    if not body:
        return answer, heading_idx
    bibliographic = sum(
        1 for line in body if _LIST_ITEM_RE.match(line) or _MARKER_RE.search(line)
    )
    if bibliographic * 2 >= len(body):
        return "\n".join(lines[:heading_idx]).rstrip(), -1
    return answer, heading_idx


# ── `[n]` 改写 ────────────────────────────────────────────────


def _protected_spans(line: str) -> list[tuple[int, int]]:
    return [m.span() for m in _PROTECTED_RE.finditer(line)]


def _is_protected(span: tuple[int, int], protected: list[tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in protected)


def _parse_numbers(raw: str) -> list[int]:
    numbers: list[int] = []
    for piece in re.split(r"[,，]", raw):
        piece = piece.strip()
        if piece.isdigit():
            numbers.append(int(piece))
    return numbers


def _rewrite_line(line: str, refs: Mapping[int, CitationRef]) -> str:
    if _LINK_DEF_RE.match(line):
        return line
    protected = _protected_spans(line)
    matches = [m for m in _MARKER_RE.finditer(line) if not _is_protected(m.span(), protected)]
    if not matches:
        return line

    # 先把相邻标记聚成组，再统一替换。朴素的 re.sub 回调看不到邻居，无法合并 `[1][2]`。
    groups: list[list[re.Match[str]]] = []
    for match in matches:
        if groups and _JOINABLE_GAP_RE.match(line[groups[-1][-1].end() : match.start()]):
            groups[-1].append(match)
        else:
            groups.append([match])

    out: list[str] = []
    cursor = 0
    for group in groups:
        start, end = group[0].start(), group[-1].end()
        out.append(line[cursor:start])
        out.append(_render_group(line[start:end], group, refs))
        cursor = end
    out.append(line[cursor:])
    return "".join(out)


def _render_group(
    original: str, group: list[re.Match[str]], refs: Mapping[int, CitationRef]
) -> str:
    """渲染一组相邻标记：合法编号合并为一对括号，越界编号原样留在其后。

    越界编号（模型幻觉出的 `[9]`，但只有 5 条证据）**绝不**渲染成 `(Anon., n.d.)`——那等于
    凭空捏造一条引用，比留着原始标记更有害。
    """
    picked: list[CitationRef] = []
    seen: set[tuple[str, tuple[int, ...]]] = set()
    leftovers: list[str] = []
    for match in group:
        for n in _parse_numbers(match.group(1)):
            ref = refs.get(n)
            if ref is None:
                leftovers.append(f"[{n}]")
                continue
            key = (ref.doc_id, ref.pages)
            if key in seen:
                continue
            seen.add(key)
            picked.append(ref)
    if not picked:
        # 整组都越界：原样保留，连空白与分隔符都不动。
        return original
    rendered = harvard_in_text_group(picked)
    return rendered + "".join(f" {item}" for item in leftovers)


def rewrite_citations(answer: str, refs: Mapping[int, CitationRef]) -> str:
    """把正文里的 `[n]` 改写为 Harvard in-text 短引；`refs` 为空时原样返回。

    逐行处理并维护围栏代码块开关：代码块内的 `[n]` 是代码不是引用。替换只做位置替换，
    绝不围绕标点重排语序。
    """
    if not refs or not answer:
        return answer
    body, skip_from = strip_llm_reference_section(answer)
    lines = body.split("\n")
    in_fence = False
    out: list[str] = []
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or (skip_from >= 0 and idx >= skip_from):
            out.append(line)
            continue
        out.append(_rewrite_line(line, refs))
    return "\n".join(out)


# ── 参考文献表 ────────────────────────────────────────────────


def build_reference_list(refs: Iterable[CitationRef]) -> list[str]:
    """按文档去重、按 Harvard 规则排序，产出不带编号的参考文献条目。

    主键 `doc_id`（保留 `source_n` 最小者），次键为渲染后的整条 reference 串——后者捕获
    同一篇文献被以不同 `doc_id` 二次入库的情况。
    """
    by_doc: dict[str, CitationRef] = {}
    for ref in refs:
        key = ref.doc_id or f"__n{ref.source_n}"
        current = by_doc.get(key)
        if current is None or ref.source_n < current.source_n:
            by_doc[key] = ref
    lines: list[str] = []
    seen: set[str] = set()
    for ref in sorted(by_doc.values(), key=reference_sort_key):
        rendered = harvard_reference(ref)
        if rendered in seen:
            continue
        seen.add(rendered)
        lines.append(rendered)
    return lines


def annotate_sources(sources: Sequence[MutableMapping[str, Any]]) -> dict[int, CitationRef]:
    """就地给每个 source 补 `harvard_in_text` / `harvard_reference`，返回 `{n: CitationRef}`。

    就地写 dict 是**刻意的**副作用：同一份 sources 既落进 `chat_history` 又返回前端，两处必须
    拿到同一批 `harvard_in_text` 串，前端才能按串还原点击跳转。codex skill 的证据端点直接用
    本函数——agent 自己写正文，需要的是成品串而非原始 creators。
    """
    refs = build_citation_refs(sources)
    for source in sources:
        try:
            n = int(source.get("n") or 0)
        except (TypeError, ValueError):
            continue
        ref = refs.get(n)
        if ref is None:
            continue
        source["harvard_in_text"] = harvard_in_text(ref)
        source["harvard_reference"] = harvard_reference(ref)
    return refs


def render_answer_with_references(
    answer: str,
    sources: Sequence[MutableMapping[str, Any]],
    *,
    heading: str = _REFERENCE_HEADING_DEFAULT,
) -> tuple[str, list[str]]:
    """改写正文、就地补 source 的 harvard 字段、返回 `(含参考文献表的正文, references)`。"""
    refs = annotate_sources(sources)
    if not refs or not answer:
        return answer, []
    body = rewrite_citations(answer, refs)
    references = build_reference_list(refs.values())
    if not references:
        return body, []
    block = "\n".join(f"- {line}" for line in references)
    return f"{body}\n\n**{heading}**\n\n{block}", references


__all__ = [
    "annotate_sources",
    "build_citation_refs",
    "build_reference_list",
    "render_answer_with_references",
    "rewrite_citations",
    "strip_llm_reference_section",
]
