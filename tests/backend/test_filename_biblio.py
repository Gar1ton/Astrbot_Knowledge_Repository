"""domain 层文件名书目解析的契约测试（纯函数，无 I/O）。"""
from __future__ import annotations

import pytest

from kacore.domain.filename_biblio import FilenameBiblio, parse_filename_biblio


@pytest.mark.parametrize(
    ("filename", "authors", "year", "title"),
    [
        # 主格式：Author(s) (Year) - Title
        (
            "Peng, Hou, Zhou and Shang (2026) - Codified Finite-State Machines for "
            "Role-Playing.pdf",
            ("Peng", "Hou", "Zhou", "Shang"),
            "2026",
            "Codified Finite-State Machines for Role-Playing",
        ),
        (
            "DeYoung (2015) - Cybernetic Big Five Theory.pdf",
            ("DeYoung",),
            "2015",
            "Cybernetic Big Five Theory",
        ),
        ("Marx (1894) - Capital Volume III.pdf", ("Marx",), "1894", "Capital Volume III"),
        # & 连接的多作者
        (
            "Marx & Engels (1845-1846) - German Ideology.pdf",
            ("Marx", "Engels"),
            "1845",  # 年份区间取首年
            "German Ideology",
        ),
        # 变体格式：Author(s) - Year - Title（et al. 应被截断，只保留已列出的姓氏）
        (
            "Pink et al. - 2016 - Digital ethnography principles and practice.pdf",
            ("Pink",),
            "2016",
            "Digital ethnography principles and practice",
        ),
        (
            "Altheide - 1994 - An Ecology of Communication.pdf",
            ("Altheide",),
            "1994",
            "An Ecology of Communication",
        ),
        # 字面 n.d.（括号与连字符两种变体，大小写/加点不敏感）
        (
            "Jordan (n.d.) - Researching the digital economy.pdf",
            ("Jordan",),
            "",
            "Researching the digital economy",
        ),
        ("Smith - N.D. - Untitled Manuscript.pdf", ("Smith",), "", "Untitled Manuscript"),
        # Zotero 去重数字前缀
        (
            "16_Laozi Ch.37 (n.d.) - 老子. 道德经 第三十七章.pdf",
            ("Laozi Ch.37",),
            "",
            "老子. 道德经 第三十七章",
        ),
        # 中文标题 + 逗号分隔多作者
        (
            "Marx, Engels (1845) - 马克思，恩格斯. 德意志意识形态.pdf",
            ("Marx", "Engels"),
            "1845",
            "马克思，恩格斯. 德意志意识形态",
        ),
    ],
)
def test_parses_recognized_filename_patterns(
    filename: str, authors: tuple[str, ...], year: str, title: str
) -> None:
    result = parse_filename_biblio(filename)
    assert result == FilenameBiblio(authors=authors, year=year, title=title)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "just-a-random-filename.pdf",
        "NoYearNoDash.pdf",
        "2024 Annual Report.pdf",  # 裸年份、无作者/标题分段
        "(2020) - Missing Authors.pdf",  # 作者段为空
        "Author (2020) - .pdf",  # 标题段为空
    ],
)
def test_returns_none_when_pattern_is_not_confidently_recognized(filename: str) -> None:
    assert parse_filename_biblio(filename) is None
