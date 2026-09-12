"""通用书籍标题识别的纯函数测试（无 I/O）。

覆盖 Chapter/Part/§ 前缀标题与无编号标题启发式，以及明显不是标题的正文句子应被拒绝。
"""
from __future__ import annotations

from kacore.managers.generic_headings import (
    detect_chapter_or_part_heading,
    detect_generic_heading,
    detect_section_sign_heading,
    looks_like_unnumbered_heading,
)


def test_chapter_with_arabic_number_and_title() -> None:
    result = detect_chapter_or_part_heading("Chapter 3: The Long Road Home")
    assert result == ("Chapter 3", "The Long Road Home", 1)


def test_chapter_with_roman_numeral_no_title() -> None:
    result = detect_chapter_or_part_heading("Chapter IV")
    assert result == ("Chapter IV", "", 1)


def test_part_heading_detected() -> None:
    result = detect_chapter_or_part_heading("Part II: Foundations")
    assert result == ("Part II", "Foundations", 1)


def test_ordinary_sentence_is_not_chapter_heading() -> None:
    assert detect_chapter_or_part_heading("This chapter covers many topics in detail.") is None


def test_section_sign_heading_with_subsection() -> None:
    result = detect_section_sign_heading("§1.2 Background")
    assert result == ("§1.2", "Background", 2)


def test_section_sign_heading_top_level() -> None:
    result = detect_section_sign_heading("§5")
    assert result == ("§5", "", 1)


def test_unnumbered_short_title_is_recognized() -> None:
    assert looks_like_unnumbered_heading("Introduction") is True
    assert looks_like_unnumbered_heading("Bibliography") is True
    assert looks_like_unnumbered_heading("结语") is True  # 结语


def test_ordinary_sentence_is_not_unnumbered_heading() -> None:
    text = "This is a normal sentence that ends with a period."
    assert looks_like_unnumbered_heading(text) is False


def test_long_line_is_not_unnumbered_heading() -> None:
    text = "word " * 20
    assert looks_like_unnumbered_heading(text) is False


def test_mostly_digits_line_is_not_unnumbered_heading() -> None:
    assert looks_like_unnumbered_heading("12 34 56 78 90") is False


def test_generic_heading_prefers_chapter_over_unnumbered_heuristic() -> None:
    result = detect_generic_heading("Chapter 1: Origins")
    assert result == ("Chapter 1", "Origins", 1)


def test_generic_heading_falls_back_to_unnumbered() -> None:
    result = detect_generic_heading("Conclusion")
    assert result == ("Conclusion", "Conclusion", 1)


def test_generic_heading_none_for_ordinary_paragraph() -> None:
    text = "The results in this section demonstrate a clear and significant trend."
    assert detect_generic_heading(text) is None
