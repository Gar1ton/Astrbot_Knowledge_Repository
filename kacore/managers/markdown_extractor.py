"""PDF → 干净 Markdown 清洗内核（managers 层，pinned PyMuPDF4LLM）。

为什么存在：替代旧的 fitz `page.get_text` 手写抽取。PyMuPDF4LLM 产出结构更干净的 Markdown，
更利于下游分块与图谱实体边界。本模块把「PDF → clean.md + 页面字符偏移」收口为一处，保证：

  - clean.md **无可见页码/页分隔符**（page_separators=False），页码只进 pages.json/DB。
  - 偏移不变量（见 PageSpan 契约）：pages.json 的字符偏移是**写盘归一化（统一 LF）后**
    clean.md 的 Python str 偏移，可被下游 chunker 直接切片，杜绝 CRLF/局部偏移回推错误。

依赖方向：仅依赖 stdlib + pinned `pymupdf4llm`（懒加载，缺失时抛带安装指引的错误）。
版本治理：PYMUPDF4LLM_PINNED_VERSION 与 requirements.txt 对齐；升级只改 pin。
"""
from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass, field
from typing import Any

# 与 requirements.txt 的 `pymupdf4llm>=0.0.17,<0.1.0` 对齐的内置参考版本。
# 不 vendor 源码（规避 AGPL 分发义务），仅记录所依赖的精确版本号。
PYMUPDF4LLM_PINNED_VERSION = "0.0.27"

CONVERTER_NAME = "pymupdf4llm"

# 页间拼接符：clean.md 中相邻页之间插入一个空行（属于「页区间」，保证字符全覆盖）。
_PAGE_JOINER = "\n\n"
_MIN_REPEATED_HEADER_PAGES = 3
_MARGINAL_LINE_WINDOW = 4
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_BLANK_PARAGRAPH_RE = re.compile(r"\n[ \t]*\n+")
_FALSE_PARAGRAPH_BREAK_RE = re.compile(
    r"(?P<left>[^\s。？！.!?:;])\n\n(?P<right>(?:[\"'“‘(\[])?[a-z])"
)
_CONTINUATION_START_RE = re.compile(r"^(?:[\"'“‘(\[])?[a-z]")


@dataclass
class PageSpan:
    """clean.md 中某一页的字符区间（左闭右开，连续覆盖含页间拼接符）。

    契约：start/end 是写盘归一化（LF）后 clean.md 的 Python str 字符偏移；
    相邻页 end_i == start_{i+1}（连续半开区间），故任一字符都能映射回某一页。
    """

    page: int
    start: int
    end: int


@dataclass
class MarkdownArtifact:
    """一次 PDF 清洗的产物：干净 Markdown + 页面偏移 + PDF 文档级元数据。"""

    clean_markdown: str
    page_spans: list[PageSpan]
    pdf_metadata: dict[str, Any] = field(default_factory=dict)
    converter: str = CONVERTER_NAME
    converter_version: str = PYMUPDF4LLM_PINNED_VERSION


def installed_pymupdf4llm_version() -> str:
    """返回实际安装的 pymupdf4llm 版本；查不到时回退内置 pin。"""
    try:
        return importlib.metadata.version("pymupdf4llm")
    except Exception:
        return PYMUPDF4LLM_PINNED_VERSION


