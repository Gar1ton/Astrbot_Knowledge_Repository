"""domain 层 Harvard 引用格式化的契约测试（纯函数，无 I/O）。"""
from __future__ import annotations

import pytest

from kacore.domain.citation import (
    ANON,
    NO_DATE,
    CitationRef,
    format_pages,
    harvard_in_text,
    harvard_in_text_group,
    harvard_reference,
    normalize_creators,
    reference_sort_key,
)


def _ref(**kwargs: object) -> CitationRef:
    base: dict[str, object] = {"source_n": 1, "doc_id": "d1"}
    base.update(kwargs)
    return CitationRef(**base)  # type: ignore[arg-type]


# ── normalize_creators ────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "surnames", "initials"),
    [
        (["Vaswani, Ashish"], ("Vaswani",), ("A.",)),
        (["Vaswani, Ashish Kumar"], ("Vaswani",), ("A.K.",)),
        (["Doe, Jean-Paul"], ("Doe",), ("J.-P.",)),
        # 机构名/单名：无逗号则整串是姓氏，绝不按空格猜。
        (["OpenAI"], ("OpenAI",), ("",)),
        (["World Health Organization"], ("World Health Organization",), ("",)),
        (["van der Berg, Jan"], ("van der Berg",), ("J.",)),
        # 中文名的 given 无拉丁字母 → 不产出 `张.`。
        (["张, 三"], ("张",), ("",)),
        (["张三"], ("张三",), ("",)),
        # 脏数据。
        ([], (), ()),
        (["", "  "], (), ()),
        ([", Ashish"], (), ()),
        (None, (), ()),
        ([123], ("123",), ("",)),
        ({"a": 1}, (), ()),
        # local_meta 手填的换行拼接字符串。
        ("Vaswani, Ashish\nShazeer, Noam", ("Vaswani", "Shazeer"), ("A.", "N.")),
        ("Vaswani, Ashish; Shazeer, Noam", ("Vaswani", "Shazeer"), ("A.", "N.")),
    ],
)
def test_normalize_creators(raw: object, surnames: tuple, initials: tuple) -> None:
    assert normalize_creators(raw) == (surnames, initials)


def test_normalize_creators_keeps_order_and_pairs_stay_aligned() -> None:
    surnames, initials = normalize_creators(["B, Bob", "OpenAI", "A, Ann"])
    assert surnames == ("B", "OpenAI", "A")
    assert initials == ("B.", "", "A.")
    assert len(surnames) == len(initials)


# ── format_pages ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        ([], ""),
        ([0], ""),
        (["x"], ""),
        ([3], "p. 3"),
        ([3, 4, 5], "pp. 3-5"),
        ([5, 3, 4], "pp. 3-5"),
        ([3, 7], "pp. 3, 7"),
        ([3, 3], "p. 3"),
        (["4", 3], "pp. 3-4"),
    ],
)
def test_format_pages(pages: list, expected: str) -> None:
    assert format_pages(pages) == expected


# ── in-text ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([], ANON),
        (["Vaswani, A"], "Vaswani"),
        (["Vaswani, A", "Shazeer, N"], "Vaswani and Shazeer"),
        (["Vaswani, A", "Shazeer, N", "Parmar, N"], "Vaswani, Shazeer and Parmar"),
        # Cite Them Right：4 位起才 et al.
        (["A, X", "B, X", "C, X", "D, X"], "A et al."),
    ],
)
def test_harvard_in_text_author_forms(names: list[str], expected: str) -> None:
    surnames, initials = normalize_creators(names)
    ref = _ref(surnames=surnames, initials=initials, year="2017")
    assert harvard_in_text(ref) == f"{expected}, 2017"


def test_harvard_in_text_includes_page_from_chunk_metadata() -> None:
    ref = _ref(surnames=("Vaswani",), initials=("A.",), year="2017", pages=(3,))
    assert harvard_in_text(ref) == "Vaswani, 2017, p. 3"
    assert harvard_in_text(ref, with_page=False) == "Vaswani, 2017"


def test_harvard_in_text_degrades_to_anon_and_no_date() -> None:
    assert harvard_in_text(_ref()) == f"{ANON}, {NO_DATE}"
    assert harvard_in_text(_ref(year="2021", pages=(7,))) == f"{ANON}, 2021, p. 7"
    assert harvard_in_text(_ref(surnames=("Li",), initials=("",))) == f"Li, {NO_DATE}"


def test_harvard_in_text_has_no_outer_parentheses() -> None:
    # 前端按内层串做最长匹配还原点击态；带括号会让合并形式无法拆分。
    rendered = harvard_in_text(_ref(surnames=("Li",), initials=("L.",), year="2025"))
    assert not rendered.startswith("(")
    assert not rendered.endswith(")")


