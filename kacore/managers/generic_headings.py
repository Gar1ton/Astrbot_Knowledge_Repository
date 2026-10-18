"""通用书籍标题识别（managers 层，纯函数，无 I/O）。

补充 `chunking.py` 现有编号小节/thesis 正则未覆盖的书籍类标题：Chapter/Part 前缀
（阿拉伯数字或罗马数字）、§ 编号、以及无编号但格式明显的标题行（短标题、无结尾句读）。

当前由生产抽取或结构切片路径调用；无需新增解析器。

"""
from __future__ import annotations

import re

_ROMAN_RE = r"[IVXLCDM]+"
_CHAPTER_RE = re.compile(
    rf"^(?:#+\s*)?(?:\*\*)?Chapter\s+(?P<label>\d{{1,3}}|{_ROMAN_RE})\b\.?(?:\*\*)?"
    r"(?:[:.\s]+(?P<title>.*))?$",
    re.IGNORECASE,
)
_PART_RE = re.compile(
    rf"^(?:#+\s*)?(?:\*\*)?Part\s+(?P<label>\d{{1,3}}|{_ROMAN_RE})\b\.?(?:\*\*)?"
    r"(?:[:.\s]+(?P<title>.*))?$",
    re.IGNORECASE,
)
_SECTION_SIGN_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?§\s*(?P<label>\d+(?:\.\d+){0,4})\.?(?:\*\*)?"
    r"(?:\s+(?P<title>.*))?$"
)

_SENTENCE_END_RE = re.compile(r"[.!?。！？]\s*$")
_CJK_OR_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*|[㐀-䶿一-鿿]")


def _strip_markup(text: str) -> str:
    text = text.replace("*", "").replace("_", "").replace("`", "").replace("#", "")
    return re.sub(r"\s+", " ", text).strip()


def detect_chapter_or_part_heading(line: str) -> tuple[str, str, int] | None:
    """识别 "Chapter N" / "Part N"（阿拉伯或罗马数字编号）标题行。

    返回 (label, title, level)；label 形如 "Chapter 3"/"Part II"，level 恒为 1
    （书籍最高一级划分）。不匹配返回 None，不臆造标题。
    """
    stripped = line.strip()
    chapter = _CHAPTER_RE.match(stripped)
    if chapter:
        label = f"Chapter {chapter.group('label').upper()}"
        title = _strip_markup(chapter.group("title") or "")
        return label, title, 1
    part = _PART_RE.match(stripped)
    if part:
        label = f"Part {part.group('label').upper()}"
        title = _strip_markup(part.group("title") or "")
        return label, title, 1
    return None


def detect_section_sign_heading(line: str) -> tuple[str, str, int] | None:
    """识别 "§1.2" 风格标题行；level 按标号句点深度计（与数字小节规则一致）。"""
    match = _SECTION_SIGN_RE.match(line.strip())
    if not match:
        return None
    label = "§" + match.group("label")
    title = _strip_markup(match.group("title") or "")
    level = match.group("label").count(".") + 1
    return label, title, level


def looks_like_unnumbered_heading(line: str) -> bool:
    """判断一行是否像无编号标题（如 "Introduction"、"结语"、"Bibliography"）。

    启发式边界：短（2-60 字符）、词数不超过 8、不以句末标点收尾、字母/CJK 字符占多数——
    与正文长句区分，但不要求编号或特定关键词，允许任意语言的通用书籍标题。
    命中此启发式不代表 100% 是标题，供上层结合上下文（如是否独占一行、前后是否有空行）
    进一步判断，不单独作为删除或强分类依据。
    """
    stripped = _strip_markup(line)
    if not (2 <= len(stripped) <= 60):
        return False
    if _SENTENCE_END_RE.search(stripped):
        return False
    words = _CJK_OR_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    alpha_or_cjk = sum(1 for ch in stripped if ch.isalpha())
    if alpha_or_cjk < max(2, len(stripped) // 2):
        return False
    return True


def detect_generic_heading(line: str) -> tuple[str, str, int] | None:
    """组合入口：依次尝试 Chapter/Part → § → 无编号标题启发式。

    无编号标题命中时 label 直接取标题原文（无独立编号可用），level 恒为 1。
    """
    result = detect_chapter_or_part_heading(line)
    if result is not None:
        return result
    result = detect_section_sign_heading(line)
    if result is not None:
        return result
    stripped = _strip_markup(line)
    if looks_like_unnumbered_heading(line):
        return stripped, stripped, 1
    return None


__all__ = [
    "detect_chapter_or_part_heading",
    "detect_section_sign_heading",
    "looks_like_unnumbered_heading",
    "detect_generic_heading",
]
