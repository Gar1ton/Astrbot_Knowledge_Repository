"""结构块保护后行修复的纯函数测试（无 I/O）。

覆盖验收矩阵 C04 相关场景：表格/列表在断词修复中不被压成一行，代码块/公式块原样保留，
纯正文段落的断词/单换行合并行为与既有算法一致。
"""
from __future__ import annotations

from kacore.managers.structural_protection import (
    protected_line_mask,
    repair_wrapped_text_preserving_blocks,
)


def test_markdown_table_rows_survive_repair() -> None:
    text = (
        "Intro sentence before the table.\n"
        "\n"
        "| Header A | Header B |\n"
        "| --- | --- |\n"
        "| cell 1 | cell 2 |\n"
        "\n"
        "Closing sentence after the table."
    )

    repaired = repair_wrapped_text_preserving_blocks(text)

    assert "| Header A | Header B |" in repaired
    assert "| --- | --- |" in repaired
    assert "| cell 1 | cell 2 |" in repaired
    # 三行表格仍各自独立成行，没有被断词修复揉进一行。
    lines = repaired.split("\n")
    assert "| Header A | Header B |" in lines
    assert "| cell 1 | cell 2 |" in lines


def test_list_items_survive_repair() -> None:
    text = "Before the list.\n\n- first item\n- second item\n- third item\n\nAfter the list."

    repaired = repair_wrapped_text_preserving_blocks(text)
    lines = repaired.split("\n")

    assert "- first item" in lines
    assert "- second item" in lines
    assert "- third item" in lines


def test_numbered_list_items_are_protected() -> None:
    text = "1. one\n2. two\n3. three"

    mask = protected_line_mask(text)

    assert mask == [True, True, True]


def test_fenced_code_block_is_preserved_verbatim() -> None:
    text = "Some prose.\n\n```\ndef f():\n    return 1\n```\n\nMore prose that wraps\nonto a line."

    repaired = repair_wrapped_text_preserving_blocks(text)

    assert "```\ndef f():\n    return 1\n```" in repaired
    assert "More prose that wraps onto a line." in repaired


def test_block_math_is_preserved_verbatim() -> None:
    text = "Consider the equation below.\n\n$$\nx = y + z\n$$\n\nAnd so it follows."

    repaired = repair_wrapped_text_preserving_blocks(text)

    assert "$$\nx = y + z\n$$" in repaired


def test_prose_paragraph_hyphenation_and_wrapping_still_repaired() -> None:
    text = "This is a wrapped sen-\ntence that continues\nacross several lines."

    repaired = repair_wrapped_text_preserving_blocks(text)

    assert repaired == "This is a wrapped sentence that continues across several lines."


def test_table_immediately_followed_by_prose_without_blank_line() -> None:
    text = "| a | b |\n| c | d |\nThis sentence directly\nfollows the table."

    repaired = repair_wrapped_text_preserving_blocks(text)
    lines = repaired.split("\n")

    assert "| a | b |" in lines
    assert "| c | d |" in lines
    assert "This sentence directly follows the table." in lines


def test_plain_prose_with_no_protected_blocks_matches_existing_behavior() -> None:
    text = "Paragraph one continues\nacross two lines.\n\nParagraph two is separate."

    repaired = repair_wrapped_text_preserving_blocks(text)

    assert repaired == "Paragraph one continues across two lines.\n\nParagraph two is separate."
