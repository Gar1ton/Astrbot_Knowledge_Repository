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
from dataclasses import dataclass, field
from typing import Any

# 与 requirements.txt 的 `pymupdf4llm>=0.0.17,<0.1.0` 对齐的内置参考版本。
# 不 vendor 源码（规避 AGPL 分发义务），仅记录所依赖的精确版本号。
PYMUPDF4LLM_PINNED_VERSION = "0.0.27"

CONVERTER_NAME = "pymupdf4llm"

# 页间拼接符：clean.md 中相邻页之间插入一个空行（属于「页区间」，保证字符全覆盖）。
_PAGE_JOINER = "\n\n"


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
    )

    parts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    pdf_metadata: dict[str, Any] = {}
    total = len(page_dicts)

    for idx, page in enumerate(page_dicts):
        meta = page.get("metadata", {}) if isinstance(page, dict) else {}
        if idx == 0 and isinstance(meta, dict):
            # 取首页携带的 PDF 文档级元数据（title/author/page_count 等），剔除逐页字段。
            pdf_metadata = {
                k: v for k, v in meta.items() if k not in ("page", "file_path")
            }
        page_no = int(meta.get("page", idx + 1)) if isinstance(meta, dict) else idx + 1

        raw_text = page.get("text", "") if isinstance(page, dict) else ""
        text = _normalize_newlines(raw_text).strip("\n")

        start = cursor
        parts.append(text)
        cursor += len(text)
        # 非末页追加拼接符；区间 end 落在拼接符之后，保证连续覆盖。
        if idx < total - 1:
            parts.append(_PAGE_JOINER)
            cursor += len(_PAGE_JOINER)
        spans.append(PageSpan(page=page_no, start=start, end=cursor))

    clean_markdown = "".join(parts)
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
    "extract_pdf_markdown",
    "build_single_page_artifact",
]
