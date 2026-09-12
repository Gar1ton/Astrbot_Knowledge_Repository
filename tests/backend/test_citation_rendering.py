"""pipelines 层 `[n]` → Harvard 改写的契约测试（纯函数，无 I/O）。"""
from __future__ import annotations

from typing import Any

from kacore.pipelines.citation_rendering import (
    build_citation_refs,
    build_reference_list,
    render_answer_with_references,
    rewrite_citations,
    strip_llm_reference_section,
)


def _source(n: int, **kwargs: Any) -> dict[str, Any]:
    src: dict[str, Any] = {
        "n": n,
        "doc_id": f"d{n}",
        "title": f"Title {n}",
        "creators": [],
        "year": "",
        "pages": [],
    }
    src.update(kwargs)
    return src


_A = _source(1, doc_id="da", title="Paper A", creators=["Aoki, Ann"], year="2020", pages=[3])
_B = _source(2, doc_id="db", title="Paper B", creators=["Bell, Bob"], year="2021", pages=[7])


def _refs(*sources: dict[str, Any]) -> dict[int, Any]:
    return build_citation_refs(list(sources))


# ── build_citation_refs ───────────────────────────────────────


def test_build_citation_refs_maps_by_n_and_reads_metadata() -> None:
    refs = _refs(_A, _B)
    assert set(refs) == {1, 2}
    assert refs[1].doc_id == "da"
    assert refs[1].surnames == ("Aoki",)
    assert refs[1].pages == (3,)


def test_build_citation_refs_falls_back_to_page_number_in_metadata() -> None:
    src = _source(1, pages=[], metadata={"page_number": 12})
    assert build_citation_refs([src])[1].pages == (12,)


def test_build_citation_refs_skips_invalid_n() -> None:
    assert build_citation_refs([_source(0), {"doc_id": "x"}, _source(-1)]) == {}


def test_build_citation_refs_normalizes_filename_style_title_and_fills_missing_biblio() -> None:
    source = _source(1, title="Hui (2021) - Art and Cosmotechnics.pdf")

    ref = build_citation_refs([source])[1]

    assert ref.title == "Art and Cosmotechnics"
    assert ref.surnames == ("Hui",)
    assert ref.year == "2021"


def test_filename_biblio_never_overrides_authoritative_creator_or_year() -> None:
    source = _source(
        1,
        title="FilenameAuthor (1999) - Clean title.pdf",
        creators=["Aoki, Ann"],
        year="2020",
    )

    ref = build_citation_refs([source])[1]

    assert ref.title == "Clean title"
    assert ref.surnames == ("Aoki",)
    assert ref.year == "2020"


# ── 基本改写 ──────────────────────────────────────────────────


def test_rewrite_replaces_marker_with_harvard_in_text_including_page() -> None:
    out = rewrite_citations("自注意力机制 [1] 被提出。", _refs(_A))
    assert out == "自注意力机制 (Aoki, 2020, p. 3) 被提出。"


def test_rewrite_degrades_to_anon_no_date_for_bare_local_document() -> None:
    out = rewrite_citations("结论 [1]。", _refs(_source(1)))
    assert out == "结论 (Anon., n.d.)。"


def test_rewrite_is_noop_without_refs() -> None:
    assert rewrite_citations("答案 [1]", {}) == "答案 [1]"
    assert rewrite_citations("", _refs(_A)) == ""


# ── 分组合并 ──────────────────────────────────────────────────


def test_rewrite_merges_adjacent_markers_into_one_paren_group() -> None:
    refs = _refs(_A, _B)
    assert rewrite_citations("X [1][2]。", refs) == "X (Aoki, 2020, p. 3; Bell, 2021, p. 7)。"
    assert rewrite_citations("X [1] [2]。", refs) == "X (Aoki, 2020, p. 3; Bell, 2021, p. 7)。"
    assert rewrite_citations("X [1]、[2]。", refs) == "X (Aoki, 2020, p. 3; Bell, 2021, p. 7)。"