def _normalize_newlines(text: str) -> str:
    """统一换行为 LF（CRLF/CR → LF），保证字符偏移稳定可复现。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_marginal_line(line: str) -> str:
    """把候选页眉页脚行归一化，供跨页重复检测。"""
    line = re.sub(r"[*_`#>\[\](){}]", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line.upper()


def _marginal_line_indices(lines: list[str]) -> set[int]:
    nonempty = [idx for idx, line in enumerate(lines) if line.strip()]
    return set(nonempty[:_MARGINAL_LINE_WINDOW] + nonempty[-_MARGINAL_LINE_WINDOW:])


def _detect_repeated_marginal_headers(page_texts: list[str]) -> set[str]:
    """识别跨页重复的边缘文本（典型页眉 / 页脚），仅用于删除 marginal 行。"""
    counts: dict[str, set[int]] = {}
    for page_idx, text in enumerate(page_texts):
        lines = text.split("\n")
        for line_idx in _marginal_line_indices(lines):
            raw = lines[line_idx].strip()
            if not raw or _PAGE_NUMBER_RE.match(raw):
                continue
            normalized = _normalize_marginal_line(raw)
            if len(normalized) < 8:
                continue
            counts.setdefault(normalized, set()).add(page_idx)

    if len(page_texts) < _MIN_REPEATED_HEADER_PAGES:
        return set()
    min_pages = max(_MIN_REPEATED_HEADER_PAGES, int(len(page_texts) * 0.15))
    return {line for line, pages in counts.items() if len(pages) >= min_pages}


def _remove_marginal_noise(text: str, repeated_headers: set[str]) -> str:
    lines = text.split("\n")
    marginal_indices = _marginal_line_indices(lines)
    cleaned: list[str] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx in marginal_indices and _PAGE_NUMBER_RE.match(stripped):
            continue
        if idx in marginal_indices and _normalize_marginal_line(stripped) in repeated_headers:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _repair_wrapped_text(text: str) -> str:
    """修复 PDF 抽取常见的行内断词与单换行换行符。"""
    # ASCII hyphen at EOL is usually layout hyphenation: opera-\ntions -> operations.
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    # ASCII hyphen + soft hyphen means the hyphen itself is semantic: co-­\nmotional -> co-motional.
    text = re.sub(r"(?<=\w)-\u00ad\n(?=\w)", "-", text)
    text = re.sub(r"(?<=\w)\u00ad\n(?=\w)", "", text)
    # 单换行多来自版面换行；空行仍作为段落边界。
    paragraphs = re.split(r"(\n[ \t]*\n+)", text)
    repaired: list[str] = []
    for part in paragraphs:
        if not part:
            continue
        if _BLANK_PARAGRAPH_RE.fullmatch(part):
            repaired.append("\n\n")
            continue
        lines = [line.strip() for line in part.split("\n")]
        joined = " ".join(line for line in lines if line)
        joined = re.sub(r"[ \t]+", " ", joined).strip()
        if joined:
            repaired.append(joined)
    text = "".join(repaired)
    previous = None
    while previous != text:
        previous = text
        text = _FALSE_PARAGRAPH_BREAK_RE.sub(r"\g<left> \g<right>", text)
    return text


def post_clean_markdown_pages(page_texts: list[str]) -> list[str]:
    """对逐页 Markdown 做确定性清洗，返回仍按页对齐的 clean text 列表。"""
    normalized = [_normalize_newlines(text).strip("\n") for text in page_texts]
    repeated_headers = _detect_repeated_marginal_headers(normalized)
    cleaned = []
    for text in normalized:
        text = _remove_marginal_noise(text, repeated_headers)
        text = _repair_wrapped_text(text)
        cleaned.append(text.strip("\n"))
    return cleaned


def _page_joiner(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if (
        left
        and right
        and left[-1] not in "。？！.!?:;"
        and _CONTINUATION_START_RE.match(right)
    ):
        return " "
    return _PAGE_JOINER


def join_cleaned_markdown_pages(
    page_texts: list[str], page_numbers: list[int] | None = None
) -> tuple[str, list[PageSpan]]:
    """拼接已清洗页面，并在跨页续句时避免插入伪段落空行。"""
    page_numbers = page_numbers or list(range(1, len(page_texts) + 1))
    parts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    total = len(page_texts)

    for idx, text in enumerate(page_texts):
        start = cursor
        parts.append(text)
        cursor += len(text)
        if idx < total - 1:
            joiner = _page_joiner(text, page_texts[idx + 1])
            parts.append(joiner)
            cursor += len(joiner)
        spans.append(PageSpan(page=page_numbers[idx], start=start, end=cursor))

    return "".join(parts), spans


def extract_pdf_markdown(pdf_path: str) -> MarkdownArtifact:
    """把 PDF 转为干净 Markdown 并记录每页字符区间。

    用 `page_chunks=True` 拿到逐页 Markdown，按确定规则（去首尾空行 + 单空行拼接）拼装成 clean.md，
    同时记录每页 [start,end) 连续区间。失败/缺依赖抛带指引的 RuntimeError。
    """
    try:
        import pymupdf4llm
    except ImportError as exc:  # 缺 pinned 依赖：给出安装指引（沿用可选依赖懒加载范式）。
        raise RuntimeError(
            "PDF 清洗需要 PyMuPDF4LLM，请安装："
            "pip install 'pymupdf4llm>=0.0.17,<0.1.0' 'PyMuPDF>=1.24,<2.0'"
        ) from exc

    page_dicts = pymupdf4llm.to_markdown(
        str(pdf_path),
        page_chunks=True,
        page_separators=False,
        ignore_alpha=True,
    )

    pdf_metadata: dict[str, Any] = {}
    page_numbers: list[int] = []
    raw_page_texts: list[str] = []

    for idx, page in enumerate(page_dicts):
        meta = page.get("metadata", {}) if isinstance(page, dict) else {}
        if idx == 0 and isinstance(meta, dict):
            # 取首页携带的 PDF 文档级元数据（title/author/page_count 等），剔除逐页字段。
            pdf_metadata = {
                k: v for k, v in meta.items() if k not in ("page", "file_path")
            }
        page_no = int(meta.get("page", idx + 1)) if isinstance(meta, dict) else idx + 1
        raw_text = page.get("text", "") if isinstance(page, dict) else ""
        page_numbers.append(page_no)
        raw_page_texts.append(raw_text)

    clean_markdown, spans = join_cleaned_markdown_pages(
        post_clean_markdown_pages(raw_page_texts),
        page_numbers,
    )
    return MarkdownArtifact(
        clean_markdown=clean_markdown,
        page_spans=spans,
        pdf_metadata=pdf_metadata,
        converter=CONVERTER_NAME,
        converter_version=installed_pymupdf4llm_version(),
    )


def build_single_page_artifact(text: str) -> MarkdownArtifact:
    """把纯文本（txt/md 上传）包装为单页制品：clean.md 即原文，整篇视作第 1 页。

    txt/md 无 PDF 结构，直接作为 clean.md（仅归一化换行），便于与 PDF 路径统一下游处理。
    """
    clean = _normalize_newlines(text)
    return MarkdownArtifact(
        clean_markdown=clean,
        page_spans=[PageSpan(page=1, start=0, end=len(clean))],
        pdf_metadata={},
        converter="plaintext",
        converter_version="",
    )


__all__ = [
    "PYMUPDF4LLM_PINNED_VERSION",
    "CONVERTER_NAME",
    "PageSpan",
    "MarkdownArtifact",
    "installed_pymupdf4llm_version",
    "post_clean_markdown_pages",
    "join_cleaned_markdown_pages",
    "extract_pdf_markdown",
    "build_single_page_artifact",
]