def test_harvard_in_text_group_merges_with_semicolons() -> None:
    a = _ref(source_n=1, doc_id="d1", surnames=("A",), initials=("A.",), year="2020", pages=(1,))
    b = _ref(source_n=2, doc_id="d2", surnames=("B",), initials=("B.",), year="2021")
    assert harvard_in_text_group([a, b]) == "(A, 2020, p. 1; B, 2021)"
    assert harvard_in_text_group([a]) == "(A, 2020, p. 1)"
    assert harvard_in_text_group([]) == ""


# ── reference list ────────────────────────────────────────────


def test_harvard_reference_full_form() -> None:
    surnames, initials = normalize_creators(
        ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]
    )
    ref = _ref(
        surnames=surnames,
        initials=initials,
        year="2017",
        title="Attention is all you need",
        venue="NeurIPS",
        doi="10.5555/aaa",
    )
    assert harvard_reference(ref) == (
        "Vaswani, A., Shazeer, N. and Parmar, N. (2017) "
        "'Attention is all you need', NeurIPS. doi: 10.5555/aaa."
    )


def test_harvard_reference_degradation_ladder() -> None:
    base = {"surnames": ("Li",), "initials": ("L.",), "year": "2025", "title": "T"}
    # 有 venue：标题加引号并跟容器名。
    assert harvard_reference(_ref(**base, venue="V", doi="10.1/x")) == (
        "Li, L. (2025) 'T', V. doi: 10.1/x."
    )
    # 无 doi 退 url。
    assert harvard_reference(_ref(**base, venue="V", url="https://e.com")) == (
        "Li, L. (2025) 'T', V. Available at: https://e.com."
    )
    # 无 venue：标题独立成句。
    assert harvard_reference(_ref(**base)) == "Li, L. (2025) T."
    # 纯本地文档：Anon. + n.d.，标题仍完整展示。
    assert harvard_reference(_ref(title="项目会议纪要 2024Q3")) == (
        f"{ANON} ({NO_DATE}) 项目会议纪要 2024Q3."
    )


def test_harvard_reference_lists_all_authors_until_cap() -> None:
    names = [f"S{i:02d}, Given{i}" for i in range(4)]
    surnames, initials = normalize_creators(names)
    rendered = harvard_reference(_ref(surnames=surnames, initials=initials, year="2020"))
    # 正文内 4 位已缩写为 et al.，但参考文献表仍列全。
    assert rendered == "S00, G., S01, G., S02, G. and S03, G. (2020)"
    assert "et al." not in rendered


def test_harvard_reference_uses_et_al_beyond_cap() -> None:
    names = [f"S{i:02d}, Given{i}" for i in range(21)]
    surnames, initials = normalize_creators(names)
    rendered = harvard_reference(_ref(surnames=surnames, initials=initials, year="2020"))
    assert rendered.startswith("S00, G. et al. (2020)")


# ── 排序 ──────────────────────────────────────────────────────


def test_reference_sort_key_orders_anon_alphabetically() -> None:
    anon = _ref(doc_id="d2")
    zulu = _ref(doc_id="d1", surnames=("Zulu",), initials=("Z.",))
    baker = _ref(doc_id="d3", surnames=("Baker",), initials=("B.",))
    ordered = sorted([zulu, anon, baker], key=reference_sort_key)
    assert [r.doc_id for r in ordered] == ["d2", "d3", "d1"]


def test_reference_sort_key_puts_no_date_before_dated_same_author() -> None:
    dated = _ref(doc_id="d1", surnames=("Li",), initials=("L.",), year="2020")
    undated = _ref(doc_id="d2", surnames=("Li",), initials=("L.",))
    assert [r.doc_id for r in sorted([dated, undated], key=reference_sort_key)] == ["d2", "d1"]


def test_reference_sort_key_single_author_precedes_multi_author() -> None:
    solo = _ref(doc_id="d1", surnames=("Li",), initials=("L.",), year="2020")
    duo = _ref(doc_id="d2", surnames=("Li", "Wang"), initials=("L.", "W."), year="2019")
    assert [r.doc_id for r in sorted([duo, solo], key=reference_sort_key)] == ["d1", "d2"]


def test_reference_sort_key_is_deterministic_on_full_ties() -> None:
    # 末位 doc_id 兜底：历史消息两次回放必须得到完全相同的顺序。
    a = _ref(doc_id="zzz", surnames=("Li",), initials=("L.",), year="2020", title="T")
    b = _ref(doc_id="aaa", surnames=("Li",), initials=("L.",), year="2020", title="T")
    assert [r.doc_id for r in sorted([a, b], key=reference_sort_key)] == ["aaa", "zzz"]
