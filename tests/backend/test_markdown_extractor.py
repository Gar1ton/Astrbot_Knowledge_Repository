"""`extract_pdf_markdown()` 生产入口的集成测试（真实 PyMuPDF4LLM，非合成字符串直调）。

覆盖点：确认 `clean_page_structure`（脚注分离 + 结构保护，见 `artifact_cleaning.py`）
真的被生产抽取路径调用，而不只是底层纯函数各自在 `test_footnote_linking.py`/
`test_structural_protection.py` 里被单独测试过——此前这条线完全没有覆盖任何
`extract_pdf_markdown()` 本身的集成测试。
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import fitz  # PyMuPDF（仅用于动态生成测试 PDF）
import pytest

from kacore.managers.markdown_extractor import extract_pdf_markdown

_pdf_extract_available = importlib.util.find_spec("pymupdf4llm") is not None
pytestmark = pytest.mark.skipif(
    not _pdf_extract_available, reason="pymupdf4llm not installed"
)


def _make_pdf(tmp_path: Path, text: str) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 750), text)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_extract_pdf_markdown_separates_credible_footnote(tmp_path: Path) -> None:
    """有出处依据（正文引用点 + 页尾书目特征）的脚注必须被分离出正文，进入 footnotes。"""
    pdf_path = _make_pdf(
        tmp_path,
        "The argument proceeds from a well-established premise14 that requires no "
        "further defense.\n\n"
        "It continues across several synthetic sentences describing the same claim "
        "in more depth.\n\n"
        "14 See University Press, 1998, pp. 12-14.",
    )

    before = hashlib.sha256(pdf_path.read_bytes()).digest()
    artifact = extract_pdf_markdown(str(pdf_path))
    assert hashlib.sha256(pdf_path.read_bytes()).digest() == before

    assert len(artifact.footnotes) == 1
    note = artifact.footnotes[0]
    assert note.marker == "14"
    assert "University Press" in note.text
    # 脚注正文被移出正文视图，但原始逐页文本仍完整保留（供全文/脚注读取回溯）。
    assert "University Press" not in artifact.clean_markdown
    assert "premise14" in artifact.clean_markdown
    assert len(artifact.raw_pages) == len(artifact.page_spans)
    assert "University Press" in artifact.raw_pages[0]


def test_extract_pdf_markdown_keeps_ordinary_numbered_text_intact(tmp_path: Path) -> None:
    """没有引用点/书目特征支持的编号行（如普通编号段落）不得被误判为脚注吞掉。"""
    pdf_path = _make_pdf(
        tmp_path,
        "Synthetic introduction paragraph with ordinary prose and no footnote markers.\n\n"
        "1 First item in a plain enumerated list.\n"
        "2 Second item continues the same list.\n"
        "3 Third item closes out the list.",
    )

    before = hashlib.sha256(pdf_path.read_bytes()).digest()
    artifact = extract_pdf_markdown(str(pdf_path))
    assert hashlib.sha256(pdf_path.read_bytes()).digest() == before

    assert artifact.footnotes == []
    assert "Third item closes out the list" in artifact.clean_markdown


def test_extract_pdf_markdown_removes_jstor_access_stamp_and_repairs_seam(
    tmp_path: Path,
) -> None:
    """访问戳即使落在文本流中间也应删除，前后续句不能被切成两个假段落。"""
    stamp = "This content downloaded from 131.111.98.148 on Fri, 11 Sep 2026 03:07:28 UTC"
    pdf_path = _make_pdf(
        tmp_path,
        "The planetary argument is\n" + stamp + "\ncontinued by this clause.\n"
        "All use subject to https://about.jstor.org/terms",
    )

    artifact = extract_pdf_markdown(str(pdf_path))

    assert "This content downloaded" not in artifact.clean_markdown
    assert "All use subject to" not in artifact.clean_markdown
    assert "The planetary argument is continued by this clause." in artifact.clean_markdown


def test_marginal_numeric_noise_does_not_delete_formula_or_code():
    from kacore.managers.markdown_extractor import _remove_marginal_noise

    text = "Prose.\n\n$$\n123\n$$\n\n```\n456\n```\n7"
    cleaned = _remove_marginal_noise(text, set())
    assert "123" in cleaned and "456" in cleaned
    assert not cleaned.endswith("7")
