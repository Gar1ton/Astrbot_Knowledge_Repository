"""IngestManager 制品包摄入 + PyMuPDF4LLM 清洗 + clean.md offset 分块测试。

用 PyMuPDF 动态生成测试 PDF（仅作测试夹具，非生产抽取路径），验证：
制品包目录结构、clean.md 无可见页码、offset 不变量（clean_md[start:end]==chunk.text）、
页面 provenance、本地 Zotero 格式 document_id、失败回滚。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import fitz  # PyMuPDF（仅用于动态生成测试 PDF）
import pytest

from core.config import SourceStoreConfig
from core.domain.models import DocumentChunk, SourceDocument
from core.managers.ingest_manager import LOCAL_LIBRARY_ID, IngestManager
from core.managers.markdown_extractor import (
    MarkdownArtifact,
    PageSpan,
    join_cleaned_markdown_pages,
    post_clean_markdown_pages,
)
from core.repository.source_store.memory import InMemorySourceDocumentStore

_pdf_extract_available = importlib.util.find_spec("pymupdf4llm") is not None
pytestmark = pytest.mark.skipif(
    not _pdf_extract_available, reason="pymupdf4llm not installed"
)


@pytest.fixture
def temp_pdf(tmp_path: Path) -> Path:
    """动态创建一个含多段文字 + 一个超长段落的测试 PDF。"""
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()

    p1 = doc.new_page()
    text_p1 = (
        "Attention Is All You Need.\n\n"
        "The dominant sequence transduction models are based on complex recurrent or "
        "convolutional networks in an encoder-decoder configuration. The best performing "
        "models also connect the encoder and decoder through an attention mechanism.\n\n"
        "We propose a new simple network architecture, the Transformer, based solely on "
        "attention mechanisms, dispensing with recurrence and convolutions entirely."
    )
    p1.insert_textbox(fitz.Rect(50, 50, 550, 750), text_p1)

    p2 = doc.new_page()
    para_base = (
        "This is a super long paragraph designed to trigger "
        "the hard limit splitting mechanism. "
    )
    p2.insert_textbox(fitz.Rect(50, 50, 550, 750), para_base * 20)

    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _manager(store: InMemorySourceDocumentStore, data_dir: Path) -> IngestManager:
    config = SourceStoreConfig(
        db_filename="test.db", default_collection="papers", ocr_enabled=False
    )
    config.chunk_size = 1000  # type: ignore[attr-defined]
    return IngestManager(source_store=store, config=config, data_dir=data_dir)


def test_post_clean_removes_marginal_noise_and_repairs_wrapped_words() -> None:
    pages = [
        "REPEATED TEST HEADER\n1\nformal opera-\ntions stay readable.\n\nA clean paragraph stays visible.\n",
        "REPEATED TEST HEADER\n2\nco-\xad\nmotional potential remains.\n\nsystems,\n\nwhile edges continue.\n",
        "REPEATED TEST HEADER\n3\nplain text.\n",
    ]

    cleaned = post_clean_markdown_pages(pages)

    joined = "\n\n".join(cleaned)
    assert "REPEATED TEST HEADER" not in joined
    assert "\n1\n" not in joined and "\n2\n" not in joined and "\n3\n" not in joined
    assert "formal operations" in joined
    assert "co-motional potential" in joined
    assert "systems, while edges continue." in joined
    assert "A clean paragraph stays visible." in joined


def test_join_cleaned_pages_merges_cross_page_sentence_continuations() -> None:
    clean_md, spans = join_cleaned_markdown_pages(
        [
            "Because capitalism is effectively universal",
            "(potentially in force everywhere), capture can continue.",
        ],
        [74, 75],
    )

    assert "universal (potentially in force everywhere)" in clean_md
    assert "\n\n(potentially" not in clean_md
    assert [span.page for span in spans] == [74, 75]
    assert spans[0].end == spans[1].start


def test_chunker_respects_sentence_boundaries_and_adds_section_metadata(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)
    manager._config.chunk_size = 260  # type: ignore[attr-defined]
    paragraph = " ".join(
        [
            "The section body explains a synthetic mechanism without relying on source text.",
            "It keeps the explanatory paragraph intact across chunk packing decisions.",
            "It has enough detail to require the heading and body to remain associated.",
        ]
    )
    md = (
        "**T54**\n\n"
        "A previous numbered point contains a cross reference (T55). However: **T55**\n\n"
        f"{paragraph}\n\n"
        "**T56**\n\n"
        "Next thesis starts here."
    )
    artifact = MarkdownArtifact(
        clean_markdown=md,
        page_spans=[PageSpan(page=1, start=0, end=len(md))],
    )

    chunks = manager._chunk_artifact(
        document_id="doc",
        library_id=LOCAL_LIBRARY_ID,
        item_key="ITEM",
        attachment_key="ATTACH",
        artifact=artifact,
    )

    assert chunks
    for chunk in chunks:
        assert md[chunk.metadata["start_char"]:chunk.metadata["end_char"]] == chunk.text
        assert not chunk.text.rstrip().endswith("It has")
    t55_chunks = [chunk for chunk in chunks if chunk.metadata.get("section_label") == "T55"]
    assert t55_chunks
    assert any(chunk.text.lstrip().startswith("**T55**") for chunk in t55_chunks)
    assert any("synthetic mechanism" in chunk.text for chunk in t55_chunks)
    assert t55_chunks[0].metadata["chunk_schema"] == "clean_md_structural_v3"
    assert t55_chunks[0].metadata["section_type"] == "thesis"


def test_structural_chunker_keeps_citations_inside_paragraph(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)
    manager._config.chunk_size = 160  # type: ignore[attr-defined]
    sentence = (
        "This synthetic paragraph contains a parenthetical citation "
        "(Alpha et al., 2020; Beta et al., 2021). However, the next sentence continues "
        "with additional planning context so that the paragraph becomes long enough for "
        "packing pressure. "
    )
    long_paragraph = sentence * 3
    md = "**1.** **Introduction**\n\n" + long_paragraph + "\n\n" + "**2.** **Method**\n\nDone."
    artifact = MarkdownArtifact(md, [PageSpan(page=1, start=0, end=len(md))])

    chunks = manager._chunk_artifact(
        document_id="doc",
        library_id=LOCAL_LIBRARY_ID,
        item_key="ITEM",
        attachment_key="ATTACH",
        artifact=artifact,
    )

    assert len(chunks) > 1
    assert all(not chunk.text.lstrip().startswith(", 2021)") for chunk in chunks)
    assert all(not chunk.text.rstrip().endswith("et al.") for chunk in chunks)
    assert any("Beta et al., 2021). However" in chunk.text for chunk in chunks)


def test_structural_chunker_adds_numbered_section_and_caption_metadata(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)
    md = (
        "Introductory setup before numbered sections.\n\n"
        "**2.** **Methods**\n\n"
        "_2.1._ _Study area_\n\n"
        "The study area paragraph is synthetic and complete.\n\n"
        "**Fig. 1.** Synthetic research framework caption."
    )
    artifact = MarkdownArtifact(md, [PageSpan(page=1, start=0, end=len(md))])

    chunks = manager._chunk_artifact(
        document_id="doc",
        library_id=LOCAL_LIBRARY_ID,
        item_key="ITEM",
        attachment_key="ATTACH",
        artifact=artifact,
    )

    numbered = [chunk for chunk in chunks if chunk.metadata.get("section_label") == "2.1"]
    assert numbered
    assert numbered[0].metadata["section_path"] == ["2", "2.1"]
    assert "figure_caption" in numbered[-1].metadata["block_types"]


def test_structural_chunker_merges_short_parent_heading_with_first_child(
    tmp_path: Path,
) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)
    body = (
        "The study area paragraph is synthetic and long enough to represent the first "
        "body block under a numbered subsection without using any private source text. "
        "It explains the setup, scope, and complete sentence boundary for testing. "
    ) * 10
    md = (
        "Opening paragraph before the methods section.\n\n"
        "**2.** **Materials and methods**\n\n"
        "_2.1._ _Study area_\n\n"
        f"{body}\n\n"
        "_2.2._ _Data sources_\n\n"
        "A second synthetic subsection follows."
    )
    artifact = MarkdownArtifact(md, [PageSpan(page=1, start=0, end=len(md))])

    chunks = manager._chunk_artifact(
        document_id="doc",
        library_id=LOCAL_LIBRARY_ID,
        item_key="ITEM",
        attachment_key="ATTACH",
        artifact=artifact,
    )

    assert all(chunk.text.strip() != "**2.** **Materials and methods**" for chunk in chunks)
    assert all(
        not (
            chunk.metadata.get("block_types") == ["section_heading"]
            and len(chunk.text) < 160
        )
        for chunk in chunks
    )
    merged = next(
        chunk for chunk in chunks if "**2.** **Materials and methods**" in chunk.text
    )
    assert "_2.1._ _Study area_" in merged.text
    assert merged.metadata["section_label"] == "2.1"
    assert merged.metadata["section_labels"] == ["2", "2.1"]
    assert ["2"] in merged.metadata["section_paths"]
    assert ["2", "2.1"] in merged.metadata["section_paths"]


async def test_rebuild_document_chunks_from_legacy_clean_md(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)
    doc = SourceDocument(
        "doc1",
        "Legacy",
        str(tmp_path / "library" / "doc1" / "original.pdf"),
        "application/pdf",
        10,
        "hash",
        "papers",
        markdown_rel_path="clean.md",
        pages_rel_path="pages.json",
    )
    await store.add_document(doc)
    bundle = tmp_path / "library" / "doc1"
    bundle.mkdir(parents=True)
    pages = [
        "REPEATED TEST HEADER\n62\nEarlier text.",
        "REPEATED TEST HEADER\n63\n**T55**\n\nformal opera-\ntions continue.",
        "REPEATED TEST HEADER\n64\nLater text.",
    ]
    clean = "\n\n".join(pages)
    (bundle / "clean.md").write_text(clean, encoding="utf-8")
    spans = []
    cursor = 0
    for page_number, page_text in zip([62, 63, 64], pages):
        start = cursor
        cursor += len(page_text)
        if page_number != 64:
            cursor += 2
        spans.append(
            {
                "page": page_number,
                "markdown_start_char": start,
                "markdown_end_char": cursor,
            }
        )
    (bundle / "pages.json").write_text(json.dumps(spans), encoding="utf-8")
    await store.replace_chunks(
        "doc1", [DocumentChunk("doc1-0001", "doc1", 0, "old fragment", "old")]
    )

    rebuilt = await manager.rebuild_document_chunks_from_artifact("doc1")

    assert rebuilt == len(await store.list_chunks("doc1"))
    rebuilt_doc = await store.get_document("doc1")
    assert rebuilt_doc is not None and rebuilt_doc.needs_reindex is True
    clean_md = (bundle / "clean.md").read_text(encoding="utf-8")
    assert "REPEATED TEST HEADER" not in clean_md
    assert "formal operations" in clean_md
    chunks = await store.list_chunks("doc1")
    assert chunks[0].chunk_id == "doc1_c0000"
    assert chunks[0].metadata["chunk_schema"] == "clean_md_structural_v3"


async def test_artifact_bundle_and_offset_invariant(temp_pdf: Path, tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = _manager(store, tmp_path)

    document_id = await manager.ingest(
        title="Attention Paper",
        file_path=str(temp_pdf),
        content_type="application/pdf",
        size_bytes=temp_pdf.stat().st_size,
        collection="papers",
        tags=["transformer", "attention"],
    )

    # 1) document_id 为本地 Zotero 格式：LOCAL_<item>_<attachment>
    assert document_id.startswith(f"{LOCAL_LIBRARY_ID}_")
    assert len(document_id.split("_")) == 3

    doc = await store.get_document(document_id)
    assert doc is not None
    assert doc.origin.value == "local"
    assert doc.read_only is False
    assert doc.converter == "pymupdf4llm"
    assert doc.markdown_rel_path == "clean.md"

    # 2) 制品包目录结构
    bundle = tmp_path / "library" / document_id
    assert (bundle / "original.pdf").exists()
    assert (bundle / "clean.md").exists()
    assert (bundle / "pages.json").exists()
    assert (bundle / "meta.json").exists()
    assert Path(doc.file_path) == bundle / "original.pdf"

    clean_md = (bundle / "clean.md").read_text(encoding="utf-8")
    # 内容保真且无可见页码/页分隔符
    assert "Attention Is All You Need." in clean_md
    assert "dispensing with recurrence" in clean_md
    assert "--- end of page" not in clean_md and "page_number=" not in clean_md

    # 3) offset 不变量：每个 chunk 的 [start,end) 切片必须等于其 text
    chunks = await store.list_chunks(document_id)
    assert len(chunks) >= 1
    for c in chunks:
        s = c.metadata["start_char"]
        e = c.metadata["end_char"]
        assert clean_md[s:e] == c.text
        assert c.metadata["pages"]  # 至少映射到一页
        assert c.chunk_id == f"{document_id}_c{c.ordinal:04d}"

    # 4) 页面 provenance：两页，区间连续覆盖
    pages = await store.list_page_chunks(document_id)
    assert [p.page for p in pages] == [1, 2]
    assert pages[0].markdown_start_char == 0
    assert pages[1].markdown_end_char == len(clean_md)

    # 5) pages.json 落盘内容与 DB 一致
    pages_json = json.loads((bundle / "pages.json").read_text(encoding="utf-8"))
    assert pages_json[0]["page"] == 1

    # 6) 本地上传已镜像进 Zotero 表（origin=local）
    items = await store.list_zotero_items(LOCAL_LIBRARY_ID)
    assert len(items) == 1 and items[0].origin.value == "local"


async def test_ingest_raises_if_file_missing(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    manager = IngestManager(source_store=store, config=SourceStoreConfig(), data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        await manager.ingest(
            title="Missing",
            file_path="missing_file.pdf",
            content_type="application/pdf",
            size_bytes=100,
            collection="default",
        )


async def test_ingest_rolls_back_bundle_when_chunk_write_fails(
    temp_pdf: Path, tmp_path: Path
) -> None:
    class FailingStore(InMemorySourceDocumentStore):
        async def replace_chunks(self, doc_id, chunks) -> None:
            raise RuntimeError("chunk write failed")

    store = FailingStore()
    manager = _manager(store, tmp_path)

    with pytest.raises(RuntimeError, match="chunk write failed"):
        await manager.ingest(
            title="Rollback",
            file_path=str(temp_pdf),
            content_type="application/pdf",
            size_bytes=temp_pdf.stat().st_size,
            collection="default",
        )

    # 文档与制品包目录都应被回滚清理
    assert await store.list_documents() == []
    library_dir = tmp_path / "library"
    assert not any(library_dir.iterdir())
