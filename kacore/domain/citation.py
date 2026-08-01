"""Harvard 引用格式化（domain 层·纯值对象与格式化规则）。

为何存在：召回结果对用户呈现的是 `[n]` 数字标记甚至 chunk/doc id，既不可读也不可核。本模块把
「一条来源的书目字段」收敛为 `CitationRef` 值对象，并给出 Cite Them Right Harvard 的 in-text
与 reference list 两种**确定性**渲染。确定性是关键——引用由代码而非 LLM 生成，从根上杜绝编造
作者与年份；LLM 只负责在正文里放 `[n]` 占位，改写由 pipelines 层完成。

边界：本模块不认识 source dict 的键名、`DocumentChunk`、Zotero/local 元数据的存储形态。
dict → `CitationRef` 的映射属于 pipelines 层（`citation_rendering.py`）。本层零依赖。

已知限制：
① `ZoteroItem` 无 creator_types 字段（见 `adapters/zotero/`），无法区分 author/editor/translator，
   故 Harvard 的 `(ed.)` 后缀不可表达；补齐需新增字段 + 两个 adapter + 一次 migration。
② 排序用 `casefold()` 码点序，CJK 姓氏会整体排在拉丁姓氏之后；纠正需引入拼音依赖，
   而 domain 层不接受第三方依赖。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# 缺字段时的标准 Harvard 占位：宁可显式标注「佚名/无日期」，也不臆造作者年份。
ANON = "Anon."
NO_DATE = "n.d."

# Cite Them Right Harvard：正文内 4 位及以上作者缩写为 `et al.`（APA 7 是 3 位，改此常量即可）。
ET_AL_THRESHOLD = 4
# 参考文献表列全部作者，仅超过此数才降级为 `et al.`。
REFERENCE_MAX_AUTHORS = 20

# given name 最多取 3 个 token 生成缩写，避免超长中间名把短引撑爆。
_MAX_GIVEN_TOKENS = 3

_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class CitationRef:
    """一条可被 Harvard 渲染的来源，`source_n` 绑定正文里的 `[n]`。

    契约：
        - `surnames` 与 `initials` 等长同序；机构名/单名的 initial 为空串。
        - `initials` 只存缩写（`A.` / `A.K.` / `J.-P.`），不存完整 given name。
        - `pages` 为该 chunk 覆盖的页码，升序去重；空元组表示无页码定位。
        - `source_n` 不参与任何格式化，仅供上层回填点击态。
        - 所有字符串字段缺失时用空串而非 None，渲染函数负责降级为 `Anon.` / `n.d.`。
    """

    source_n: int
    doc_id: str
    title: str = ""
    surnames: tuple[str, ...] = ()
    initials: tuple[str, ...] = ()
    year: str = ""
    pages: tuple[int, ...] = ()
    venue: str = ""
    doi: str = ""
    url: str = ""
    item_type: str = ""


# ── 作者归一化 ────────────────────────────────────────────────


def _split_raw_creators(raw: object) -> list[str]:
    """把各种实际形态的 creators 原料摊平成字符串列表。

    现实输入有三源：Zotero 镜像的 `list[str]`（`"Last, First"` 或机构名裸串）、用户在文档界面
    手填后落进 `local_meta` 的**换行拼接字符串**、以及历史脏数据（None / 数字 / 嵌套）。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[str] = []
        for line in raw.split("\n"):
            items.extend(line.split(";"))
        return items
    if isinstance(raw, (list, tuple)):
        return [item if isinstance(item, str) else str(item) for item in raw]
    return []


def _initials_of(given: str) -> str:
    """由 given name 生成 Harvard 缩写：`Ashish Kumar` → `A.K.`，`Jean-Paul` → `J.-P.`。

    无拉丁字母的 given name（如中文名）返回空串——`张.` 既不是 Harvard 也不可读。
    """
    chunks: list[str] = []
    for token in given.split()[:_MAX_GIVEN_TOKENS]:
        parts = [p for p in (seg.strip() for seg in token.split("-")) if p]
        rendered = [f"{p[0].upper()}." for p in parts if _LATIN_RE.match(p[0])]
        if rendered:
            chunks.append("-".join(rendered))
    return "".join(chunks)


