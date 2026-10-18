"""脚注候选检测与正文关联（managers 层，纯函数，无 I/O）。

从 PDF 逐页原始抽取文本中分离页面尾部的脚注候选，并与同页正文中的引用点关联。

当前由生产抽取或结构切片路径调用；无需新增解析器。

启发式边界（诚实说明，不过度宣称）：
    - PyMuPDF4LLM 默认转换不保留上标格式，脚注引用点在纯文本里通常退化为紧贴前一个词的
      数字/符号（如 "结论14"）。本模块用「前面必须是词字符/收尾标点、后面必须是空白或
      收尾标点」的贴靠模式识别引用点，命中多处记 AMBIGUOUS、命中零处记 UNLINKED，两种情况
      都保留脚注原文，不臆造关联、不删除文本。真实 PDF 上的准确率需要用户用真实语料验证。
"""

from __future__ import annotations

import re
from dataclasses import replace

from kacore.domain.footnotes import FootnoteBlock, FootnoteLinkStatus

# 只在页面尾部这么多行内寻找脚注候选，避免把页面中段的编号列表/正文误判为脚注区。
_FOOTNOTE_ZONE_MAX_LINES = 15

# 数字标号：1-3 位数字，后面不能紧跟另一位数字（排除年份等长数字）。
_NUMERIC_MARKER_RE = re.compile(r"^(?P<marker>\d{1,3})(?!\d)[.\):]?\s+(?=\S)")
# 符号标号：常见脚注符号 * † ‡ § ¶（1-2 个重复，如 "**"）。
_SYMBOL_MARKER_RE = re.compile(r"^(?P<marker>[*†‡¶]{1,2})\s*(?=\S)")
# 字母标号：单个字母 + 句点/括号（如 "a." "b)"）。
_LETTER_MARKER_RE = re.compile(r"^(?P<marker>[a-zA-Z])[.\)]\s+(?=\S)")

_MARKER_PATTERNS = (_NUMERIC_MARKER_RE, _SYMBOL_MARKER_RE, _LETTER_MARKER_RE)


def _match_marker(line: str) -> re.Match[str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    for pattern in _MARKER_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return match
    return None


def extract_footnote_candidates(page_text: str, *, page: int) -> tuple[str, list[FootnoteBlock]]:
    """从单页原始文本尾部分离脚注候选，返回 (去脚注正文, 脚注候选列表)。

    契约：
        - 只扫描页面最后 `_FOOTNOTE_ZONE_MAX_LINES` 行；候选起始行必须匹配标号格式，且
          前面存在空行段落边界，或候选本身就是页面第一行（整页仅剩脚注的情形，见验收 C05）。
        - 找不到候选时原样返回 page_text 与空列表，不改动任何字符（不确定时不强删）。
        - source_start/source_end 是候选文本（含标号前缀）在传入 page_text 中的字符偏移，
          `page_text[source_start:source_end]` 与该脚注条目原文逐字符一致。
        - 一个页面可以分离出多条脚注（连续多个标号起始行各自成一条，中间非标号行视为
          上一条脚注的续行）。
    """
    lines = page_text.split("\n")
    total = len(lines)
    window_start = max(0, total - _FOOTNOTE_ZONE_MAX_LINES)

    zone_start_line: int | None = None
    for idx in range(window_start, total):
        if _match_marker(lines[idx]) is None:
            continue
        preceded_by_blank = idx == 0 or lines[idx - 1].strip() == ""
        if preceded_by_blank:
            zone_start_line = idx
            break

    if zone_start_line is None:
        return page_text, []

    body_lines = lines[:zone_start_line]
    zone_lines = lines[zone_start_line:]

    entries: list[list[str]] = []
    for line in zone_lines:
        if _match_marker(line) is not None:
            entries.append([line])
        elif entries:
            entries[-1].append(line)

    footnotes: list[FootnoteBlock] = []
    # body_lines 用 "\n" 拼接后长度 +1（换行符）即 zone 在原文中的起始偏移；
    # split("\n") / "\n".join(...) 互为逆运算，故按行长求和可精确回推偏移，无需二次搜索。
    cursor = sum(len(line) + 1 for line in body_lines)
    for entry_lines in entries:
        raw_text = "\n".join(entry_lines)
        start = cursor
        end = start + len(raw_text)
        marker_match = _match_marker(entry_lines[0])
        assert marker_match is not None  # entries 只由匹配过的行起始，恒成立
        leading_ws = len(entry_lines[0]) - len(entry_lines[0].lstrip())
        text = raw_text[leading_ws + marker_match.end() :].strip()
        footnotes.append(
            FootnoteBlock(
                page=page,
                marker=marker_match.group("marker"),
                text=text,
                source_start=start,
                source_end=end,
            )
        )
        cursor = end + 1  # 补回条目间被 split 消耗的换行符

    body_text = "\n".join(body_lines).rstrip("\n")
    return body_text, footnotes


def link_footnotes(body_text: str, footnotes: list[FootnoteBlock]) -> list[FootnoteBlock]:
    """在正文中查找与脚注 marker 贴靠的引用点，回填 link_status/body_marker_span。

    契约：只在传入的 body_text 范围内搜索——调用方保证 body_text 与 footnotes 同页/同正文流，
    本函数不做跨页搜索，天然避免不同章节复用同一 marker 时的串线（见验收 C03）。
    命中恰好一处记 LINKED；零处记 UNLINKED；多处记 AMBIGUOUS。三种情况下 footnote.text
    均不改变，只更新链接元数据，不删除、不臆造。
    """
    linked: list[FootnoteBlock] = []
    for footnote in footnotes:
        pattern = re.compile(
            r"(?<=[\w)\].,;:!?”\"])[ \t]*(?P<ref>"
            + re.escape(footnote.marker)
            + r")(?=[\s.,;:!?)\]]|$)"
        )
        matches = list(pattern.finditer(body_text))
        if not matches:
            linked.append(footnote)
        elif len(matches) > 1:
            linked.append(replace(footnote, link_status=FootnoteLinkStatus.AMBIGUOUS))
        else:
            match = matches[0]
            linked.append(
                replace(
                    footnote,
                    link_status=FootnoteLinkStatus.LINKED,
                    body_marker_span=(match.start("ref"), match.end("ref")),
                )
            )
    return linked


def separate_footnotes(page_text: str, *, page: int) -> tuple[str, list[FootnoteBlock]]:
    """提取并关联单页脚注的组合入口：extract_footnote_candidates + link_footnotes。"""
    body_text, footnotes = extract_footnote_candidates(page_text, page=page)
    if not footnotes:
        return body_text, footnotes
    return body_text, link_footnotes(body_text, footnotes)


__all__ = [
    "extract_footnote_candidates",
    "link_footnotes",
    "separate_footnotes",
]
