"""IngestManager PDF 抽取与段落合并切分测试。

使用 PyMuPDF 动态生成测试用 PDF 原件，
在 IngestManager 内运行文本抽取，验证物理页隔离、动态段落合并的字数切分契约。
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytest

from core.config import SourceStoreConfig
from core.managers.ingest_manager import IngestManager
from core.repository.source_store.memory import InMemorySourceDocumentStore


@pytest.fixture
def temp_pdf(tmp_path: Path) -> Path:
    """动态创建一个含有多段文字的测试用 PDF 原件。"""
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()

    # 第一页：含有 3 个正常自然段
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

    # 第二页：含有 1 个超大段落（用于测试超限强制切分）
    p2 = doc.new_page()
    # 构造一个 1600 字符左右的超级长段落，里面有多个句号
    para_base = (
        "This is a super long paragraph designed to trigger "
        "the hard limit splitting mechanism. "
    )
    long_para = para_base * 20
    p2.insert_textbox(fitz.Rect(50, 50, 550, 750), long_para)

    doc.save(pdf_path)
    doc.close()
    return pdf_path


async def test_pdf_ingestion_and_paragraph_chunking(temp_pdf: Path, tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    config = SourceStoreConfig(
        db_filename="test.db",
        default_collection="papers",
        ocr_enabled=False,
    )
    # 给 SourceStoreConfig 动态注入 chunk 参数进行测试
    setattr(config, "chunk_size", 1000)
    setattr(config, "chunk_by_page", True)

    manager = IngestManager(
        source_store=store,
        config=config,
        data_dir=tmp_path,
    )

    # 执行摄入
    doc_id = await manager.ingest(
        title="Attention Paper",
        file_path=str(temp_pdf),
        content_type="application/pdf",
        size_bytes=temp_pdf.stat().st_size,
        collection="papers",
        tags=["transformer", "attention"],
    )

    # 1) 验证文档是否成功登记，并且拷贝到了本地插件管理文件夹下
    doc = await store.get_document(doc_id)
    assert doc is not None
    assert doc.title == "Attention Paper"
    assert doc.collection == "papers"
    assert doc.tags == ["transformer", "attention"]
    assert Path(doc.file_path).exists()
    assert Path(doc.file_path).name == f"{doc_id}.pdf"

    # 2) 验证分块是否按照契约提取
    chunks = await store.list_chunks(doc_id)
    assert len(chunks) > 0

    # 3) 第一页分块（c0）应该保留段落的完整性，不被截断
    c0 = chunks[0]
    assert c0.doc_id == doc_id
    assert c0.ordinal == 0
    # 内容中应该包含第一页的段落特征词
    assert "Attention Is All You Need." in c0.text
    assert "dispensing with recurrence" in c0.text

    # 4) 验证超长段落是否被强制在句号句末切开
    # 第一页文字大约 400 字，按页隔离后会合并为一个 chunk (idx 0)
    # 第二页文字大约 1600 字，超出了 hard_limit 1500 字，会被子切分为两个 chunks (idx 1 和 2)
    assert len(chunks) == 3
    assert "trigger the hard limit" in chunks[1].text
    assert "trigger the hard limit" in chunks[2].text


async def test_ingest_raises_if_file_missing(tmp_path: Path) -> None:
    store = InMemorySourceDocumentStore()
    config = SourceStoreConfig()
    manager = IngestManager(source_store=store, config=config, data_dir=tmp_path)

    with pytest.raises(FileNotFoundError):
        await manager.ingest(
            title="Missing",
            file_path="missing_file.pdf",
            content_type="pdf",
            size_bytes=100,
            collection="default",
        )
