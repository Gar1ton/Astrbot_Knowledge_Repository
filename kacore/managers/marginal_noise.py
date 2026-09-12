"""页边噪声判据：重复标题与单次出版声明，限定位置且保留原文旁车。"""

from __future__ import annotations

import re

_ACCESS_STAMP_RE = re.compile(
    r"This content downloaded from\s+\S+\s+on\s+.+?\s+UTC\.?",
    re.I,
)
_ACCESS_TERMS_RE = re.compile(
    r"All use subject to\s+(?:https?://\S+|JSTOR Terms and Conditions)\.?",
    re.I,
)
_INLINE_ACCESS_PATTERNS = (
    re.compile(
        r"This content downloaded from\s+\S+\s+on\s+.*?\bUTC\b\.?",
        re.I,
    ),
    re.compile(
        r"All use subject to\s+(?:https?://about\.jstor\.org/terms/?|"
        r"JSTOR Terms and Conditions)\.?",
        re.I,
    ),
)


def is_publication_footer(line: str) -> bool:
    """只接受以出版标识起始的组合声明，不因正文/书目含 DOI 或版权词而删除。"""
    plain = re.sub(r"[*_`#]", "", line).strip()
    return bool(
        re.match(r"ISSN\b", plain, re.I)
        and re.search(r"\b\d{4}-[\dX]{4}\b", plain, re.I)
        and re.search(r"©|\bcopyright\b", plain, re.I)
        and re.search(r"https?://doi\.org/|\b(?:Group|Limited|Publisher)\b", plain, re.I)
    )


def is_running_heading(line: str, index: int, edge_indices: set[int]) -> bool:
    """只有首尾行的重复无编号标题可覆盖标题保护；正文中的同名标题照常保留。"""
    plain = re.sub(r"^[\s#*_]+", "", line).strip()
    return (
        index in edge_indices
        and bool(re.match(r"^\s*#{1,6}\s", line))
        and not re.match(r"(?:\d|§|Chapter\b|Part\b|Appendix\b)", plain, re.I)
    )


def publication_footer_indices(lines: list[str], margins: set[int]) -> set[int]:
    """版权声明可能折行，连同紧随其后的独立 DOI 一起清理，其他 DOI 保留。"""
    found = {i for i in margins if is_publication_footer(lines[i])}
    for i in list(found):
        for following in range(i + 1, min(len(lines), i + 5)):
            plain = lines[following].strip()
            if not plain:
                continue
            if re.fullmatch(r"(?:<u>)?https?://doi\.org/[^\s<>]+(?:</u>)?", plain):
                found.add(following)
            break
    return found


def access_stamp_indices(lines: list[str]) -> set[int]:
    """识别完整或至多三行折行的数据库下载戳，位置不限但必须整段严格匹配。

    这类戳在 PDF 文本流中不一定落在视觉页脚，因此不能仅检查首尾行；反过来，使用
    fullmatch、固定开头和 UTC 结尾，避免删除正文里对下载声明的普通讨论。
    """
    found: set[int] = set()
    for start, line in enumerate(lines):
        plain = re.sub(r"[*_`#]", "", line).strip()
        if _ACCESS_TERMS_RE.fullmatch(plain):
            found.add(start)
            continue
        if not re.match(r"This content downloaded from\b", plain, re.I):
            continue
        combined = ""
        for end in range(start, min(len(lines), start + 3)):
            fragment = re.sub(r"[*_`#]", "", lines[end]).strip()
            if fragment:
                combined = f"{combined} {fragment}".strip()
            if _ACCESS_STAMP_RE.fullmatch(combined):
                found.update(range(start, end + 1))
                break
    return found


def remove_inline_access_stamps(line: str, *, preserve_offsets: bool = False) -> str:
    """删除被转换器并入正文行的访问戳；完整替换范围严格，代码/公式保护由调用方负责。"""
    for pattern in _INLINE_ACCESS_PATTERNS:
        line = pattern.sub(
            (lambda match: " " * len(match.group(0))) if preserve_offsets else " ",
            line,
        )
    return line


__all__ = [
    "access_stamp_indices",
    "is_publication_footer",
    "is_running_heading",
    "publication_footer_indices",
    "remove_inline_access_stamps",
]