def test_rewrite_handles_comma_form_including_fullwidth() -> None:
    refs = _refs(_A, _B)
    expected = "X (Aoki, 2020, p. 3; Bell, 2021, p. 7)。"
    assert rewrite_citations("X [1,2]。", refs) == expected
    assert rewrite_citations("X [1，2]。", refs) == expected
    assert rewrite_citations("X [1, 2]。", refs) == expected


def test_rewrite_dedupes_same_doc_same_pages_within_group() -> None:
    dup = _source(3, doc_id="da", title="Paper A", creators=["Aoki, Ann"], year="2020", pages=[3])
    out = rewrite_citations("X [1][3]。", _refs(_A, dup))
    assert out == "X (Aoki, 2020, p. 3)。"


def test_rewrite_does_not_merge_across_sentence_text() -> None:
    refs = _refs(_A, _B)
    out = rewrite_citations("先 [1] 然后 [2]。", refs)
    assert out == "先 (Aoki, 2020, p. 3) 然后 (Bell, 2021, p. 7)。"


# ── 越界编号 ──────────────────────────────────────────────────


def test_rewrite_keeps_out_of_range_marker_verbatim() -> None:
    # 绝不把幻觉编号渲染成 (Anon., n.d.)——那是凭空捏造一条引用。
    refs = _refs(_A)
    assert rewrite_citations("X [9]。", refs) == "X [9]。"
    assert rewrite_citations("X [0]。", refs) == "X [0]。"
    assert rewrite_citations("X [123]。", refs) == "X [123]。"


def test_rewrite_mixed_group_renders_valid_and_keeps_invalid() -> None:
    out = rewrite_citations("X [1][9]。", _refs(_A))
    assert out == "X (Aoki, 2020, p. 3) [9]。"


def test_rewrite_ignores_bare_year_in_brackets() -> None:
    assert rewrite_citations("发表于 [2024] 年。", _refs(_A)) == "发表于 [2024] 年。"


# ── 保护区 ────────────────────────────────────────────────────


def test_rewrite_skips_fenced_code_block() -> None:
    text = "见下：\n```python\narr = x[1]\n```\n结论 [1]。"
    out = rewrite_citations(text, _refs(_A))
    assert "arr = x[1]" in out
    assert out.endswith("结论 (Aoki, 2020, p. 3)。")


def test_rewrite_skips_inline_code() -> None:
    out = rewrite_citations("调用 `arr[1]` 即可 [1]。", _refs(_A))
    assert out == "调用 `arr[1]` 即可 (Aoki, 2020, p. 3)。"


def test_rewrite_skips_markdown_links_and_images() -> None:
    refs = _refs(_A)
    assert rewrite_citations("见 [1](http://e.com)", refs) == "见 [1](http://e.com)"
    assert rewrite_citations("![1](i.png) 与 [1]", refs) == "![1](i.png) 与 (Aoki, 2020, p. 3)"


def test_rewrite_skips_reference_link_definitions() -> None:
    text = "正文 [1]。\n\n[1]: https://example.com"
    out = rewrite_citations(text, _refs(_A))
    assert out.endswith("[1]: https://example.com")
    assert "(Aoki, 2020, p. 3)" in out


def test_rewrite_skips_escaped_markers() -> None:
    assert rewrite_citations(r"字面量 \[1\] 保留。", _refs(_A)) == r"字面量 \[1\] 保留。"


# ── LLM 自写参考文献尾块 ──────────────────────────────────────


def test_strip_llm_reference_section_removes_bibliographic_tail() -> None:
    text = "正文 [1]。\n\n参考文献\n\n- [1] Paper A\n- [2] Paper B"
    body, skip_from = strip_llm_reference_section(text)
    assert body == "正文 [1]。"
    assert skip_from == -1


