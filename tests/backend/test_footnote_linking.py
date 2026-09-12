"""脚注候选检测与关联的纯函数测试（无 I/O）。

覆盖验收矩阵 C01/C03/C05 相关场景：正文与脚注分离、脚注可独立读取、同标号跨页不串线、
只有脚注的页面正确处理、低置信关联保留原文不臆造。
"""
from __future__ import annotations

from kacore.domain.footnotes import FootnoteBlock, FootnoteLinkStatus
from kacore.managers.footnote_linking import (
    extract_footnote_candidates,
    link_footnotes,
    separate_footnotes,
)


def test_single_footnote_extracted_and_linked() -> None:
    page_text = (
        "This is the introduction paragraph that references a claim14 made earlier.\n"
        "\n"
        "14 This is the footnote text explaining the claim in detail."
    )

    body, footnotes = separate_footnotes(page_text, page=5)

    assert body == "This is the introduction paragraph that references a claim14 made earlier."
    assert len(footnotes) == 1
    fn = footnotes[0]
    assert fn.marker == "14"
    assert fn.page == 5
    assert fn.text == "This is the footnote text explaining the claim in detail."
    assert fn.link_status == FootnoteLinkStatus.LINKED
    assert fn.body_marker_span is not None
    start, end = fn.body_marker_span
    assert body[start:end] == "14"


def test_source_span_matches_original_text() -> None:
    page_text = "Body sentence here.\n\n7 Footnote body text."
    _, footnotes = extract_footnote_candidates(page_text, page=1)

    assert len(footnotes) == 1
    fn = footnotes[0]
    assert page_text[fn.source_start : fn.source_end] == "7 Footnote body text."


def test_multiple_footnotes_on_same_page_split_correctly() -> None:
    page_text = (
        "Body text referencing claim12 and another point13.\n"
        "\n"
        "12 First footnote text.\n"
        "13 Second footnote text."
    )

    body, footnotes = separate_footnotes(page_text, page=2)

    assert body == "Body text referencing claim12 and another point13."
    assert [fn.marker for fn in footnotes] == ["12", "13"]
    assert footnotes[0].text == "First footnote text."
    assert footnotes[1].text == "Second footnote text."
    assert all(fn.link_status == FootnoteLinkStatus.LINKED for fn in footnotes)


def test_footnote_continuation_line_is_preserved() -> None:
    page_text = (
        "Body text with a reference9 to something.\n"
        "\n"
        "9 This footnote text is long enough\n"
        "to wrap onto a second physical line."
    )

    body, footnotes = separate_footnotes(page_text, page=1)

    assert len(footnotes) == 1
    assert "wrap onto a second physical line" in footnotes[0].text


def test_unmatched_footnote_marker_is_unlinked_but_preserved() -> None:
    page_text = "Body text with no digit reference at all.\n\n3 Orphaned footnote text."

    body, footnotes = separate_footnotes(page_text, page=1)

    assert len(footnotes) == 1
    fn = footnotes[0]
    assert fn.link_status == FootnoteLinkStatus.UNLINKED
    assert fn.body_marker_span is None
    assert fn.text == "Orphaned footnote text."  # 未关联也不删除脚注原文


def test_ambiguous_marker_hits_multiple_body_positions() -> None:
    body_text = "First claim5 and second claim5 both need support."
    footnotes = [
        FootnoteBlock(page=1, marker="5", text="Shared footnote.", source_start=0, source_end=0)
    ]

    linked = link_footnotes(body_text, footnotes)

    assert linked[0].link_status == FootnoteLinkStatus.AMBIGUOUS
    assert linked[0].body_marker_span is None
    assert linked[0].text == "Shared footnote."


def test_same_marker_on_different_pages_does_not_cross_link() -> None:
    """C03：不同章节都含脚注 14，只关联本页正确注释，不跨页/跨章串线。"""
    page_a_text = "Chapter one discusses topic14 in depth.\n\n14 Chapter one's own footnote."
    page_b_text = "Chapter two revisits topic14 differently.\n\n14 Chapter two's own footnote."

    body_a, footnotes_a = separate_footnotes(page_a_text, page=10)
    body_b, footnotes_b = separate_footnotes(page_b_text, page=55)

    assert footnotes_a[0].text == "Chapter one's own footnote."
    assert footnotes_b[0].text == "Chapter two's own footnote."
    assert footnotes_a[0].link_status == FootnoteLinkStatus.LINKED
    assert footnotes_b[0].link_status == FootnoteLinkStatus.LINKED
    # 关联点分别落在各自页面的正文内，互不影响。
    a_start, a_end = footnotes_a[0].body_marker_span
    b_start, b_end = footnotes_b[0].body_marker_span
    assert body_a[a_start:a_end] == "14"
    assert body_b[b_start:b_end] == "14"


def test_page_with_only_footnotes_has_empty_body() -> None:
    """C05：只有脚注的页面，正文可为空，脚注仍完整保留。"""
    page_text = "1 First footnote on a footnote-only page.\n2 Second footnote, no body above."

    body, footnotes = separate_footnotes(page_text, page=42)

    assert body == ""
    assert len(footnotes) == 2
    assert footnotes[0].marker == "1"
    assert footnotes[1].marker == "2"


def test_ordinary_paragraph_starting_with_year_is_not_misclassified() -> None:
    page_text = "1997 was a landmark year for the discipline, changing how scholars approached it."

    body, footnotes = extract_footnote_candidates(page_text, page=1)

    assert footnotes == []
    assert body == page_text


def test_numbered_heading_mid_page_is_not_treated_as_footnote() -> None:
    lines = [f"Paragraph line number {i} of ordinary body text." for i in range(20)]
    lines.insert(5, "")
    lines.insert(6, "1. Introduction")
    page_text = "\n".join(lines)

    body, footnotes = extract_footnote_candidates(page_text, page=1)

    assert footnotes == []
    assert body == page_text


def test_no_footnote_present_returns_original_text_unchanged() -> None:
    page_text = "Just an ordinary paragraph with no footnote markers whatsoever."

    body, footnotes = extract_footnote_candidates(page_text, page=1)

    assert body == page_text
    assert footnotes == []