def normalize_creators(raw: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """把原始 creators 归一化为 `(surnames, initials)` 两个等长同序元组。

    切分规则：**有逗号**才切姓/名（`"Vaswani, Ashish"` → `Vaswani` + `A.`）；**无逗号**时整串
    即姓氏、缩写留空。绝不按空格启发式切分——那会把 `van der Berg`、`OpenAI`、
    `World Health Organization`、`张三` 全部切坏。代价是本地用户手填 `"Ashish Vaswani"` 会被
    整体当姓氏，这应由输入框提示 `姓, 名` 解决，而不是由解析器猜。
    """
    surnames: list[str] = []
    initials: list[str] = []
    for item in _split_raw_creators(raw):
        text = item.strip()
        if not text:
            continue
        if "," in text:
            left, _, right = text.partition(",")
            surname = " ".join(left.split())
            if not surname:
                # `", Ashish"` 这类只有名没有姓的脏数据整条丢弃，避免产出空姓氏条目。
                continue
            initial = _initials_of(right.strip())
        else:
            surname = " ".join(text.split())
            initial = ""
        surnames.append(surname)
        initials.append(initial)
    return tuple(surnames), tuple(initials)


# ── 页码 ──────────────────────────────────────────────────────


def format_pages(pages: Sequence[int]) -> str:
    """把页码序列渲染为 Harvard 页码段：`p. 3` / `pp. 3-5` / `pp. 3, 7`；无有效页码返回空串。

    连续区间压缩为 `起-止`，不连续则逐页列出。非数字与非正数页码静默丢弃（chunk 元数据里
    偶有 0 或字符串页码）。
    """
    nums: list[int] = []
    for page in pages or ():
        try:
            value = int(page)
        except (TypeError, ValueError):
            continue
        if value > 0:
            nums.append(value)
    ordered = sorted(set(nums))
    if not ordered:
        return ""
    if len(ordered) == 1:
        return f"p. {ordered[0]}"
    if ordered[-1] - ordered[0] == len(ordered) - 1:
        return f"pp. {ordered[0]}-{ordered[-1]}"
    return "pp. " + ", ".join(str(n) for n in ordered)


# ── 渲染 ──────────────────────────────────────────────────────


def _authors_in_text(ref: CitationRef) -> str:
    count = len(ref.surnames)
    if count == 0:
        return ANON
    if count == 1:
        return ref.surnames[0]
    if count >= ET_AL_THRESHOLD:
        return f"{ref.surnames[0]} et al."
    if count == 2:
        return f"{ref.surnames[0]} and {ref.surnames[1]}"
    return f"{', '.join(ref.surnames[:-1])} and {ref.surnames[-1]}"


def _authors_reference(ref: CitationRef) -> str:
    if not ref.surnames:
        return ANON
    names = [
        f"{surname}, {initial}" if initial else surname
        for surname, initial in zip(ref.surnames, ref.initials)
    ]
    if len(names) > REFERENCE_MAX_AUTHORS:
        return f"{names[0]} et al."
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def harvard_in_text(ref: CitationRef, *, with_page: bool = True) -> str:
    """渲染 in-text 短引的**内层**串，不含外层括号：`Vaswani et al., 2017, p. 3`。

    刻意不含括号：多条引用合并时外层只包一对括号（`harvard_in_text_group`），且前端要按
    内层串做最长匹配还原点击态——带括号会让合并形式无法拆分。
    """
    parts = [_authors_in_text(ref), ref.year.strip() or NO_DATE]
    if with_page:
        pages = format_pages(ref.pages)
        if pages:
            parts.append(pages)
    return ", ".join(parts)


def harvard_in_text_group(refs: Sequence[CitationRef]) -> str:
    """把相邻的多条引用合并为一对括号：`(A, 2020, p. 1; B, 2021)`；空输入返回空串。"""
    if not refs:
        return ""
    return "(" + "; ".join(harvard_in_text(ref) for ref in refs) + ")"


def harvard_reference(ref: CitationRef) -> str:
    """渲染参考文献表条目（文档级，**不含页码**）。

    形如 `Vaswani, A. and Shazeer, N. (2017) 'Attention is all you need', NeurIPS. doi: 10.x.`。
    逐级降级：有 venue 时标题加引号并跟容器名，无 venue 时标题独立成句；定位符优先 doi，
    其次 url，都没有就省略。
    """
    segments = [f"{_authors_reference(ref)} ({ref.year.strip() or NO_DATE})"]
    title = ref.title.strip()
    venue = ref.venue.strip()
    if title:
        segments.append(f"'{title}'," if venue else f"{title}.")
    if venue:
        segments.append(f"{venue}.")
    doi = ref.doi.strip()
    url = ref.url.strip()
    if doi:
        segments.append(f"doi: {doi}.")
    elif url:
        segments.append(f"Available at: {url}.")
    return " ".join(segments)


def reference_sort_key(ref: CitationRef) -> tuple[str, str, tuple[int, str], str, str]:
    """参考文献表排序键：首作者姓 → 其余作者 → 年份 → 标题 → doc_id。

    `Anon.` 按字面归入 A 位（Cite Them Right 不单独分桶）；`n.d.` 排在同作者有年份条目之前。
    末位 `doc_id` 是确定性兜底——历史消息回放两次必须得到完全相同的顺序。
    """
    primary = (ref.surnames[0] if ref.surnames else ANON).casefold()
    rest = " ".join(ref.surnames[1:]).casefold()
    year = ref.year.strip()
    return (primary, rest, (1, year) if year else (0, ""), ref.title.casefold(), ref.doc_id)


__all__ = [
    "ANON",
    "ET_AL_THRESHOLD",
    "NO_DATE",
    "REFERENCE_MAX_AUTHORS",
    "CitationRef",
    "format_pages",
    "harvard_in_text",
    "harvard_in_text_group",
    "harvard_reference",
    "normalize_creators",
    "reference_sort_key",
]
