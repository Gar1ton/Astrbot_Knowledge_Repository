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

import hashlib
import json
import re
import secrets
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.domain.models import (
    DocumentChunk,
    DocumentOrigin,
    PageChunk,
    SourceDocument,
    ZoteroAttachment,
    ZoteroItem,
    ZoteroLibrary,
)
from core.managers.base import BaseIngestManager
from core.managers.markdown_extractor import (
    MarkdownArtifact,
    build_single_page_artifact,
    extract_pdf_markdown,
)

if TYPE_CHECKING:
    from core.config import SourceStoreConfig
    from core.repository.source_store.base import SourceDocumentStore

# 本地合成库标识（与 SourceDocument.library_id 默认值一致）。
LOCAL_LIBRARY_ID = "LOCAL"

# Zotero 风格 key 字母表（去除易混淆字符），8 位。
_ZKEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"

# 制品包内固定文件名。
_ARTIFACT_PDF = "original.pdf"
_ARTIFACT_MD = "clean.md"
_ARTIFACT_PAGES = "pages.json"
_ARTIFACT_META = "meta.json"

# 句末切分符（中英文）。
_SENTENCE_ENDERS = "。？！.?!"


def gen_zotero_key() -> str:
    """生成一个 8 位 Zotero 风格 key。"""
    return "".join(secrets.choice(_ZKEY_ALPHABET) for _ in range(8))