def test_strip_llm_reference_section_keeps_prose_section() -> None:
    text = "正文。\n\n参考资料\n\n这一节讲的是如何查阅原始资料，属于正文内容。"
    body, skip_from = strip_llm_reference_section(text)
    assert body == text
    assert skip_from >= 0


def test_rewrite_does_not_produce_two_bibliographies() -> None:
    text = "正文 [1]。\n\nReferences\n\n1. [1] Paper A"
    out = rewrite_citations(text, _refs(_A))
    assert "References" not in out
    assert out == "正文 (Aoki, 2020, p. 3)。"


# ── 参考文献表 ────────────────────────────────────────────────


def test_build_reference_list_dedupes_by_document_and_sorts() -> None:
    a2 = _source(3, doc_id="da", title="Paper A", creators=["Aoki, Ann"], year="2020", pages=[9])
    refs = _refs(_B, _A, a2)
    assert build_reference_list(refs.values()) == [
        "Aoki, A. (2020) Paper A.",
        "Bell, B. (2021) Paper B.",
    ]


def test_build_reference_list_is_stable_across_calls() -> None:
    refs = _refs(_A, _B)
    assert build_reference_list(refs.values()) == build_reference_list(refs.values())


def test_same_document_two_pages_yields_two_in_text_but_one_reference() -> None:
    a2 = _source(2, doc_id="da", title="Paper A", creators=["Aoki, Ann"], year="2020", pages=[7])
    sources = [dict(_A), a2]
    body, references = render_answer_with_references("X [1] 与 Y [2]。", sources)
    assert "(Aoki, 2020, p. 3)" in body
    assert "(Aoki, 2020, p. 7)" in body
    assert references == ["Aoki, A. (2020) Paper A."]


# ── render_answer_with_references ─────────────────────────────


def test_render_appends_reference_block_and_mutates_sources_in_place() -> None:
    sources = [dict(_A), dict(_B)]
    body, references = render_answer_with_references("结论 [1] 与 [2]。", sources)
    assert body == (
        "结论 (Aoki, 2020, p. 3) 与 (Bell, 2021, p. 7)。\n\n"
        "**参考文献**\n\n"
        "- Aoki, A. (2020) Paper A.\n"
        "- Bell, B. (2021) Paper B."
    )
    assert references == ["Aoki, A. (2020) Paper A.", "Bell, B. (2021) Paper B."]
    # 就地写回是刻意副作用：chat_history 与前端必须拿到同一批串才能还原点击态。
    assert sources[0]["harvard_in_text"] == "Aoki, 2020, p. 3"
    assert sources[0]["harvard_reference"] == "Aoki, A. (2020) Paper A."
    assert sources[1]["harvard_in_text"] == "Bell, 2021, p. 7"


def test_render_reference_list_does_not_repeat_filename_author_year_or_extension() -> None:
    source = _source(1, title="Hui (2021) - Art and Cosmotechnics.pdf")

    body, references = render_answer_with_references("结论 [1]。", [source])

    assert body == (
        "结论 (Hui, 2021)。\n\n"
        "**参考文献**\n\n"
        "- Hui (2021) Art and Cosmotechnics."
    )
    assert references == ["Hui (2021) Art and Cosmotechnics."]
    assert source["harvard_in_text"] == "Hui, 2021"


def test_render_with_empty_sources_returns_answer_unchanged() -> None:
    body, references = render_answer_with_references("答案 [1]", [])
    assert body == "答案 [1]"
    assert references == []


def test_render_still_annotates_sources_when_answer_is_empty() -> None:
    sources = [dict(_A)]
    body, references = render_answer_with_references("", sources)
    assert body == ""
    assert references == []
    assert sources[0]["harvard_in_text"] == "Aoki, 2020, p. 3"


def test_render_uses_custom_heading() -> None:
    body, _ = render_answer_with_references("X [1]", [dict(_A)], heading="References")
    assert "**References**" in body
