"""本地 PDF 文档摄入管理器的实现。

负责原件注册、基于 PyMuPDF (fitz) 的本地免成本文本抽取、
高度稳定的「物理页隔离 + 动态段落合并」切块算法，以及持久化写入。
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.domain.models import DocumentChunk, SourceDocument
from core.managers.base import BaseIngestManager

if TYPE_CHECKING:
    from core.config import SourceStoreConfig
    from core.repository.source_store.base import SourceDocumentStore


class IngestManager(BaseIngestManager):
    """具体的 PDF 文档摄入与切块管理器。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        config: SourceStoreConfig,
        data_dir: Path,
    ) -> None:
        super().__init__()
        self._source_store = source_store
        self._config = config
        self._data_dir = data_dir

        # 确保文档原件存储专用子目录存在
        self._docs_dir = self._data_dir / "documents"
        self._docs_dir.mkdir(parents=True, exist_ok=True)

    async def ingest(
        self,
        *,
        title: str,
        file_path: str,
        content_type: str,
        size_bytes: int,
        collection: str,
        tags: list[str] | None = None,
    ) -> str:
        source_path = Path(file_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        # 1) 生成稳定的外部 ID
        doc_id = uuid.uuid4().hex

        # 2) 物理拷贝至插件管理的原件库目录，防止外部临时文件被删
        dest_path = self._docs_dir / f"{doc_id}.pdf"
        copied = source_path.resolve() != dest_path.resolve()
        document_added = False
        try:
            if copied:
                shutil.copy2(source_path, dest_path)

            # 3) 计算文件内容哈希 (SHA-256)
            with open(dest_path, "rb") as f:
                content_bytes = f.read()
            file_hash = hashlib.sha256(content_bytes).hexdigest()

            # 4) 抽取文本与分块
            chunks = self._extract_and_chunk(dest_path, doc_id)

            # 5) 创建文档领域实体
            now = datetime.now(timezone.utc)
            doc = SourceDocument(
                doc_id=doc_id,
                title=title,
                file_path=str(dest_path),
                content_type=content_type,
                size_bytes=size_bytes,
                content_hash=file_hash,
                collection=collection,
                tags=list(tags or []),
                created_at=now,
                updated_at=now,
            )

            # 6) 写入仓储 (事务级，先加文档元数据，再写入分块)
            await self._source_store.add_document(doc)
            document_added = True
            await self._source_store.replace_chunks(doc_id, chunks)
        except Exception:
            if document_added:
                await self._source_store.delete_document(doc_id)
            if copied:
                dest_path.unlink(missing_ok=True)
            raise

        self.logger.info(
            f"Successfully ingested document {title} (ID: {doc_id}) with {len(chunks)} chunks."
        )
        return doc_id

    def _extract_and_chunk(self, pdf_path: Path, doc_id: str) -> list[DocumentChunk]:
        """使用 PyMuPDF 抽取文本并按「物理页隔离 + 动态段落合并」执行高稳定性切分，
        同时生成页码、定位符等元数据。
        """
        # 触发 OCR/LLM 可选功能警示提示
        if self._config.ocr_enabled:
            warnings.warn(
                "OCR/LLM extraction is enabled which may incur substantial computation/API costs.",
                UserWarning,
            )

        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError(
                "PDF 文本抽取需要 PyMuPDF，请在运行环境中执行：pip install PyMuPDF"
            ) from exc

        doc = fitz.open(pdf_path)
        pages_text: list[str] = []

        for page in doc:
            # 基础文本抽取。后续可引入 block/结构识别以过滤页眉页脚
            text = page.get_text("text")
            pages_text.append(text)

        doc.close()

        # 切分参数计算
        chunk_size = getattr(self._config, "chunk_size", 1000)
        chunk_by_page = getattr(self._config, "chunk_by_page", True)

        target_min = int(chunk_size * 0.8)   # 默认 800 字
        target_max = int(chunk_size * 1.2)   # 默认 1200 字
        hard_limit = int(chunk_size * 1.5)   # 默认 1500 字

        chunk_entries: list[tuple[str, dict[str, Any]]] = []

        if chunk_by_page:
            # 方案 A: 物理页物理边界隔离，独立切分，哈希变动仅局限单页
            for page_idx, page_text in enumerate(pages_text):
                page_num = page_idx + 1
                paras = self._split_into_paragraphs(page_text, target_min, target_max, hard_limit)
                for para_idx, text in enumerate(paras):
                    chunk_entries.append((
                        text,
                        {
                            "page_number": page_num,
                            "locator": f"page_{page_num}_p{para_idx + 1}",
                            "paragraph": para_idx + 1,
                        }
                    ))
        else:
            # 方案 B: 全文打散合并，无边界连续段落合并
            all_text = "\n\n".join(pages_text)
            paras = self._split_into_paragraphs(all_text, target_min, target_max, hard_limit)
            for para_idx, text in enumerate(paras):
                # 启发式页码定位：在 pages_text 中搜索该文本的前 100 个字符
                page_num = 1
                sample = text[:100].strip()
                if sample:
                    for p_idx, p_txt in enumerate(pages_text):
                        if sample in p_txt:
                            page_num = p_idx + 1
                            break
                chunk_entries.append((
                    text,
                    {
                        "page_number": page_num,
                        "locator": f"page_{page_num}_p{para_idx + 1}",
                        "paragraph": para_idx + 1,
                    }
                ))

        # 构造领域 DocumentChunk 对象
        chunks = []
        for idx, (text, meta) in enumerate(chunk_entries):
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc_id}-c{idx}",
                    doc_id=doc_id,
                    ordinal=idx,
                    text=text,
                    content_hash=chunk_hash,
                    metadata=meta,
                )
            )
        return chunks



    def _split_into_paragraphs(
        self, text: str, target_min: int, target_max: int, hard_limit: int
    ) -> list[str]:
        """动态段落合并算法核心。"""
        # 以双换行符分割自然段落
        raw_paras = [p.strip() for p in text.split("\n\n")]
        # 如果双换行分割失败（可能部分PDF只有单换行），退而使用单换行，并合并过短的行
        if len(raw_paras) <= 1:
            raw_paras = [p.strip() for p in text.split("\n") if p.strip()]

        paragraphs = [p for p in raw_paras if p]

        chunks: list[str] = []
        current_block: list[str] = []
        current_len = 0

        def _flush(blocks: list[str]):
            txt = "\n\n".join(blocks).strip()
            if txt:
                chunks.append(txt)

        for para in paragraphs:
            para_len = len(para)

            # 超长单段安全保护，强制句号切分
            if para_len > hard_limit:
                if current_block:
                    _flush(current_block)
                    current_block = []
                    current_len = 0

                # 按中英文句号/问号/感叹号分句
                sentences = []
                curr_sent = ""
                for char in para:
                    curr_sent += char
                    if char in ("。", "？", "！", ".", "?", "!"):
                        sentences.append(curr_sent.strip())
                        curr_sent = ""
                if curr_sent.strip():
                    sentences.append(curr_sent.strip())

                sent_blocks: list[str] = []
                sent_len = 0
                for sent in sentences:
                    if sent_len + len(sent) > target_max and sent_blocks:
                        chunks.append(" ".join(sent_blocks))
                        sent_blocks = [sent]
                        sent_len = len(sent)
                    else:
                        sent_blocks.append(sent)
                        sent_len += len(sent)
                if sent_blocks:
                    chunks.append(" ".join(sent_blocks))

            else:
                # 正常段落，动态合并
                if current_len + para_len > target_max and current_block:
                    _flush(current_block)
                    current_block = [para]
                    current_len = para_len
                else:
                    current_block.append(para)
                    current_len += para_len
                    # 当累加达到黄金字数区间，且后续有超出风险时在段落末尾切分
                    if current_len >= target_min and current_len <= target_max:
                        # 这是一个完美的切分点
                        pass

        if current_block:
            _flush(current_block)

        return chunks


__all__ = ["IngestManager"]