def make_document_id(library_id: str, item_key: str, attachment_key: str) -> str:
    """制品包 canonical ID：<library_id>_<item_key>_<attachment_key>。"""
    return f"{library_id}_{item_key}_{attachment_key}"


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
        self._source_store = source_store
        self._config = config
        self._data_dir = data_dir
        # 制品包根目录：每文档一子目录 library/<document_id>/。
        self._library_dir = self._data_dir / "library"
        self._library_dir.mkdir(parents=True, exist_ok=True)

    # ── 公开入口：本地上传 ────────────────────────────────────────

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

        # 本地上传同样写入 Zotero 镜像（origin=local），使作用域检索/同步一视同仁。
        await self._source_store.upsert_zotero_library(
            ZoteroLibrary(library_id=LOCAL_LIBRARY_ID, library_type="LOCAL", name="本地上传")
        )
        await self._source_store.upsert_zotero_item(
            ZoteroItem(
                item_key=item_key,
                library_id=LOCAL_LIBRARY_ID,
                item_type="attachment",
                title=title,
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
            title=title,
            content_type=content_type,
            src_path=source_path,
            collection=collection,
            tags=list(tags or []),
        )
        return document_id

    # ── 可复用：把一个附件原件处理为制品包 ────────────────────────

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
        last_synced_at: datetime | None = None,
        link_original: bool = False,
    ) -> SourceDocument:
        """把 src_path 处理为 document_id 的制品包并持久化（document + chunks + page_chunks）。

        供本地上传与 Zotero 同步共用。失败时回滚制品包目录与已写文档。

        link_original=True（Zotero linked 存储模式）：不拷贝原件，file_path 指向 Zotero 外部路径，
        但 clean.md/pages.json/meta.json 仍写入插件制品包目录；回滚不删除外部原件。
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
                    shutil.copy2(src_path, dest_pdf)
                source_pdf = dest_pdf

            with open(source_pdf, "rb") as f:
                content_bytes = f.read()
            file_hash = hashlib.sha256(content_bytes).hexdigest()

            # 1) 抽取干净 Markdown + 页面字符偏移
            artifact = self._extract_artifact(source_pdf, content_type)

            # 2) 落盘 clean.md / pages.json / meta.json
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
                "pdf_metadata": artifact.pdf_metadata,
            }
            if meta_extra:
                meta_payload.update(meta_extra)
            (bundle_dir / _ARTIFACT_META).write_text(
                json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 3) clean.md 上的字符区间分块（offset 不变量）
            chunks = self._chunk_artifact(
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
            )
            # 幂等：本地首次为 add；Zotero 重同步为 update（覆盖已存在制品包）。
            existing = await self._source_store.get_document(document_id)
            if existing is None:
                await self._source_store.add_document(doc)
            else:
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

    # ── 抽取 ──────────────────────────────────────────────────────

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
        target_min = int(chunk_size * 0.8)
        target_max = int(chunk_size * 1.2)
        hard_limit = int(chunk_size * 1.5)

        spans = self._chunk_spans(md, target_min, target_max, hard_limit)
        is_zotero = library_id != LOCAL_LIBRARY_ID

        chunks: list[DocumentChunk] = []
        for idx, (cs, ce) in enumerate(spans):
            text = md[cs:ce]
            pages = [s.page for s in artifact.page_spans if s.start < ce and s.end > cs]
            page_number = pages[0] if pages else 1
            metadata: dict[str, Any] = {
                "pages": pages,
                "page_number": page_number,
                "start_char": cs,
                "end_char": ce,
                "locator": f"page_{page_number}_o{cs}",
            }
            # Zotero 跳转链接仅对真实 Zotero 库有意义；本地合成 key 不构造。
            if is_zotero:
                metadata["zotero_item_uri"] = (
                    f"zotero://select/library/items/{item_key}"
                )
                metadata["zotero_pdf_uri"] = (
                    f"zotero://open-pdf/library/items/{attachment_key}?page={page_number}"
                )
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_c{idx:04d}",
                    doc_id=document_id,
                    ordinal=idx,
                    text=text,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    metadata=metadata,
                )
            )
        return chunks

    @staticmethod
    def _paragraph_spans(md: str) -> list[tuple[int, int]]:
        """把 clean.md 切为段落字符区间（按空行分隔；退化时按单换行）。

        返回的每个 [start,end) 都是 md 的精确子串区间（不做文本变换），保证 offset 不变量。
        """
        if not md.strip():
            return []
        spans: list[tuple[int, int]] = []
        pos = 0
        for m in re.finditer(r"\n[ \t]*\n[ \t\n]*", md):
            if m.start() > pos:
                spans.append((pos, m.start()))
            pos = m.end()
        if pos < len(md):
            spans.append((pos, len(md)))
        # 退化：整篇没有空行分隔（单段），改按单换行切。
        if len(spans) <= 1 and "\n" in md:
            spans = []
            pos = 0
            for m in re.finditer(r"\n+", md):
                if m.start() > pos:
                    spans.append((pos, m.start()))
                pos = m.end()
            if pos < len(md):
                spans.append((pos, len(md)))
        return spans

    def _chunk_spans(
        self, md: str, target_min: int, target_max: int, hard_limit: int
    ) -> list[tuple[int, int]]:
        """段落区间贪心合并为分块区间；超长单段按句末切分。返回连续字符区间列表。"""
        paras = self._paragraph_spans(md)
        chunks: list[tuple[int, int]] = []
        cur_start: int | None = None
        cur_end: int | None = None

        for s, e in paras:
            if (e - s) > hard_limit:
                if cur_start is not None and cur_end is not None:
                    chunks.append((cur_start, cur_end))
                    cur_start = cur_end = None
                chunks.extend(self._sentence_spans(md, s, e, target_max))
                continue
            if cur_start is None:
                cur_start, cur_end = s, e
            elif (e - cur_start) > target_max:
                chunks.append((cur_start, cur_end))  # type: ignore[arg-type]
                cur_start, cur_end = s, e
            else:
                cur_end = e
        if cur_start is not None and cur_end is not None:
            chunks.append((cur_start, cur_end))
        return chunks

    @staticmethod
    def _sentence_spans(
        md: str, start: int, end: int, target_max: int
    ) -> list[tuple[int, int]]:
        """把超长段落 [start,end) 按句末贪心切为 <= target_max 的连续区间。"""
        enders = [i + 1 for i in range(start, end) if md[i] in _SENTENCE_ENDERS]
        if not enders or enders[-1] != end:
            enders.append(end)
        spans: list[tuple[int, int]] = []
        cs = start
        prev = start
        for cut in enders:
            if (cut - cs) > target_max and prev > cs:
                spans.append((cs, prev))
                cs = prev
            prev = cut
        if cs < end:
            spans.append((cs, end))
        return spans


__all__ = ["IngestManager", "gen_zotero_key", "make_document_id", "LOCAL_LIBRARY_ID"]
