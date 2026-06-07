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
from core.managers.ingest_manager import LOCAL_LIBRARY_ID, IngestManager
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
    assert len(chunks) >= 2  # 超长段落触发句末再切
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
