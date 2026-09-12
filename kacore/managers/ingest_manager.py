"""本地文档摄入管理器（制品包模型 + PyMuPDF4LLM 清洗内核）。

职责：把一个 PDF/文本原件转为「制品包」——在 `data_dir/library/<document_id>/` 下集中存放
original.pdf / clean.md（无可见页码）/ pages.json（页→字符偏移）/ meta.json（归一化 + 原始元数据），
并在 clean.md 上做字符区间分块（保证 `clean.md[start:end] == chunk.text` 的 offset 不变量）。

标识：本地上传以 Zotero 格式镜像——合成 `LOCAL` 库 + 8 位 item/attachment key，
`document_id = LOCAL_<item_key>_<attachment_key>`，origin=LOCAL（可编辑）。同时写入 Zotero 镜像表，
使作用域检索/同步对本地与 Zotero 来源一视同仁。

不再保留 fitz 手写抽取路径：PDF 一律走 `markdown_extractor.extract_pdf_markdown`。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import shutil
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kacore.domain.filename_biblio import parse_filename_biblio
from kacore.domain.models import (
    DocumentChunk,
    DocumentOrigin,
    PageChunk,
    SourceDocument,
    ZoteroAttachment,
    ZoteroItem,
    ZoteroLibrary,
)
from kacore.managers.artifact_provenance import (
    PROCESSING_VERSION,
    load_provenance,
    save_provenance,
)
from kacore.managers.base import BaseIngestManager
from kacore.managers.chunk_token_limits import limit_chunk_spans
from kacore.managers.chunking import CHUNK_SCHEMA, build_structural_chunk_spans
from kacore.managers.markdown_extractor import (
    MarkdownArtifact,
    PageSpan,
    build_single_page_artifact,
    extract_pdf_markdown,
    join_cleaned_markdown_pages,
    post_clean_markdown_pages,
)
from kacore.utils.processing_lock import (
    ProcessingLock,
    complete_thread_call,
    serialized_processing,
)

if TYPE_CHECKING:
    from kacore.config import SourceStoreConfig
    from kacore.repository.source_store.base import SourceDocumentStore

# 本地合成库标识（与 SourceDocument.library_id 默认值一致）。
LOCAL_LIBRARY_ID = "LOCAL"

# Zotero 风格 key 字母表（去除易混淆字符），8 位。
_ZKEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"

# 制品包内固定文件名。
_ARTIFACT_PDF = "original.pdf"
_ARTIFACT_MD = "clean.md"
_ARTIFACT_PAGES = "pages.json"
_ARTIFACT_META = "meta.json"
_CHUNK_SCHEMA = CHUNK_SCHEMA


def gen_zotero_key() -> str:
    """生成一个 8 位 Zotero 风格 key。"""
    return "".join(secrets.choice(_ZKEY_ALPHABET) for _ in range(8))


def make_document_id(library_id: str, item_key: str, attachment_key: str) -> str:
    """制品包 canonical ID：<library_id>_<item_key>_<attachment_key>。"""
    return f"{library_id}_{item_key}_{attachment_key}"


def resolve_filename_biblio_hint(filename: str) -> tuple[str | None, dict[str, Any] | None]:
    """尝试从文件名解析书目猜测，返回 `(干净标题, biblio_hint)`；解析失败时两者均为 `None`。

    供本地上传与 Zotero 同步共用（两者都可能拿不到权威书目元数据，参见
    `kacore.domain.filename_biblio` 的 docstring）。`biblio_hint` 与
    `KnowledgeRepositoryApi.update_document_meta` 白名单同名（`creators`/`year`），
    落进 `SourceDocument.local_meta` 后由 `_document_biblio_meta()` 按「权威数据优先，
    此 hint 只补空」的规则合并，绝不覆盖真实书目数据。
    """
    parsed = parse_filename_biblio(filename)
    if parsed is None:
        return None, None
    hint: dict[str, Any] = {"creators": list(parsed.authors), "year": parsed.year}
    return parsed.title, hint


class IngestManager(BaseIngestManager):
    """具体的文档摄入与切块管理器（制品包 + clean.md offset 分块）。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        config: SourceStoreConfig,
        data_dir: Path,
    ) -> None:
        super().__init__()
        self._processing_lock = ProcessingLock()
        self._source_store = source_store
        self._config = config
        self._data_dir = data_dir
        # 制品包根目录：每文档一子目录 library/<document_id>/。
        self._library_dir = self._data_dir / "library"
        self._library_dir.mkdir(parents=True, exist_ok=True)

    # ── 公开入口：本地上传 ────────────────────────────────────────

    @serialized_processing
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
        """登记一个本地上传原件，返回 document_id。

        本地上传以 Zotero 格式镜像（LOCAL 库 + 合成 key），origin=LOCAL 可编辑。
        """
        self.logger.info(
            "Ingest start: title=%r collection=%r size=%d", title, collection, size_bytes
        )
        source_path = Path(file_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        item_key = gen_zotero_key()
        attachment_key = gen_zotero_key()
        document_id = make_document_id(LOCAL_LIBRARY_ID, item_key, attachment_key)

        # 上传时无书目元数据可言：原始文件名（title）如果长得像「作者 (年份) - 标题」，
        # 就顺带把干净标题与作者/年份猜测取出来，好过整篇挂着带扩展名的原始文件名。
        guessed_title, biblio_hint = resolve_filename_biblio_hint(title)
        resolved_title = guessed_title or title

        # 本地上传同样写入 Zotero 镜像（origin=local），使作用域检索/同步一视同仁。
        await self._source_store.upsert_zotero_library(
            ZoteroLibrary(library_id=LOCAL_LIBRARY_ID, library_type="LOCAL", name="本地上传")
        )
        await self._source_store.upsert_zotero_item(
            ZoteroItem(
                item_key=item_key,
                library_id=LOCAL_LIBRARY_ID,
                item_type="attachment",
                title=resolved_title,
                origin=DocumentOrigin.LOCAL,
            )
        )
        await self._source_store.upsert_zotero_attachment(
            ZoteroAttachment(
                attachment_key=attachment_key,
                parent_item_key=item_key,
                library_id=LOCAL_LIBRARY_ID,
                content_type=content_type,
                filename=source_path.name,
            )
        )

        await self.process_attachment(
            document_id=document_id,
            library_id=LOCAL_LIBRARY_ID,
            item_key=item_key,
            attachment_key=attachment_key,
            origin=DocumentOrigin.LOCAL,
            read_only=False,
            title=resolved_title,
            content_type=content_type,
            src_path=source_path,
            collection=collection,
            tags=list(tags or []),
            biblio_hint=biblio_hint,
        )
        return document_id

    # ── 可复用：把一个附件原件处理为制品包 ────────────────────────

    @serialized_processing
    async def process_attachment(
        self,
        *,
        document_id: str,
        library_id: str,
        item_key: str,
        attachment_key: str,
        origin: DocumentOrigin,
        read_only: bool,
        title: str,
        content_type: str,
        src_path: Path,
        collection: str,
        tags: list[str],
        zotero_version: int = 0,
        meta_extra: dict[str, Any] | None = None,
        biblio_hint: dict[str, Any] | None = None,
        last_synced_at: datetime | None = None,
        link_original: bool = False,
    ) -> SourceDocument:
        """把 src_path 处理为 document_id 的制品包并持久化（document + chunks + page_chunks）。

        供本地上传与 Zotero 同步共用。失败时回滚制品包目录与已写文档。

        link_original=True（Zotero linked 存储模式）：不拷贝原件，file_path 指向 Zotero 外部路径，
        但 clean.md/pages.json/meta.json 仍写入插件制品包目录；回滚不删除外部原件。

        biblio_hint：调用方（`ingest()` / Zotero 同步管线）算好的书目猜测（形如
        `{"creators": [...], "year": "..."}`，见 `resolve_filename_biblio_hint()`），本方法
        只负责原样存进 `local_meta`，不关心它是怎么算出来的——是否采信、如何与权威数据合并，
        由 `KnowledgeRepositoryApi._document_biblio_meta()` 决定。
        """
        bundle_dir = self._library_dir / document_id
        bundle_dir.mkdir(parents=True, exist_ok=True)
        dest_pdf = bundle_dir / _ARTIFACT_PDF
        document_added = False
        try:
            if link_original:
                source_pdf = src_path  # 原件留在 Zotero storage
            else:
                if src_path.resolve() != dest_pdf.resolve():
                    await asyncio.to_thread(shutil.copy2, src_path, dest_pdf)
                source_pdf = dest_pdf

            # 拷贝/哈希/PDF 解析均为阻塞 CPU/IO，丢进线程避免堵塞事件循环
            # （Zotero 同步逐篇调用本方法时，阻塞会连带卡住其余并发 HTTP 请求，
            # 表现为前端 /active 轮询超时、进度弹窗忽隐忽现）。
            content_bytes, file_hash = await asyncio.to_thread(self._read_and_hash, source_pdf)

            # 1) 抽取干净 Markdown + 页面字符偏移
            artifact = await asyncio.to_thread(self._extract_artifact, source_pdf, content_type)

            # 2) 落盘 clean.md / pages.json / meta.json
            await complete_thread_call(save_provenance, bundle_dir, artifact)
            (bundle_dir / _ARTIFACT_MD).write_text(artifact.clean_markdown, encoding="utf-8")
            pages_payload = [
                {"page": s.page, "markdown_start_char": s.start, "markdown_end_char": s.end}
                for s in artifact.page_spans
            ]
            (bundle_dir / _ARTIFACT_PAGES).write_text(
                json.dumps(pages_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            meta_payload = {
                "document_id": document_id,
                "library_id": library_id,
                "item_key": item_key,
                "attachment_key": attachment_key,
                "origin": origin.value,
                "title": title,
                "converter": artifact.converter,
                "converter_version": artifact.converter_version,
                "chunk_schema": _CHUNK_SCHEMA,
                "pdf_metadata": artifact.pdf_metadata,
            }
            if meta_extra:
                meta_payload.update(meta_extra)
            (bundle_dir / _ARTIFACT_META).write_text(
                json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 3) clean.md 上的字符区间分块（offset 不变量）
            chunks = await asyncio.to_thread(
                self._chunk_artifact,
                document_id=document_id,
                library_id=library_id,
                item_key=item_key,
                attachment_key=attachment_key,
                artifact=artifact,
            )
            page_chunks = [
                PageChunk(
                    document_id=document_id,
                    page=s.page,
                    markdown_start_char=s.start,
                    markdown_end_char=s.end,
                )
                for s in artifact.page_spans
            ]

            # 4) 持久化领域对象
            now = datetime.now(timezone.utc)
            doc = SourceDocument(
                doc_id=document_id,
                title=title,
                file_path=str(source_pdf),
                content_type=content_type,
                size_bytes=len(content_bytes),
                content_hash=file_hash,
                collection=collection,
                tags=list(tags),
                created_at=now,
                updated_at=now,
                library_id=library_id,
                zotero_item_key=item_key,
                attachment_key=attachment_key,
                origin=origin,
                read_only=read_only,
                zotero_version=zotero_version,
                markdown_rel_path=_ARTIFACT_MD,
                pages_rel_path=_ARTIFACT_PAGES,
                converter=artifact.converter,
                converter_version=artifact.converter_version,
                last_synced_at=last_synced_at,
                local_meta={"chunk_schema": _CHUNK_SCHEMA, "processing_version": PROCESSING_VERSION,
                            **(biblio_hint or {})},
            )
            # 幂等：本地首次为 add；Zotero 重同步为 update（覆盖已存在制品包）。
            existing = await self._source_store.get_document(document_id)
            if existing is None:
                await self._source_store.add_document(doc)
            else:
                doc.local_meta = {**existing.local_meta, **doc.local_meta}
                await self._source_store.update_document(doc)
            document_added = existing is None
            await self._source_store.replace_chunks(document_id, chunks)
            await self._source_store.replace_page_chunks(document_id, page_chunks)
        except Exception:
            if document_added:
                await self._source_store.delete_document(document_id)
            # 制品包目录仅含派生制品（link 模式原件在外部 Zotero storage），可安全整体清理。
            shutil.rmtree(bundle_dir, ignore_errors=True)
            raise

        self.logger.info(
            "Ingested %s (%s) with %d chunks, %d pages.",
            title,
            document_id,
            len(chunks),
            len(artifact.page_spans),
        )
        return doc

    @serialized_processing
    async def rebuild_document_chunks_from_artifact(self, document_id: str) -> int:
        """从现有 clean.md/pages.json 重新清洗并生成 paragraph-aware chunks。

        用于 legacy chunk 修复：不读取或修改 PDF 原件，只更新制品包派生文本、page spans、
        SQLite chunks，并把文档标记为 Milvus 待重建。
        """
        doc = await self._source_store.get_document(document_id)
        if doc is None:
            raise FileNotFoundError(f"Document not found: {document_id}")
        if doc.local_meta.get("processing_pending"):
            result = await self.reextract_document(document_id)
            return int(result["chunk_count"])
        clean_path = self._resolve_artifact_path(doc, doc.markdown_rel_path or _ARTIFACT_MD)
        if clean_path is None:
            raise FileNotFoundError(f"Markdown artifact not found for {document_id}")

        artifact = await asyncio.to_thread(self._load_and_reclean_artifact, doc, clean_path)
        pages_path = self._resolve_artifact_path(doc, doc.pages_rel_path or _ARTIFACT_PAGES)
        doc.needs_reindex = True
        doc.local_meta = {**doc.local_meta, "processing_pending": True}
        await self._source_store.update_document(doc)
        clean_path.write_text(artifact.clean_markdown, encoding="utf-8")
        if pages_path is not None:
            pages_payload = [
                {"page": s.page, "markdown_start_char": s.start, "markdown_end_char": s.end}
                for s in artifact.page_spans
            ]
            pages_path.write_text(
                json.dumps(pages_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        chunks = await asyncio.to_thread(
            self._chunk_artifact,
            document_id=doc.doc_id,
            library_id=doc.library_id,
            item_key=doc.zotero_item_key,
            attachment_key=doc.attachment_key,
            artifact=artifact,
        )
        doc.needs_reindex = True
        doc.local_meta = {**doc.local_meta, "chunk_schema": _CHUNK_SCHEMA,
                          "processing_version": PROCESSING_VERSION}
        await self._source_store.commit_document_processing(doc, chunks, [
            PageChunk(doc.doc_id, span.page, span.start, span.end) for span in artifact.page_spans
        ])
        self.logger.info("Rebuilt %s with %d paragraph-aware chunks.", doc.doc_id, len(chunks))
        return len(chunks)

    @serialized_processing
    async def reextract_document(self, doc_id: str) -> dict[str, Any]:
        """从制品包中已存储的原件（original.pdf）重新提取 Markdown，覆写 clean.md/pages.json，
        重新分块，并标记 Milvus 待重建。

        适用于：提取代码升级（如 ignore_alpha=True）后，修复已摄入文档的陈旧内容。
        不支持 txt/md 纯文本文档（无需重新提取）。

        返回：{"chunk_count": int, "converter_version": str}
        """
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            raise FileNotFoundError(f"Document not found: {doc_id}")

        # 定位原件：优先制品包内 original.pdf，其次 file_path（Zotero linked 模式）。
        bundle_pdf = self._library_dir / doc_id / _ARTIFACT_PDF
        if bundle_pdf.is_file():
            source_pdf = bundle_pdf
        elif doc.file_path and Path(doc.file_path).is_file():
            source_pdf = Path(doc.file_path)
        else:
            raise FileNotFoundError(
                f"Original PDF not found for {doc_id}. "
                "Restore the original file and retry processing."
            )

        recover_text = (bool(doc.local_meta.get("processing_pending"))
                        and doc.content_type.startswith("text/"))
        if (not recover_text and doc.content_type not in ("application/pdf", "")
                and not str(source_pdf).lower().endswith(".pdf")):
            raise ValueError(
                "reextract_document only supports PDF files, "
                f"got content_type={doc.content_type!r}"
            )

        # 先持久化恢复意图；即使抽取、文件发布、事务提交失败/取消，重启后仍可检测。
        doc.needs_reindex = True
        doc.local_meta = {**doc.local_meta, "processing_pending": True}
        await self._source_store.update_document(doc)

        # 重新提取（使用当前已修复的 ignore_alpha=True 代码）。
        if recover_text:
            # 旧纯文本重切中断也从原件恢复，不把名为 original.pdf 的文本副本送进 PDF 解析器。
            text = await asyncio.to_thread(source_pdf.read_text, encoding="utf-8", errors="replace")
            artifact = build_single_page_artifact(text)
        else:
            artifact = await asyncio.to_thread(
                self._extract_artifact, source_pdf, doc.content_type or "application/pdf"
            )

        # 覆写制品包中的派生文件。
        bundle_dir = self._library_dir / doc_id
        bundle_dir.mkdir(parents=True, exist_ok=True)
        await complete_thread_call(save_provenance, bundle_dir, artifact)
        (bundle_dir / _ARTIFACT_MD).write_text(artifact.clean_markdown, encoding="utf-8")
        pages_payload = [
            {"page": s.page, "markdown_start_char": s.start, "markdown_end_char": s.end}
            for s in artifact.page_spans
        ]
        (bundle_dir / _ARTIFACT_PAGES).write_text(
            json.dumps(pages_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 重新分块并替换 SQLite 中的 chunks。
        chunks = await asyncio.to_thread(
            self._chunk_artifact,
            document_id=doc.doc_id,
            library_id=doc.library_id,
            item_key=doc.zotero_item_key,
            attachment_key=doc.attachment_key,
            artifact=artifact,
        )

        # 更新元数据并标记待重建。
        doc.converter = artifact.converter
        doc.converter_version = artifact.converter_version
        doc.needs_reindex = True
        doc.local_meta = {**doc.local_meta, "chunk_schema": _CHUNK_SCHEMA,
                          "processing_version": PROCESSING_VERSION}
        await self._source_store.commit_document_processing(doc, chunks, [
            PageChunk(doc.doc_id, span.page, span.start, span.end) for span in artifact.page_spans
        ])

        self.logger.info(
            "Re-extracted %s → %d chunks, converter_version=%s",
            doc_id, len(chunks), artifact.converter_version,
        )
        return {"chunk_count": len(chunks), "converter_version": artifact.converter_version}

    def _resolve_artifact_path(self, doc: SourceDocument, rel_path: str) -> Path | None:
        candidates = [
            self._library_dir / doc.doc_id / rel_path,
            self._data_dir / "managed_docs" / doc.doc_id / rel_path,
            Path(doc.file_path).parent / rel_path,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _load_and_reclean_artifact(self, doc: SourceDocument, clean_path: Path) -> MarkdownArtifact:
        clean_md = clean_path.read_text(encoding="utf-8")
        page_spans = self._load_page_spans(doc, len(clean_md))
        original_pages, notes = load_provenance(clean_path.parent)
        if original_pages or notes:
            return MarkdownArtifact(clean_md, page_spans, raw_pages=original_pages, footnotes=notes)
        raw_pages = [clean_md[span.start:span.end] for span in page_spans] or [clean_md]
        page_numbers = [span.page for span in page_spans] or [1]
        clean_markdown, rebuilt_spans = join_cleaned_markdown_pages(
            post_clean_markdown_pages(raw_pages),
            page_numbers,
        )
        return MarkdownArtifact(
            clean_markdown=clean_markdown,
            page_spans=rebuilt_spans,
            pdf_metadata={},
            converter=doc.converter or "clean_md",
            converter_version=doc.converter_version,
        )

    def _load_page_spans(self, doc: SourceDocument, text_len: int) -> list[PageSpan]:
        pages_path = self._resolve_artifact_path(doc, doc.pages_rel_path or _ARTIFACT_PAGES)
        if pages_path is None:
            return [PageSpan(page=1, start=0, end=text_len)]
        try:
            payload = json.loads(pages_path.read_text(encoding="utf-8"))
        except Exception:
            return [PageSpan(page=1, start=0, end=text_len)]
        spans: list[PageSpan] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                start = int(item.get("markdown_start_char", 0))
                end = int(item.get("markdown_end_char", 0))
                page = int(item.get("page", len(spans) + 1))
                if 0 <= start <= end <= text_len:
                    spans.append(PageSpan(page=page, start=start, end=end))
        return spans or [PageSpan(page=1, start=0, end=text_len)]

    @staticmethod
    def chunk_needs_rebuild(
        document_id: str,
        chunks: list[DocumentChunk],
        local_meta: dict[str, Any] | None = None,
    ) -> bool:
        """判断旧式 chunks 是否需要按当前 clean.md offset schema 重建。

        `processing_version` 判据只读 local_meta，不需要读 chunk：分块/清洗逻辑升级而
        `CHUNK_SCHEMA` 未升版本时，靠它识别旧数据（重切后会写回当前版本，判据自动失效）。
        """
        if local_meta and local_meta.get("processing_pending"):
            return True
        if local_meta is not None and local_meta.get("processing_version") != PROCESSING_VERSION:
            return True
        if not chunks:
            return True
        expected_prefix = f"{document_id}_c"
        for chunk in chunks:
            if not chunk.chunk_id.startswith(expected_prefix):
                return True
            if chunk.metadata.get("chunk_schema") != _CHUNK_SCHEMA:
                return True
            if "start_char" not in chunk.metadata or "end_char" not in chunk.metadata:
                return True
        return False

    # ── 抽取 ──────────────────────────────────────────────────────

    @staticmethod
    def _read_and_hash(path: Path) -> tuple[bytes, str]:
        content_bytes = path.read_bytes()
        return content_bytes, hashlib.sha256(content_bytes).hexdigest()

    def _extract_artifact(self, path: Path, content_type: str) -> MarkdownArtifact:
        """PDF → PyMuPDF4LLM 清洗；txt/md → 单页纯文本制品。"""
        if self._config.ocr_enabled:
            warnings.warn(
                "OCR/LLM extraction is enabled which may incur substantial computation/API costs.",
                UserWarning,
                stacklevel=2,
            )
        suffix = path.suffix.lower()
        is_pdf = content_type == "application/pdf" or suffix == ".pdf"
        if is_pdf:
            return extract_pdf_markdown(str(path))
        if suffix in (".txt", ".md", ".markdown"):
            return build_single_page_artifact(path.read_text(encoding="utf-8", errors="replace"))
        # 其它类型暂按纯文本兜底（避免摄入直接失败）。
        return build_single_page_artifact(path.read_text(encoding="utf-8", errors="replace"))

    # ── clean.md 字符区间分块 ─────────────────────────────────────

    def _chunk_artifact(
        self,
        *,
        document_id: str,
        library_id: str,
        item_key: str,
        attachment_key: str,
        artifact: MarkdownArtifact,
    ) -> list[DocumentChunk]:
        md = artifact.clean_markdown
        chunk_size = getattr(self._config, "chunk_size", 1000)
        chunk_spans, _, _ = build_structural_chunk_spans(md, chunk_size=chunk_size)
        chunk_spans = limit_chunk_spans(md, chunk_spans)
        is_zotero = library_id != LOCAL_LIBRARY_ID
        revision = hashlib.sha256(
            (md + json.dumps([{**asdict(n), "doc_id": document_id}
                              for n in artifact.footnotes], sort_keys=True)
             + json.dumps([(s.start, s.end) for s in chunk_spans])
             + PROCESSING_VERSION).encode("utf-8")
        ).hexdigest()[:16]

        chunks: list[DocumentChunk] = []
        for idx, chunk_span in enumerate(chunk_spans):
            cs = chunk_span.start
            ce = chunk_span.end
            text = md[cs:ce]
            pages = [s.page for s in artifact.page_spans if s.start < ce and s.end > cs]
            page_number = pages[0] if pages else 1
            metadata: dict[str, Any] = {
                **chunk_span.metadata,
                "pages": pages,
                "page_number": page_number,
                "start_char": cs,
                "end_char": ce,
                "locator": f"page_{page_number}_o{cs}",
                "chunk_kind": "body",
                "revision_id": revision,
                "processing_version": PROCESSING_VERSION,
                "footnotes": [
                    {**asdict(n), "doc_id": document_id} for n in artifact.footnotes
                    if n.body_marker_span is not None and any(
                        p.page == n.page and cs <= p.start + n.body_marker_span[0] < ce
                        for p in artifact.page_spans
                    )
                ],
            }
            # Zotero 跳转链接仅对真实 Zotero 库有意义；本地合成 key 不构造。
            if is_zotero:
                metadata["zotero_item_uri"] = f"zotero://select/library/items/{item_key}"
                metadata["zotero_pdf_uri"] = (
                    f"zotero://open-pdf/library/items/{attachment_key}?page={page_number}"
                )
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_c{idx:04d}_r{revision}",
                    doc_id=document_id,
                    ordinal=idx,
                    text=text,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    metadata=metadata,
                )
            )
        return chunks


__all__ = ["IngestManager", "gen_zotero_key", "make_document_id", "LOCAL_LIBRARY_ID"]
