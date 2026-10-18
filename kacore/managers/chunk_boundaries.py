"""切片边界识别：保留结构块、原始字符偏移和句末引用，不改写正文。"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s*(?:#{1,6}\s|§\s*\d|(?:Chapter|Part)\s+[\dIVXLCDM]+\b)", re.I)
_LIST = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s)")
_ABBREVIATION = re.compile(
    r"(?:\bet al|\bfig|\bfigure|\beq|e\.g|i\.e|\bno|\bvol|\bpp|\bdr|\bmr|\bmrs|\bprof|\bvs)\.$",
    re.I,
)


def structural_ranges(text: str) -> list[tuple[int, int]]:
    """标题独立成块，普通单换行留在段内；代码/公式内部空行不构成段界。"""
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    cursor = 0
    kind = ""
    fence = ""

    def flush(end: int) -> None:
        nonlocal start
        if start is not None:
            while end > start and text[end - 1] in "\r\n":
                end -= 1
            if end > start:
                ranges.append((start, end))
            start = None

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            if ((fence == "$$" and stripped == fence)
                    or (fence != "$$" and stripped.startswith(fence)
                        and not stripped[len(fence):].strip())):
                fence = ""
                flush(cursor + len(line))
        elif marker or stripped == "$$":
            flush(cursor)
            start = cursor
            fence = marker.group(1) if marker else "$$"
            kind = "fence"
        elif not stripped:
            flush(cursor)
        elif _HEADING.match(line):
            flush(cursor)
            start = cursor
            flush(cursor + len(line))
            kind = "heading"
        else:
            new_kind = "table" if stripped.startswith("|") else (
                "list" if _LIST.match(line) else "paragraph"
            )
            if new_kind != kind:
                flush(cursor)
            if start is None:
                start = cursor
            kind = new_kind
        cursor += len(line)
    flush(len(text))
    return ranges


def sentence_boundaries(text: str, start: int, end: int) -> list[int]:
    """句界包含闭引号与紧邻引用标记，跳过缩写、小数、URL 和括号内句点。"""
    boundaries: list[int] = []
    depth = 0
    for idx in range(start, end):
        char = text[idx]
        if char in "([（":
            depth += 1
        elif char in ")]）":
            depth = max(0, depth - 1)
        if char not in ".!?。！？" or depth:
            continue
        if char == ".":
            prefix = text[max(start, idx - 30):idx + 1]
            if _ABBREVIATION.search(prefix) or re.search(r"\b[A-Z]\.$", prefix):
                continue
            if idx + 1 < end and not (text[idx + 1].isspace() or text[idx + 1] in '\"”’」』'):
                continue
        boundary = idx + 1
        while boundary < end and text[boundary] in '\"\'”’」』)]）':
            boundary += 1
        citation = re.match(r"(?:<sup>.*?</sup>|\[\d+(?:[,–\- ]\d+)*\])", text[boundary:end])
        if citation:
            boundary += citation.end()
        if boundary < end and text[boundary] in ",;:":
            continue
        boundaries.append(boundary)
    return sorted(set(boundaries))


__all__ = ["sentence_boundaries", "structural_ranges"]
