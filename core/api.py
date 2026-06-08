"""业务门面（框架无关，见 api.README.md 与 ../ARCHITECTURE.md §7）。

为 WebUI / CLI / 其它入口提供统一的纯业务调用面：不含 HTTP 概念，只收发普通数据/domain 对象。
`web/` 把请求翻译后委派到这里，再把返回包装成 HTTP 响应。

落地策略：本门面当前直接依赖仓储端口（source_store/kb_reader/sync_targets）。后续版本引入
managers/pipelines（ingest/category/sync/quota）后，对应写操作改为委派到 manager，门面签名不变。
依赖经构造器注入，自身不创建依赖（装配在组合根）。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.api_capabilities import CapabilitiesApiMixin
from core.config import (
    CONSEQUENCE_REBUILD,
    CONSEQUENCE_RESTART,
    api_writable_keys,
    change_consequence,
    structural_keys,
)
from core.domain.models import Collection, DocumentOrigin, SourceDocument, SyncTargetKind
from core.pipelines.retrieval_orchestrator import RetrievalScope

logger = logging.getLogger("KnowledgeRepositoryApi")

SYSTEM_COLLECTION_UNCATEGORIZED = "_uncategorized"
MILVUS_INDEX_MAX_ATTEMPTS = 3
MILVUS_INDEX_RETRY_DELAYS = (0.5, 1.5)


def _build_scope(scope_type: str, scope_key: str, scope_library_id: str) -> RetrievalScope | None:
    """构造检索作用域；scope_type 为空返回 None（无 doc 级硬过滤）。"""
    if not scope_type:
        return None
    return RetrievalScope(
        scope_type=scope_type, scope_key=scope_key, library_id=scope_library_id
    )


def _assert_doc_writable(doc: SourceDocument) -> None:
    """service 层只读强制：Zotero 同步来源禁止用户侧修改/删除（review #7）。"""
    if doc.read_only or doc.origin is DocumentOrigin.ZOTERO:
        raise ReadOnlyError(
            f"文档 {doc.doc_id} 来自 Zotero 同步，处于只读状态；"
            "请在 Zotero 中修改后重新同步，或切换同步模式。"
        )

if TYPE_CHECKING:
    from collections.abc import Callable

    from core.adapters.llm import LLMAdapter
    from core.ask_progress import ProgressStore
    from core.config import Config
    from core.domain.models import DocumentChunk, QuotaUsage
    from core.index_compatibility import IndexCompatibilityStore
    from core.lightrag_core import BuildJob, LightRAGCoreRegistry
    from core.managers.base import BaseCategoryManager, BaseIngestManager, BaseQuotaManager
    from core.metrics import PerformanceTracker
    from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
    from core.pipelines.sync_pipeline import SyncPipeline
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.sync_targets.base import SyncTarget
    from core.repository.vector_store.base import VectorStore


def _get_astrbot_persona_prompt(context: Any) -> str:
    """从 AstrBot context 中动态检索当前的 persona prompt。"""
    if context is None:
        return ""
    try:
        get_active_prompt = getattr(context, "get_active_persona_prompt", None)
        if callable(get_active_prompt):
            return str(get_active_prompt())

        active_persona = getattr(context, "active_persona", None)
        if active_persona is not None:
            prompt = getattr(active_persona, "prompt", None) or getattr(
                active_persona, "system_prompt", None
            )
            if prompt:
                return str(prompt)

        get_active_persona = getattr(context, "get_active_persona", None)
        if callable(get_active_persona):
            persona_obj = get_active_persona()
            if persona_obj:
                prompt = getattr(persona_obj, "prompt", None) or getattr(
                    persona_obj, "system_prompt", None
                )
                if prompt:
                    return str(prompt)

        config_obj = getattr(context, "config", None)
        if config_obj:
            get_cfg = getattr(config_obj, "get", None)
            if callable(get_cfg):
                p = get_cfg("persona") or get_cfg("active_persona")
                if isinstance(p, dict):
                    return str(p.get("prompt") or p.get("system_prompt") or "")
                elif isinstance(p, str):
                    return p
    except Exception as e:
        logger.warning(f"Failed to fetch AstrBot persona dynamically: {e}")
    return ""


class LightRAGNotReadyError(RuntimeError):
    def __init__(self, collection: str, reason: str, *, build_available: bool = False) -> None:
        super().__init__(reason)
        self.collection = collection
        self.reason = reason
        self.build_available = build_available


class HighPrecisionQueryError(RuntimeError):
    def __init__(self, collection: str, reason: str) -> None:
        super().__init__(reason)
        self.collection = collection
        self.reason = reason


class ReadOnlyError(RuntimeError):
    """Zotero 同步来源（只读）被尝试修改/删除时抛出。

    本轮单向同步保证：origin=zotero 的文档/集合/标签在文档系统中只读，
    仅 Zotero Pull 这一特权服务可变更；用户侧 delete/classify/移动一律拒绝。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _extract_raw_doc_text(doc: SourceDocument) -> str | None:
    """读取制品包内的干净 Markdown（clean.md），供 LightRAG 使用（避免双重切块）。

    与 Milvus 路径（预切 chunk）完全分离：LightRAG 拿到连续的 clean.md 文本后由其内部切块器
    决定粒度，且 clean.md 已由 PyMuPDF4LLM 清洗（无可见页码/页眉页脚噪声），实体边界更干净。

    降级策略：制品包缺 markdown_rel_path / clean.md 不存在 → 返回 None，
    由调用方回退到 chunk 拼接路径。不再回退 fitz 手写抽取。
    """
    from pathlib import Path

    rel = getattr(doc, "markdown_rel_path", "") or ""
    if not rel:
        return None
    md_path = Path(doc.file_path).parent / rel
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


class KnowledgeRepositoryApi(CapabilitiesApiMixin):
    """知识库应用的业务门面。依赖经构造器注入，自身不创建依赖（装配在组合根）。

    公共方法面按职责拆分到 mixin（如 CapabilitiesApiMixin 承载能力/依赖管理），
    本类负责 __init__ 装配与文档/检索/图谱/同步核心方法及其共享私有助手。
    """

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        kb_reader: KnowledgeBaseReader,
        sync_targets: dict[SyncTargetKind, SyncTarget] | None = None,
        ingest_manager: BaseIngestManager | None = None,
        category_manager: BaseCategoryManager | None = None,
        quota_manager: BaseQuotaManager | None = None,
        sync_pipeline: SyncPipeline | None = None,
        lightrag_registry: LightRAGCoreRegistry | None = None,
        config: Config | None = None,
        config_persist: Callable[[str, str, object], None] | None = None,
        llm_adapter: LLMAdapter | None = None,
        managed_documents_dir: Path | None = None,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
        metrics: PerformanceTracker | None = None,
        progress_store: ProgressStore | None = None,
        index_compatibility: IndexCompatibilityStore | None = None,
        embedding_fingerprint: str | None = None,
    ) -> None:
        self._source_store = source_store
        self._kb_reader = kb_reader
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._retrieval_orchestrator = retrieval_orchestrator
        self._sync_targets = sync_targets or {}
        self._ingest_manager = ingest_manager
        self._category_manager = category_manager
        self._quota_manager = quota_manager
        self._sync_pipeline = sync_pipeline
        self._lightrag_registry = lightrag_registry
        self._graph_build_jobs: dict[str, BuildJob] = {}
        self._build_pause_events: dict[str, asyncio.Event] = {}
        self._config = config
        self._config_persist = config_persist
        self._llm_adapter = llm_adapter
        self._managed_documents_dir = managed_documents_dir
        self._metrics = metrics
        self._progress_store = progress_store
        self._index_compatibility = index_compatibility
        self._embedding_fingerprint = embedding_fingerprint
        # Zotero 同步管线（组合根在 api 构造后注入，避免回调循环依赖）。
        self._zotero_pipeline: Any | None = None
        self._last_zotero_sync: dict[str, Any] = {}

    def attach_zotero_pipeline(self, pipeline: Any) -> None:
        """组合根注入 ZoteroSyncPipeline（其回调引用本 api 的索引/LRAG 助手）。"""
        self._zotero_pipeline = pipeline

    # ── 集合（分类）────────────────────────────────────────────

    async def list_collections(self) -> list[Collection]:
        """列出全部集合。"""
        return await self._source_store.list_collections()

    async def create_collection(self, name: str, description: str = "") -> None:
        """新建或更新集合（按 name upsert）。v0.3.0 起委派 category_manager。"""
        if self._category_manager:
            await self._category_manager.create_collection(name, description)
        else:
            await self._source_store.upsert_collection(
                Collection(name=name, description=description, created_at=_now())
            )

    async def _ensure_system_collections(self) -> None:
        """确保系统集合（_uncategorized 等）存在，幂等。"""
        await self._source_store.upsert_collection(
            Collection(
                name=SYSTEM_COLLECTION_UNCATEGORIZED,
                description="未归档文档（系统集合，不可删除）",
                created_at=_now(),
            )
        )

    async def delete_collection(self, name: str) -> bool:
        """删除集合。非空集合的文档将迁入 _uncategorized 系统集合。返回 False 表示 name 不存在。

        只读保护：Zotero 同步来源的集合（origin=zotero）禁止用户侧删除，仅允许删除手动创建的集合。
        """
        if name == SYSTEM_COLLECTION_UNCATEGORIZED:
            raise ValueError(f"系统集合 '{SYSTEM_COLLECTION_UNCATEGORIZED}' 不可删除。")
        existing = {c.name: c for c in await self._source_store.list_collections()}
        target = existing.get(name)
        if target is not None and target.origin is DocumentOrigin.ZOTERO:
            raise ReadOnlyError(
                f"集合 '{name}' 来自 Zotero 同步，处于只读状态，不能手动删除。"
            )

        await self._ensure_system_collections()
        moving_docs = await self._source_store.list_documents(collection=name)
        if self._lightrag_registry is not None and self._lightrag_registry.has_workspace(name):
            try:
                await self._lightrag_registry.reset_workspace(name)
            except Exception as exc:
                logger.error("Failed to remove LightRAG workspace %s: %s", name, exc)
        if self._index_compatibility is not None:
            self._index_compatibility.remove_lightrag_collection(name)
        await self._source_store.move_documents_to_collection(name, SYSTEM_COLLECTION_UNCATEGORIZED)
        for doc in moving_docs:
            await self._mark_lightrag_pending(doc.doc_id, SYSTEM_COLLECTION_UNCATEGORIZED)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus":
                if self._milvus_index_is_compatible():
                    try:
                        assert self._vector_store is not None
                        await self._vector_store.delete_collection(name)
                        for doc in moving_docs:
                            await self._sync_milvus_collection_move(
                                doc.doc_id, SYSTEM_COLLECTION_UNCATEGORIZED
                            )
                    except Exception as exc:
                        self._mark_milvus_incompatible(
                            f"Milvus collection delete failed: {exc}"
                        )
                        for doc in moving_docs:
                            await self._mark_document_needs_reindex(doc.doc_id)
                else:
                    for doc in moving_docs:
                        await self._mark_document_needs_reindex(doc.doc_id)

        if self._category_manager:
            return await self._category_manager.delete_collection(name)
        return await self._source_store.delete_collection(name)

    # ── 文档（管理）────────────────────────────────────────────

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        """列出文档，可按集合与单标签过滤（AND）。"""
        return await self._source_store.list_documents(collection=collection, tag=tag)

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        """取单个文档；不存在返回 None。"""
        return await self._source_store.get_document(doc_id)

    async def list_document_chunks(self, doc_id: str) -> list[DocumentChunk]:
        """列出单个文档的本地文本分块，供管理端展示摘要统计。"""
        return await self._source_store.list_chunks(doc_id)

    async def get_zotero_item_meta(self, library_id: str, item_key: str) -> dict[str, Any] | None:
        """返回某 Zotero 条目的归一化引用字段（供文档界面一等展示）。"""
        if not library_id or not item_key:
            return None
        item = await self._source_store.get_zotero_item(library_id, item_key)
        if item is None:
            return None
        return {
            "item_type": item.item_type,
            "creators": item.creators,
            "year": item.year,
            "venue": item.venue,
            "doi": item.doi,
            "url": item.url,
            "abstract": item.abstract,
        }

    async def get_lightrag_index_status(self, doc_id: str) -> dict[str, str] | None:
        return await self._source_store.get_lightrag_index_status(doc_id)

    async def register_document(
        self,
        *,
        title: str,
        file_path: str,
        content_type: str,
        size_bytes: int,
        content_hash: str,
        collection: str,
        tags: list[str] | None = None,
    ) -> str:
        """登记一个原件（生成 doc_id），返回 doc_id。

        预览级登记：仅写入源库元数据。v0.3.0 起本操作委派 ingest_manager（含 PyMuPDF 抽取/分块）。
        """
        auto_index = True
        if self._config:
            auto_index = self._config.get_vector_db_config().auto_index_enabled

        if self._ingest_manager:
            doc_id = await self._ingest_manager.ingest(
                title=title,
                file_path=file_path,
                content_type=content_type,
                size_bytes=size_bytes,
                collection=collection,
                tags=tags,
            )
            # 同步写入 Milvus 向量库（仅在 auto_index_enabled=True 时执行）
            if auto_index and self._config and self._milvus_index_is_compatible():
                vdb = self._config.get_vector_db_config()
                if vdb.backend == "milvus" and self._vector_store and self._embedding_provider:
                    try:
                        await self._index_document_chunks_with_retry(
                            doc_id, collection, context="auto upload"
                        )
                        await self._clear_document_needs_reindex(doc_id)
                    except Exception as exc:
                        logger.error(
                            "Milvus indexing failed after retries for %s: %s",
                            doc_id,
                            exc,
                        )
                        await self._mark_document_needs_reindex(doc_id)
            elif not auto_index or (
                self._config.get_vector_db_config().backend == "milvus"
                and not self._milvus_index_is_compatible()
            ):
                await self._mark_document_needs_reindex(doc_id)
            await self._mark_lightrag_pending(doc_id, collection)
            return doc_id

        doc_id = uuid.uuid4().hex
        await self._source_store.add_document(
            SourceDocument(
                doc_id=doc_id,
                title=title,
                file_path=file_path,
                content_type=content_type,
                size_bytes=size_bytes,
                content_hash=content_hash,
                collection=collection,
                tags=list(tags or []),
                created_at=_now(),
                updated_at=_now(),
            )
        )
        await self._mark_lightrag_pending(doc_id, collection)
        return doc_id

    async def classify_document(
        self, doc_id: str, *, collection: str | None = None, tags: list[str] | None = None
    ) -> bool:
        """调整文档的集合/标签（手动分类）。返回 False 表示 doc_id 不存在。

        仅改动传入的维度：collection/tags 为 None 时该维度保持不变。
        """
        old_doc = await self._source_store.get_document(doc_id)
        if old_doc is None:
            return False
        _assert_doc_writable(old_doc)
        old_collection = old_doc.collection
        if (
            collection is not None
            and collection != old_collection
            and self._lightrag_registry
            and self._lightrag_index_is_compatible(old_collection)
        ):
            try:
                await self._lightrag_registry.delete_doc(old_doc.collection, doc_id)
                logger.info(
                    "LightRAG old workspace delete completed before moving doc %s from %s to %s",
                    doc_id,
                    old_collection,
                    collection,
                )
            except Exception as exc:
                logger.error("LightRAG document move delete failed for %s: %s", doc_id, exc)
                self._mark_lightrag_collection_incompatible(old_collection)

        if self._category_manager:
            updated = await self._category_manager.classify_document(
                doc_id, collection=collection, tags=tags
            )
            if updated and collection is not None and collection != old_collection:
                await self._mark_lightrag_pending(doc_id, collection)
                await self._sync_milvus_collection_move(doc_id, collection)
            return updated

        doc = old_doc
        if doc is None:
            return False
        if collection is not None:
            doc.collection = collection
        if tags is not None:
            doc.tags = tags
        doc.updated_at = _now()
        updated = await self._source_store.update_document(doc)
        if updated and collection is not None and collection != old_collection:
            await self._mark_lightrag_pending(doc_id, collection)
            await self._sync_milvus_collection_move(doc_id, collection)
        return updated

    async def delete_document(self, doc_id: str) -> bool:
        """删除文档、图谱贡献、远端镜像和插件托管原件。

        只读保护：Zotero 同步来源（origin=zotero）禁止用户侧删除（仅 Zotero Pull 可变更）。
        """
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return False
        _assert_doc_writable(doc)

        chunks = await self._source_store.list_chunks(doc_id)
        if self._lightrag_registry is not None and self._lightrag_index_is_compatible(
            doc.collection
        ):
            try:
                await self._lightrag_registry.delete_doc(doc.collection, doc_id)
            except Exception as exc:
                logger.error("LightRAG document delete failed for %s: %s", doc_id, exc)
                self._mark_lightrag_collection_incompatible(doc.collection)
        records = [
            record
            for record in await self._source_store.list_sync_records()
            if record.doc_id == doc_id and record.remote_ref
        ]
        for record in records:
            target = self._sync_targets.get(record.target)
            if target is None:
                continue
            try:
                await target.delete(record.remote_ref or "")
            except Exception as exc:
                logger.warning("Failed to delete remote mirror %s: %s", record.remote_ref, exc)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus" and self._milvus_index_is_compatible():
                chunk_ids = [c.chunk_id for c in chunks]
                if chunk_ids:
                    try:
                        assert self._vector_store is not None
                        await self._vector_store.delete_chunks(chunk_ids)
                    except Exception as exc:
                        logger.error("Milvus document delete failed for %s: %s", doc_id, exc)
                        self._mark_milvus_incompatible(
                            f"Milvus document delete failed: {exc}"
                        )

        deleted = await self._source_store.delete_document(doc_id)
        if deleted:
            self._unlink_managed_document(doc.file_path)
        return deleted

    # ── AstrBot 知识库（调用 / 检索）────────────────────────────

    async def list_kb_collections(self) -> list[str]:
        """列出 AstrBot 知识库中的集合名。"""
        return await self._kb_reader.list_collections()

    async def search_kb(
        self,
        collection: str,
        query: str,
        top_k: int,
        scope_type: str = "",
        scope_key: str = "",
        scope_library_id: str = "",
    ) -> list[DocumentChunk]:
        """在某 AstrBot 知识库集合内检索，可选 item/collection/tag/library 作用域硬过滤。"""
        if self._retrieval_orchestrator is not None:
            scope = _build_scope(scope_type, scope_key, scope_library_id)
            return await self._retrieval_orchestrator.retrieve(collection, query, top_k, scope)
        return await self._kb_reader.search(collection, query, top_k)

    async def get_chunk_context(
        self, doc_id: str, chunk_id: str, window: int = 2
    ) -> dict:
        """返回指定 chunk 及其前后 window 个相邻 chunk（按 ordinal 排序）。"""
        all_chunks = await self._source_store.list_chunks(doc_id)
        all_chunks.sort(key=lambda c: c.ordinal)
        matched_idx = next(
            (i for i, c in enumerate(all_chunks) if c.chunk_id == chunk_id), None
        )
        if matched_idx is None:
            return {"context_before": [], "context_after": [], "matched_chunk_id": chunk_id}
        before = all_chunks[max(0, matched_idx - window):matched_idx]
        after = all_chunks[matched_idx + 1:min(len(all_chunks), matched_idx + window + 1)]
        return {
            "context_before": [
                {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "ordinal": c.ordinal, "text": c.text}
                for c in before
            ],
            "context_after": [
                {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "ordinal": c.ordinal, "text": c.text}
                for c in after
            ],
            "matched_chunk_id": chunk_id,
        }

    async def rebuild_vector_store(self) -> dict[str, Any]:
        """清除并从 SQLite 事实源全量 rebuild 本地向量数据库。"""
        if not self._config or not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

        self._mark_milvus_incompatible("Milvus full rebuild is in progress.")

        # 1. 清空向量库
        await self._vector_store.clear()

        # 2. 从 SQLite 中读取所有的文档
        docs = await self._source_store.list_documents()
        total_chunks = 0
        errors: list[dict[str, str]] = []

        # 3. 逐个文档批量进行 Embedding 计算与 upsert
        for doc in docs:
            try:
                total_chunks += await self._index_document_chunks_with_retry(
                    doc.doc_id, doc.collection, context="full rebuild"
                )
            except Exception as exc:
                logger.error(
                    "Milvus indexing failed after retries for %s during full rebuild: %s",
                    doc.doc_id,
                    exc,
                )
                await self._mark_document_needs_reindex(doc.doc_id)
                errors.append({"doc_id": doc.doc_id, "error": str(exc)})

        if errors:
            reason = f"Milvus rebuild failed for {len(errors)} document(s)."
            self._mark_milvus_incompatible(reason)
            logger.error("Milvus indexing failed after retries: %s", reason)
            return {
                "rebuilt_chunks": total_chunks,
                "failed_docs": len(errors),
                "errors": errors[:5],
            }

        for doc in docs:
            await self._clear_document_needs_reindex(doc.doc_id)

        logger.info("Successfully rebuilt vector store index: %d chunks", total_chunks)
        if self._index_compatibility and self._embedding_fingerprint:
            self._index_compatibility.mark_milvus_compatible(self._embedding_fingerprint)
        return {"rebuilt_chunks": total_chunks, "failed_docs": 0, "errors": []}

    async def rebuild_index_pending(self) -> dict[str, Any]:
        """仅对 needs_reindex=True 的文档进行增量索引重建，完成后清除标记。"""
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError(
                "VectorStore 未配置（请安装 Milvus 并重启插件，或配置 embedding provider）"
            )

        if (
            self._config
            and self._config.get_vector_db_config().backend == "milvus"
            and self._index_compatibility
            and self._embedding_fingerprint
            and not self._index_compatibility.is_milvus_compatible(
                self._embedding_fingerprint
            )
        ):
            docs = await self._source_store.list_documents()
            result = await self.rebuild_vector_store()
            return {"rebuilt_docs": len(docs), **result}

        docs = await self._source_store.list_pending_reindex_documents()
        total_chunks = 0
        rebuilt_docs = 0
        errors: list[dict[str, str]] = []
        logger.info("rebuild_index_pending: %d 个文档待重建", len(docs))

        for doc in docs:
            try:
                total_chunks += await self._index_document_chunks_with_retry(
                    doc.doc_id, doc.collection, context="pending rebuild"
                )
                await self._clear_document_needs_reindex(doc.doc_id)
                rebuilt_docs += 1
            except Exception as exc:
                logger.error(
                    "Milvus indexing failed after retries for %s during pending rebuild: %s",
                    doc.doc_id,
                    exc,
                )
                await self._mark_document_needs_reindex(doc.doc_id)
                errors.append({"doc_id": doc.doc_id, "error": str(exc)})

        logger.info(
            "rebuild_index_pending 完成: %d docs, %d chunks, %d failed",
            rebuilt_docs,
            total_chunks,
            len(errors),
        )
        return {
            "rebuilt_docs": rebuilt_docs,
            "rebuilt_chunks": total_chunks,
            "failed_docs": len(errors),
            "errors": errors[:5],
        }

    async def get_pending_reindex_count(self) -> int:
        """返回待重建索引的文档数量。"""
        docs = await self._source_store.list_pending_reindex_documents()
        return len(docs)

    async def get_chat_history(self, conversation_id: str) -> list[dict]:
        """返回某会话的全部消息记录，按时间升序。"""
        return await self._source_store.get_chat_messages(conversation_id)

    async def clear_chat_history(self, conversation_id: str) -> None:
        """删除某会话的全部消息记录。"""
        await self._source_store.clear_chat_messages(conversation_id)

    async def ask(
        self,
        question: str,
        collection: str | None = None,
        top_k: int = 5,
        conversation_id: str | None = None,
        persona_enabled: bool = False,
        retrieval_mode: str = "default",
        use_english_retrieval: bool = False,
        answer_language: str = "auto",
        scope_type: str = "",
        scope_key: str = "",
        scope_library_id: str = "",
    ) -> dict:
        """Retrieve evidence and generate one final answer."""
        scope = _build_scope(scope_type, scope_key, scope_library_id)
        if retrieval_mode not in {"default", "high_precision", "graph_only"}:
            raise ValueError("retrieval_mode must be 'default', 'high_precision', or 'graph_only'")
        if retrieval_mode in {"high_precision", "graph_only"} and not collection:
            raise ValueError(f"{retrieval_mode} retrieval requires a collection")
        if answer_language not in {"auto", "zh", "en"}:
            answer_language = "auto"

        cid = conversation_id or uuid.uuid4().hex
        ask_start = time.monotonic()

        def _progress(stage: str, pct: int) -> None:
            if self._progress_store is not None:
                self._progress_store.set(cid, stage, pct)

        def _record(op: str, t0: float, **meta: object) -> None:
            if self._metrics is not None:
                self._metrics.record(op, (time.monotonic() - t0) * 1000, meta or None)

        _progress("embed_query", 0)
        t0 = time.monotonic()

        # 翻译召回查询（当 use_english_retrieval=True 时，将用户问题翻译为英语再送入向量检索）
        retrieval_question = question
        if use_english_retrieval and self._llm_adapter is not None:
            try:
                prompt = (
                    "Translate the following query to English for document retrieval."
                    " Output only the English translation, nothing else:\n\n"
                    f"{question}"
                )
                translated = await self._llm_adapter.generate(
                    prompt,
                    system_prompt=(
                        "You are a translation assistant."
                        " Output only the English translation, concisely."
                    ),
                    allow_mock=False,
                )
                if translated and translated.strip():
                    retrieval_question = translated.strip()
                    logger.info(
                        "Query translated for retrieval: %r → %r",
                        question,
                        retrieval_question,
                    )
            except Exception as exc:
                logger.warning("Query translation failed, using original: %s", exc)

        if retrieval_mode in {"high_precision", "graph_only"}:
            readiness = await self.get_lightrag_readiness(collection or "")
            if not readiness["ready"]:
                raise LightRAGNotReadyError(
                    collection or "",
                    readiness["reason"],
                    build_available=readiness["build_available"],
                )

        chunks: list[DocumentChunk] = []
        engines: list[str] = []
        fallback_reason: str | None = None
        milvus_fallback_reason = await self._milvus_retrieval_fallback_reason()

        # graph_only: 跳过向量/词法召回，仅走图谱路径
        if retrieval_mode == "graph_only":
            _progress("lightrag_context", 30)
            try:
                if self._retrieval_orchestrator is None:
                    raise RuntimeError("RetrievalOrchestrator is not configured")
                lightrag_context = await self._retrieval_orchestrator.retrieve_lightrag_context(
                    collection or "", question, scope
                )
                engines.append("lightrag")
            except Exception as exc:
                logger.warning("LightRAG graph_only retrieval failed [%s]: %s", collection, exc)
                raise HighPrecisionQueryError(collection or "", str(exc)) from exc
            _progress("llm_generate", 80)
            t_llm = time.monotonic()
            if self._llm_adapter is not None and lightrag_context:
                if answer_language == "zh":
                    lang_instr = "Answer in Chinese (中文)."
                elif answer_language == "en":
                    lang_instr = "Answer in English."
                else:
                    lang_instr = "Answer in the same language as the question."
                system_prompt = (
                    "You are a helpful academic assistant. "
                    "Answer the question based solely on the provided context. "
                    f"{lang_instr}"
                )
                user_prompt = f"Context:\n\n{lightrag_context}\n\nQuestion: {question}"
                answer = await self._llm_adapter.generate(user_prompt, system_prompt=system_prompt)
            else:
                answer = lightrag_context or "未在知识图谱中找到与该问题相关的内容。"
            _record("llm_generate", t_llm)
            _record("ask_total", ask_start, sources=0)
            _progress("done", 100)
            try:
                await self._source_store.add_chat_message(cid, "user", question)
                await self._source_store.add_chat_message(
                    cid, "assistant", answer, sources=[], retrieval_mode="lightrag_only"
                )
            except Exception as exc:
                logger.warning("Failed to persist chat history: %s", exc)
            return {
                "conversation_id": cid,
                "answer": answer,
                "sources": [],
                "requested_retrieval_mode": retrieval_mode,
                "actual_retrieval_mode": "lightrag_only",
                "retrieval_engines": ["lightrag"],
                "fallback_reason": None,
            }

        _progress("vector_search", 20)
        t_vs = time.monotonic()
        seen_ids: set[str] = set()
        for col in await self._resolve_ask_collections(collection):
            try:
                if self._retrieval_orchestrator is not None:
                    outcome = await self._retrieval_orchestrator.retrieve_with_outcome(
                        col, retrieval_question, top_k, scope
                    )
                    current_chunks = outcome.chunks
                    engines.extend(outcome.engines)
                    fallback_reason = fallback_reason or outcome.fallback_reason
                else:
                    fallback_reason = fallback_reason or milvus_fallback_reason
                    current_chunks = await self._kb_reader.search(col, retrieval_question, top_k)
                    engines.append("astrbot")
            except Exception as exc:
                logger.warning("Ask retrieval failed for collection %s: %s", col, exc)
                fallback_reason = fallback_reason or f"collection_error:{col}"
                continue
            for chunk in current_chunks:
                if chunk.chunk_id not in seen_ids:
                    seen_ids.add(chunk.chunk_id)
                    chunks.append(chunk)
                if len(chunks) >= top_k:
                    break
            if len(chunks) >= top_k:
                break
        _record("vector_search", t_vs, hits=len(chunks))

        _record("embed_query", t0)

        lightrag_context = ""
        if retrieval_mode == "high_precision":
            _progress("lightrag_context", 50)
            try:
                if self._retrieval_orchestrator is None:
                    raise RuntimeError("RetrievalOrchestrator is not configured")
                lightrag_context = await self._retrieval_orchestrator.retrieve_lightrag_context(
                    collection or "", question, scope
                )
                engines.append("lightrag")
            except Exception as exc:
                logger.warning("LightRAG high-precision retrieval failed [%s]: %s", collection, exc)
                raise HighPrecisionQueryError(collection or "", str(exc)) from exc

        _progress("rrf_fusion", 65)

        sources = []
        context_parts = []
        for i, chunk in enumerate(chunks):
            n = i + 1
            doc = await self.get_document(chunk.doc_id)
            title = doc.title if doc else chunk.doc_id
            meta = chunk.metadata or {}
            source = {
                "n": n,
                "doc_id": chunk.doc_id,
                "document_id": chunk.doc_id,
                "title": title,
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "metadata": meta,
                "pages": meta.get("pages", []),
                "origin": doc.origin.value if doc else "local",
            }
            # Zotero provenance：跳转链接 + 归一化引用（Li 2025）。
            if doc and doc.origin is DocumentOrigin.ZOTERO:
                source["zotero_item_uri"] = meta.get("zotero_item_uri", "")
                source["zotero_pdf_uri"] = meta.get("zotero_pdf_uri", "")
                zmeta = await self.get_zotero_item_meta(doc.library_id, doc.zotero_item_key)
                if zmeta:
                    first_author = (zmeta["creators"][0].split(",")[0] if zmeta["creators"] else "")
                    source["citation"] = " ".join(
                        x for x in [first_author, zmeta["year"]] if x
                    ).strip()
            sources.append(source)
            has_page = chunk.metadata and "page_number" in chunk.metadata
            page_info = f" (Page {chunk.metadata['page_number']})" if has_page else ""
            context_parts.append(f"[{n}] {title}{page_info}\n{chunk.text}")

        _progress("llm_generate", 80)
        t_llm = time.monotonic()

        has_evidence = bool(context_parts or lightrag_context)
        if self._llm_adapter is not None and has_evidence:
            if answer_language == "zh":
                lang_instr = "Answer in Chinese (中文)."
            elif answer_language == "en":
                lang_instr = "Answer in English."
            else:
                lang_instr = "Answer in the same language as the question."
            system_prompt = (
                "You are a helpful academic assistant. "
                "Answer the question based solely on the provided context. "
                f"Cite sources using [n] notation (e.g. [1], [2]). "
                f"{lang_instr}"
            )
            if persona_enabled:
                bot_persona = _get_astrbot_persona_prompt(self._llm_adapter._context)
                if bot_persona:
                    system_prompt = f"{bot_persona}\n\n[RAG Constraints]\n{system_prompt}"

            graph_header = (
                f"[LightRAG Context]\n{lightrag_context}\n\n---\n\n"
                if lightrag_context
                else ""
            )
            user_prompt = (
                "Context:\n\n"
                + graph_header
                + "\n\n---\n\n".join(context_parts)
                + f"\n\nQuestion: {question}"
            )
            answer = await self._llm_adapter.generate(user_prompt, system_prompt=system_prompt)
        elif context_parts:
            answer = f"根据知识库检索到 {len(chunks)} 个相关片段：\n\n" + "\n\n".join(
                f"**[{s['n']}] {s['title']}**\n"
                f"{s['text'][:300]}{'…' if len(s['text']) > 300 else ''}"
                for s in sources
            )
        elif lightrag_context:
            answer = lightrag_context
        else:
            answer = "未在知识库中找到与该问题相关的内容。请尝试其他关键词或上传相关文档。"

        _record("llm_generate", t_llm)
        _record("ask_total", ask_start, sources=len(sources))
        _progress("done", 100)

        engines = list(dict.fromkeys(engines))
        if retrieval_mode == "high_precision":
            if "astrbot" in engines:
                actual_mode = "astrbot_lightrag"
            elif "milvus" in engines:
                actual_mode = "milvus_lightrag"
            elif "sqlite_lexical" in engines:
                actual_mode = "lexical_lightrag"
            else:
                actual_mode = "lightrag"
        elif "astrbot" in engines:
            actual_mode = "astrbot_fallback" if fallback_reason else "astrbot"
        elif "milvus" in engines:
            actual_mode = "milvus"
        elif "sqlite_lexical" in engines:
            actual_mode = "sqlite_lexical"
        else:
            actual_mode = "none"

        # 自动持久化聊天记录（source_store 支持时）
        try:
            await self._source_store.add_chat_message(cid, "user", question)
            await self._source_store.add_chat_message(
                cid, "assistant", answer,
                sources=[s for s in sources],
                retrieval_mode=actual_mode,
            )
        except Exception as exc:
            logger.warning("Failed to persist chat history: %s", exc)

        return {
            "conversation_id": cid,
            "answer": answer,
            "sources": sources,
            "requested_retrieval_mode": retrieval_mode,
            "actual_retrieval_mode": actual_mode,
            "retrieval_engines": engines,
            "fallback_reason": fallback_reason,
        }

    async def _resolve_ask_collections(self, collection: str | None) -> list[str]:
        if collection:
            return [collection]
        collections = [item.name for item in await self.list_collections()]
        if not collections:
            collections = await self.list_kb_collections()
        return collections[:5]

    async def get_lightrag_readiness(self, collection: str) -> dict[str, Any]:
        if not collection:
            return {
                "ready": False,
                "reason": "A collection is required.",
                "build_available": False,
            }
        if self._lightrag_registry is None:
            return {
                "ready": False,
                "reason": "LightRAG Core is not enabled or configured.",
                "build_available": False,
            }
        docs = await self._source_store.list_documents(collection=collection)
        if not docs:
            return {
                "ready": False,
                "reason": "The collection has no documents.",
                "build_available": False,
            }
        if not self._lightrag_registry.has_workspace(collection):
            return {
                "ready": False,
                "reason": "LightRAG workspace has not been built.",
                "build_available": True,
            }
        if (
            not self._index_compatibility
            or not self._embedding_fingerprint
            or not self._index_compatibility.is_lightrag_compatible(
                collection, self._embedding_fingerprint
            )
        ):
            return {
                "ready": False,
                "reason": "LightRAG index is incompatible with the active embedding.",
                "build_available": True,
            }
        indexed = 0
        unindexed = 0
        for doc in docs:
            status = await self._source_store.get_lightrag_index_status(doc.doc_id)
            if (
                status is not None
                and status.get("collection") == collection
                and status.get("status") == "indexed"
            ):
                indexed += 1
            else:
                unindexed += 1
        # 至少有一篇文档被成功索引就认为可用；全部失败才阻止
        if indexed == 0 and unindexed > 0:
            return {
                "ready": False,
                "reason": f"No documents have been indexed yet ({unindexed} pending).",
                "build_available": True,
            }
        return {
            "ready": True,
            "reason": "",
            "build_available": False,
            "indexed_docs": indexed,
            "unindexed_docs": unindexed,
        }

    # ── 在线服务（配额）────────────────────────────────────────

    async def list_quota(self) -> list[QuotaUsage]:
        """汇总各已配置同步目标的用量快照（配额仪表盘用）。

        无同步目标时返回空列表。warning 级别由调用方（quota_manager / 前端）按阈值判定。
        """
        usages = []
        for target in self._sync_targets.values():
            usages.append(await target.check_quota())
        return usages

    # ── 预留端口（Reserved）：契约先定，实现随对应版本接入 ──────────
    #
    # 以下方法是「接口先行」在 api 门面的体现：签名/语义现在钉死，前端与 web 路由据此预留入口，
    # 真实实现到对应版本接入（届时本类构造器注入对应 manager，方法体改为委派，签名不变）。
    # 现阶段统一抛 NotImplementedError，web 层捕获后回 501 + available_in，前端展示「将接入」。

    async def sync_documents(self, target: str, doc_ids: list[str] | None = None) -> dict:
        """把文档同步到在线目标（target=r2|notion|all）。doc_ids=None 表示全量。

        Reserved（v0.3.0 R2 / v0.4.0 Notion 接入）：返回逐文档同步结果汇总 + 配额预警。
        """
        if self._sync_pipeline:
            if target == "all":
                results = {
                    kind.value: await self._sync_pipeline.sync(kind, doc_ids)
                    for kind in SyncTargetKind
                }
                return {
                    "status": (
                        "success"
                        if all(result.get("status") == "success" for result in results.values())
                        else "error"
                    ),
                    "targets": results,
                }
            try:
                kind = SyncTargetKind(target)
            except ValueError:
                return {"status": "error", "message": f"未知的同步目标: {target}"}
            return await self._sync_pipeline.sync(kind, doc_ids)

        raise NotImplementedError("sync_documents: available in v0.3.0 (r2) / v0.4.0 (notion)")

    async def initialize_notion_database(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> dict:
        """自动创建 Notion 数据库，并回写生成的 database_id。"""
        if not self._sync_pipeline:
            raise NotImplementedError("initialize_notion_database: available in v0.8.0")

        result = await self._sync_pipeline.initialize_notion_database(
            parent_page_id=parent_page_id,
            database_title=database_title,
        )
        if result.get("status") == "success":
            database_id = result.get("database_id")
            if isinstance(database_id, str) and database_id:
                self._persist_config_value("notion_sync", "database_id", database_id)
            parent = result.get("parent_page_id")
            if isinstance(parent, str) and parent:
                self._persist_config_value("notion_sync", "parent_page_id", parent)
            title = result.get("database_title")
            if isinstance(title, str) and title:
                self._persist_config_value("notion_sync", "database_title", title)
        return result

    async def pull_notion_metadata(self) -> dict:
        """从 Notion 反向拉取 Collection/Tags 元数据。"""
        if self._sync_pipeline:
            return await self._sync_pipeline.pull_notion_metadata()
        raise NotImplementedError("pull_notion_metadata: available in v0.8.0")

    async def get_effective_config(self) -> dict:
        """返回前端可展示的有效配置。"""
        if self._config is None:
            raise NotImplementedError("get_effective_config: available in v0.8.0")
        return self._config.to_public_dict()

    _SECRET_KEYS: frozenset[str] = frozenset(
        {
            "api_key",
            "secret_access_key",
            "access_key_id",
            "password",
        }
    )

    # 可写键与结构键从 config.py 的单一登记表派生（不再手抄，重启/重建后果亦由登记表决定）。
    _CONFIG_UPDATE_KEYS: dict[str, frozenset[str]] = api_writable_keys()
    _STRUCTURAL_KEYS: dict[str, frozenset[str]] = structural_keys()

    async def update_config_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Persist a safe config value without hot-swapping embedding-backed runtime state."""
        logger.info("update_config: %s.%s", section, key)
        if section not in self._CONFIG_UPDATE_KEYS:
            raise ValueError(f"Section '{section}' is write-protected or read-only.")
        if key not in self._CONFIG_UPDATE_KEYS.get(section, frozenset()):
            raise ValueError(f"runtime config key is not allowed: {section}.{key}")
        if key in self._SECRET_KEYS and value:
            raise ValueError(f"'{key}' 为机密字段，必须通过环境变量注入，不可经此接口写入。")
        if key in self._STRUCTURAL_KEYS.get(section, frozenset()):
            raise ValueError(
                f"'{section}.{key}' 为结构性参数，修改后需手动重建索引。"
                "请直接修改插件配置文件并重启插件，而非通过此接口写入。"
            )
        if section == "embedding" and key == "provider" and value not in {"local", "external"}:
            raise ValueError("embedding.provider must be 'local' or 'external'.")
        if section == "vector_db" and key == "backend" and value not in {"milvus", "astr"}:
            raise ValueError("vector_db.backend must be 'milvus' or 'astr'.")

        changed = self._current_config_value(section, key) != value
        self._persist_config_value(section, key, value)
        consequence = change_consequence(section, key)
        rebuild_required = changed and consequence == CONSEQUENCE_REBUILD
        restart_required = changed and consequence in (CONSEQUENCE_RESTART, CONSEQUENCE_REBUILD)
        if rebuild_required:
            await self._invalidate_embedding_indexes(
                f"Configuration changed: {section}.{key}"
            )

        logger.info("update_config ok: %s.%s persisted", section, key)
        return {
            "status": "success",
            "restart_required": restart_required,
            "rebuild_required": rebuild_required,
            "message": (
                "Configuration saved. Restart and rebuild indexes."
                if rebuild_required
                else (
                    "Configuration saved. Restart required."
                    if restart_required
                    else "Configuration saved."
                )
            ),
        }

    async def test_embedding_connection(self, base_url: str, model_name: str) -> dict:
        """临时创建一个 ExternalEmbeddingProvider 并发送测试请求，验证云端 API 可连通性。"""
        from core.repository.embedding.external import ExternalEmbeddingProvider

        provider = ExternalEmbeddingProvider(
            base_url=base_url,
            model_name=model_name,
        )
        try:
            vec = await provider.embed_query("ping")
            return {"status": "ok", "dimension": len(vec), "model": model_name}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    async def get_sync_status(self) -> list[dict]:
        """列出各文档在各目标的同步状态（SyncRecord 视图）。

        Reserved（v0.3.0 起）：现返回空，接入后返回 doc_id/target/status/synced_at。
        """
        records = await self._source_store.list_sync_records()
        return [
            {
                "doc_id": r.doc_id,
                "target": r.target.value,
                "remote_ref": r.remote_ref,
                "status": r.status.value,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
                "message": r.message,
            }
            for r in records
        ]

    async def backup_now(self) -> dict:
        """立即触发一次 R2 全量备份（插件托管原件 + knowledge_repository.db 快照）。

        Reserved（v0.3.0）：返回备份对象数与用量；接近 10GB 时含警告。
        """
        if self._sync_pipeline:
            return await self._sync_pipeline.sync(SyncTargetKind.R2)

        raise NotImplementedError("backup_now: available in v0.3.0")

    async def restore_from_backup(self, snapshot: str | None = None) -> dict:
        """从 R2 备份恢复本地（snapshot=None 取最新）。对应「本地崩溃可恢复」。

        Reserved（v0.3.0）：返回恢复的文档数。
        """
        if self._sync_pipeline:
            return await self._sync_pipeline.restore(SyncTargetKind.R2)

        raise NotImplementedError("restore_from_backup: available in v0.3.0")

    async def estimate_graph_build(self, collection: str | None = None) -> dict:
        """Dry-run LightRAG build estimate. This never calls LLM or Embedding."""
        from core.lightrag_core import estimate_lightrag_build

        col = await self._resolve_collection(collection)
        docs = await self._lightrag_docs_for_build(col)
        chunks_by_doc = {
            doc.doc_id: await self._source_store.list_chunks(doc.doc_id) for doc in docs
        }
        graph_cfg = self._config.get_graph_config() if self._config else None
        max_chars = graph_cfg.max_doc_chars if graph_cfg else 0
        estimate = estimate_lightrag_build(
            docs,
            chunks_by_doc,
            max_doc_chars=max_chars,
            is_local_lightrag_llm=bool(
                graph_cfg and graph_cfg.lightrag_llm_provider == "local"
            ),
            seconds_per_chunk_local=(
                graph_cfg.lightrag_seconds_per_chunk_local if graph_cfg else 90.0
            ),
            seconds_per_chunk_remote=(
                graph_cfg.lightrag_seconds_per_chunk_remote if graph_cfg else 20.0
            ),
        )
        return {"collection": col, **estimate}

    async def build_graph(self, collection: str | None = None, *, confirmed: bool = False) -> dict:
        """Start a manually confirmed LightRAG Core build job."""
        if not confirmed:
            raise ValueError(
                "LightRAG build requires confirmed=true because it triggers LLM indexing"
            )
        if self._lightrag_registry is None:
            raise RuntimeError("LightRAG Core registry is not configured")

        from core.lightrag_core import BuildJob

        col = await self._resolve_collection(collection)
        job_id = uuid.uuid4().hex
        docs = await self._lightrag_docs_for_build(col)
        job = BuildJob(job_id=job_id, collection=col, total_docs=len(docs))
        self._graph_build_jobs[job_id] = job
        ev = asyncio.Event()
        ev.set()
        self._build_pause_events[job_id] = ev
        asyncio.create_task(self._run_lightrag_build_job(job_id))
        return {"job_id": job_id, "status": job.status, "engine": job.engine, "collection": col}

    async def get_graph_build_job(self, job_id: str) -> dict | None:
        job = self._graph_build_jobs.get(job_id)
        return job.to_dict() if job else None

    async def get_active_build_job(self) -> dict | None:
        """返回当前正在运行或暂停的构建任务，没有则返回 None。"""
        for job in self._graph_build_jobs.values():
            if job.status in ("queued", "running") or job.paused:
                return job.to_dict()
        return None

    async def get_build_job_history(self, collection: str | None = None) -> list[dict]:
        """返回构建任务历史（来自持久化表）。"""
        return await self._source_store.list_build_jobs(collection=collection)

    async def pause_build_job(self, job_id: str) -> None:
        """暂停指定构建任务。"""
        job = self._graph_build_jobs.get(job_id)
        if job is None:
            raise KeyError(f"Build job {job_id!r} not found")
        if job.status not in ("queued", "running"):
            raise ValueError(f"Job {job_id!r} is not active (status={job.status!r})")
        job.paused = True
        ev = self._build_pause_events.get(job_id)
        if ev is not None:
            ev.clear()

    async def resume_build_job(self, job_id: str) -> None:
        """继续被暂停的构建任务。"""
        job = self._graph_build_jobs.get(job_id)
        if job is None:
            raise KeyError(f"Build job {job_id!r} not found")
        job.paused = False
        ev = self._build_pause_events.get(job_id)
        if ev is not None:
            ev.set()

    def _build_job_db_snapshot(
        self, job: BuildJob, started_iso: str, finished_iso: str | None = None
    ) -> dict:
        return {
            "job_id": job.job_id, "collection": job.collection,
            "status": job.status, "stage": job.stage,
            "processed_docs": job.processed_docs, "failed_docs": job.failed_docs,
            "total_docs": job.total_docs,
            "processed_chunks": job.processed_chunks, "failed_chunks": job.failed_chunks,
            "total_chunks": job.total_chunks,
            "recent_error": job.recent_error,
            "started_at": started_iso, "finished_at": finished_iso,
        }

    async def _run_lightrag_build_job(self, job_id: str) -> None:
        job = self._graph_build_jobs[job_id]
        assert self._lightrag_registry is not None
        job.status = "running"
        job.stage = "reading_documents"
        started_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        await self._source_store.upsert_build_job(
            self._build_job_db_snapshot(job, started_iso)
        )
        try:
            docs = await self._lightrag_docs_for_build(job.collection)
            job.total_docs = len(docs)
            if (
                self._index_compatibility is not None
                and self._embedding_fingerprint
                and self._lightrag_registry.has_workspace(job.collection)
                and not self._index_compatibility.is_lightrag_compatible(
                    job.collection, self._embedding_fingerprint
                )
            ):
                job.stage = "resetting_workspace"
                await self._lightrag_registry.reset_workspace(job.collection)

            max_chars = 0
            if self._config is not None:
                max_chars = self._config.get_graph_config().max_doc_chars

            prepared: list[tuple[SourceDocument, str, list[str], str]] = []
            for doc in docs:
                text = await self._lightrag_text_for_doc(doc)
                if max_chars > 0 and len(text) > max_chars:
                    text = text[:max_chars]
                if not text.strip():
                    prepared.append((doc, "", [], "lrag_chunks"))
                    continue
                chunk_document = getattr(self._lightrag_registry, "chunk_document", None)
                if callable(chunk_document):
                    chunks, basis = await chunk_document(job.collection, text)
                else:
                    chunks, basis = [text], "estimated_lrag_chunks"
                prepared.append((doc, text, chunks, basis))

            job.total_chunks = sum(len(chunks) for _, text, chunks, _ in prepared if text.strip())
            bases = {basis for _, _, _, basis in prepared}
            job.progress_basis = (
                "lrag_chunks" if bases <= {"lrag_chunks"} else "estimated_lrag_chunks"
            )

            for doc, text, lrag_chunks, _basis in prepared:
                pause_ev = self._build_pause_events.get(job_id)
                if pause_ev is not None:
                    await pause_ev.wait()
                job.stage = "indexing"
                job.current_doc_id = doc.doc_id
                if not text.strip():
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                    continue

                chunk_start = job.processed_chunks
                chunk_target = min(job.total_chunks, chunk_start + len(lrag_chunks))

                def _on_lightrag_llm(event: dict[str, Any]) -> None:
                    if event.get("status") == "ok":
                        if job.total_chunks > 0:
                            job.processed_chunks = min(
                                job.total_chunks, max(job.processed_chunks + 1, chunk_start)
                            )
                            job.current_chunk_index = job.processed_chunks
                    elif event.get("status") == "error":
                        job.failed_chunks += 1

                try:
                    await self._lightrag_registry.insert_document(
                        job.collection,
                        doc.doc_id,
                        text,
                        lrag_chunks=lrag_chunks,
                        progress_callback=_on_lightrag_llm,
                    )
                    if job.processed_chunks < chunk_target:
                        job.processed_chunks = chunk_target
                        job.current_chunk_index = job.processed_chunks
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                except Exception as exc:
                    job.failed_docs += 1
                    remaining = max(0, chunk_target - job.processed_chunks)
                    job.failed_chunks += remaining
                    job.recent_error = str(exc)
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "error", str(exc)
                    )
                    logger.error("LightRAG build failed for doc %s: %s", doc.doc_id, exc)
            job.stage = "done"
            job.status = "success" if job.failed_docs == 0 else "partial_failure"
            if (
                job.status in ("success", "partial_failure")
                and job.processed_docs > 0
                and self._index_compatibility is not None
                and self._embedding_fingerprint
            ):
                self._index_compatibility.mark_lightrag_compatible(
                    job.collection, self._embedding_fingerprint
                )
        except Exception as exc:
            job.stage = "error"
            job.status = "error"
            job.recent_error = str(exc)
            logger.error("LightRAG build job %s failed: %s", job_id, exc)
        finally:
            job.finished_at = time.monotonic()
            job.paused = False
            self._build_pause_events.pop(job_id, None)
            finished_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            await self._source_store.upsert_build_job(
                self._build_job_db_snapshot(job, started_iso, finished_iso)
            )

    async def _lightrag_text_for_doc(self, doc: SourceDocument) -> str:
        raw = _extract_raw_doc_text(doc)
        if raw is not None:
            return raw
        chunks = await self._source_store.list_chunks(doc.doc_id)
        return "\n\n".join(chunk.text for chunk in chunks if chunk.text.strip())

    async def _lightrag_docs_for_build(self, collection: str) -> list[SourceDocument]:
        docs = await self._source_store.list_documents(collection=collection)
        if (
            self._lightrag_registry is None
            or not self._lightrag_registry.has_workspace(collection)
            or not self._lightrag_index_is_compatible(collection)
        ):
            return docs
        pending = []
        for doc in docs:
            status = await self._source_store.get_lightrag_index_status(doc.doc_id)
            if (
                status is None
                or status.get("collection") != collection
                or status.get("status") != "indexed"
            ):
                pending.append(doc)
        return pending

    async def probe_lightrag_core(
        self, collection: str, text: str, doc_id: str, query: str
    ) -> dict:
        """Deployment manual probe for AstrBot terminal verification."""
        if self._lightrag_registry is None:
            raise RuntimeError("LightRAG Core registry is not configured")
        return await self._lightrag_registry.manual_probe(
            collection=collection, text=text, doc_id=doc_id, query=query
        )

    async def query_graph(
        self,
        query: str,
        top_k: int = 5,
        collection: str | None = None,
        debug: bool = False,
    ) -> dict:
        """Run the independent full-answer LightRAG query endpoint."""
        del top_k, debug
        if self._lightrag_registry is None:
            raise NotImplementedError("query_graph requires LightRAG Core")
        col = await self._resolve_collection(collection)
        readiness = await self.get_lightrag_readiness(col)
        if not readiness["ready"]:
            raise RuntimeError(readiness["reason"])
        payload = await self._lightrag_registry.query(col, query)
        payload["status"] = "success"
        payload["query"] = query
        return payload

    async def get_graph(self, collection: str | None = None) -> dict:
        """Export a graph or return a structured not-ready state.

        LightRAG Core 已落地；未启用、依赖缺失或 workspace 未构建都不是 reserved
        功能，而是运行态未就绪状态，供 WebUI 给出准确下一步。
        """
        col = await self._resolve_collection(collection)
        readiness = await self.get_lightrag_readiness(col)
        if not readiness["ready"]:
            return {
                "status": "not_ready",
                "ready": False,
                "collection": col,
                "engine": "lightrag_core",
                "reason": readiness["reason"],
                "build_available": readiness["build_available"],
            }
        assert self._lightrag_registry is not None
        return await self._lightrag_registry.export_graph(col)

    async def _resolve_collection(self, collection: str | None) -> str:
        if collection:
            return collection
        cols = await self.list_collections()
        return cols[0].name if cols else "default"

    # ── 性能指标与进度（供 WebUI 监控面板使用）─────────────────────

    def get_metrics_summary(self) -> dict:
        """返回近期操作延迟聚合统计。无 metrics 时返回空结构。"""
        if self._metrics is not None:
            return self._metrics.summary()
        return {"ops": {}, "total_records": 0}

    def get_ask_progress(self, conversation_id: str) -> dict | None:
        """返回指定对话的召回进度，不存在或已过期时返回 None。"""
        if self._progress_store is not None:
            return self._progress_store.get(conversation_id)
        return None

    async def get_graph_stats(self) -> dict:
        """返回图谱摘要统计（实体数、关系数、涉及集合数）。"""
        if self._lightrag_registry is None:
            return {"entities_count": 0, "relations_count": 0, "collections_covered": 0}
        nodes: set[str] = set()
        edges: set[str] = set()
        collections = 0
        for collection in self._lightrag_registry.existing_collections():
            readiness = await self.get_lightrag_readiness(collection)
            if not readiness["ready"]:
                continue
            try:
                graph = await self._lightrag_registry.export_graph(collection)
                nodes.update(f"{collection}:{item['id']}" for item in graph.get("nodes", []))
                edges.update(f"{collection}:{item['id']}" for item in graph.get("edges", []))
                collections += 1
            except Exception as exc:
                logger.warning("Skipping LightRAG stats for %s: %s", collection, exc)
        return {
            "entities_count": len(nodes),
            "relations_count": len(edges),
            "collections_covered": collections,
        }

    # ── 调试：系统信息 & 文件列表 ─────────────────────────────────

    def get_system_info(self) -> dict:
        """返回后端运行环境基础信息，供调试面板使用。"""
        import sys

        data_dir = (
            self._managed_documents_dir.parent if self._managed_documents_dir else Path("data")
        )
        source_cfg = self._config.get_source_store_config() if self._config else None
        db_file = source_cfg.db_filename if source_cfg else "knowledge_repository.db"
        return {
            "cwd": str(Path.cwd()),
            "data_dir": str(data_dir.resolve()),
            "db_file": db_file,
            "docs_dir": str((data_dir / "library").resolve()),
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        }

    def list_data_files(self, subdir: str = "") -> dict:
        """列出 data_dir 或其子目录的文件，路径严格限制在 data_dir 内。"""
        data_dir = (
            self._managed_documents_dir.parent if self._managed_documents_dir else Path("data")
        ).resolve()

        # 路径安全：拒绝包含 .. 的路径
        if ".." in subdir.replace("\\", "/").split("/"):
            raise ValueError("Path traversal not allowed")

        target = (data_dir / subdir).resolve()
        try:
            target.relative_to(data_dir)
        except ValueError:
            raise ValueError("Path is outside data directory")

        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {subdir!r}")

        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
            stat = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "type": "file" if item.is_file() else "dir",
                    "size_bytes": stat.st_size if item.is_file() else None,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        return {
            "path": str(target.relative_to(data_dir)),
            "entries": entries,
        }

    # ── HuggingFace 本地模型管理 ──────────────────────────────────

    def list_local_embedding_models(self) -> list[dict]:
        """列出 HuggingFace hub 缓存中的本地 embedding 模型目录。"""
        import os

        hf_cache = (
            Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"
        )
        if not hf_cache.is_dir():
            return []
        models = []
        for entry in sorted(hf_cache.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("models--"):
                continue
            raw_name = entry.name[len("models--") :]
            display_name = raw_name.replace("--", "/")
            size_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            try:
                mtime = max(f.stat().st_mtime for f in entry.rglob("*") if f.is_file())
                last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except ValueError:
                last_modified = None
            models.append(
                {
                    "name": display_name,
                    "dir_name": entry.name,
                    "size_bytes": size_bytes,
                    "last_modified": last_modified,
                    "path": str(entry),
                }
            )
        return models

    def delete_local_embedding_model(self, model_name: str) -> dict:
        """删除指定本地 embedding 模型缓存目录（不可逆）。

        model_name 格式为 org/model 或 model，只允许字母/数字/-/_/./ 。
        """
        import os
        import re
        import shutil

        if not re.fullmatch(r"[A-Za-z0-9\-_./]+", model_name) or ".." in model_name:
            raise ValueError("Invalid model name")
        hf_cache = (
            Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"
        )
        dir_name = "models--" + model_name.replace("/", "--")
        target = hf_cache / dir_name
        if not target.exists():
            raise FileNotFoundError(f"Model not found: {model_name!r}")
        target.relative_to(hf_cache)  # 二次路径安全确认
        shutil.rmtree(target)
        return {"deleted": model_name}

    def _persist_config_value(self, section: str, key: str, value: object) -> None:
        if self._config is not None:
            self._config.set_value(section, key, value)
        if self._config_persist is not None:
            self._config_persist(section, key, value)

    def _current_config_value(self, section: str, key: str) -> object | None:
        if self._config is None:
            return None
        getters = {
            "vector_db": self._config.get_vector_db_config,
            "embedding": self._config.get_embedding_config,
            "ask": self._config.get_ask_agent_config,
            "graph": self._config.get_graph_config,
            "r2_sync": self._config.get_r2_sync_config,
            "notion_sync": self._config.get_notion_sync_config,
            "source_store": self._config.get_source_store_config,
        }
        getter = getters.get(section)
        return getattr(getter(), key, None) if getter else None

    def _milvus_index_is_compatible(self) -> bool:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return False
        return bool(
            self._vector_store
            and self._embedding_provider
            and self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_milvus_compatible(self._embedding_fingerprint)
        )

    async def _milvus_retrieval_fallback_reason(self) -> str | None:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return None
        pending_count = len(await self._source_store.list_pending_reindex_documents())
        if not self._milvus_index_is_compatible():
            reason = ""
            if self._index_compatibility is not None:
                reason = self._index_compatibility.reason("milvus")
            return reason or "Milvus index is not compatible; rebuild index required."
        if pending_count:
            return f"{pending_count} document(s) still require Milvus reindex."
        return None

    def _lightrag_index_is_compatible(self, collection: str) -> bool:
        return bool(
            self._lightrag_registry
            and self._index_compatibility
            and self._embedding_fingerprint
            and self._index_compatibility.is_lightrag_compatible(
                collection, self._embedding_fingerprint
            )
        )

    def _mark_milvus_incompatible(self, reason: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.mark_milvus_incompatible(reason)

    def _mark_lightrag_collection_incompatible(self, collection: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.remove_lightrag_collection(collection)

    async def _mark_document_needs_reindex(self, doc_id: str) -> None:
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return
        doc.needs_reindex = True
        await self._source_store.update_document(doc)

    async def _clear_document_needs_reindex(self, doc_id: str) -> None:
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return
        if doc.needs_reindex:
            doc.needs_reindex = False
            await self._source_store.update_document(doc)

    async def _index_document_chunks_with_retry(
        self, doc_id: str, collection: str, *, context: str
    ) -> int:
        chunks = await self._source_store.list_chunks(doc_id)
        if not chunks:
            return 0
        return await self._upsert_milvus_chunks_with_retry(
            chunks,
            collection=collection,
            context=f"{context}: doc={doc_id}",
        )

    async def _upsert_milvus_chunks_with_retry(
        self, chunks: list[DocumentChunk], *, collection: str, context: str
    ) -> int:
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

        doc_ids = sorted({chunk.doc_id for chunk in chunks})
        if hasattr(self._vector_store, "set_doc_collection_mapping"):
            for doc_id in doc_ids:
                self._vector_store.set_doc_collection_mapping(doc_id, collection)

        last_exc: Exception | None = None
        for attempt in range(1, MILVUS_INDEX_MAX_ATTEMPTS + 1):
            try:
                embeddings = await self._embedding_provider.embed_documents(
                    [chunk.text for chunk in chunks]
                )
                await self._vector_store.upsert_chunks(chunks, embeddings)
                if attempt > 1:
                    logger.info(
                        "Milvus indexing retry succeeded on attempt %d/%d: %s",
                        attempt,
                        MILVUS_INDEX_MAX_ATTEMPTS,
                        context,
                    )
                return len(chunks)
            except Exception as exc:
                last_exc = exc
                if attempt >= MILVUS_INDEX_MAX_ATTEMPTS:
                    break
                delay = MILVUS_INDEX_RETRY_DELAYS[
                    min(attempt - 1, len(MILVUS_INDEX_RETRY_DELAYS) - 1)
                ]
                logger.warning(
                    "Milvus indexing attempt %d/%d failed for %s: %s; retrying in %.1fs",
                    attempt,
                    MILVUS_INDEX_MAX_ATTEMPTS,
                    context,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"Milvus indexing failed after retries ({context}): {last_exc}")

    async def _mark_lightrag_pending(self, doc_id: str, collection: str) -> None:
        await self._source_store.set_lightrag_index_status(doc_id, collection, "pending")

    # ── Zotero 同步副作用回调（供 ZoteroSyncPipeline 注入）──────────

    async def _index_document(self, doc_id: str, collection: str) -> None:
        """把某文档的 chunk 嵌入并写入 Milvus（与 register_document 自动索引同语义）。"""
        if not (self._config and self._milvus_index_is_compatible()):
            await self._mark_document_needs_reindex(doc_id)
            return
        vdb = self._config.get_vector_db_config()
        if vdb.backend != "milvus" or not self._vector_store or not self._embedding_provider:
            return
        try:
            await self._index_document_chunks_with_retry(doc_id, collection, context="zotero")
            await self._clear_document_needs_reindex(doc_id)
        except Exception as exc:
            logger.error("Milvus indexing failed after retries for Zotero doc %s: %s", doc_id, exc)
            await self._mark_document_needs_reindex(doc_id)

    async def _remove_document_index(self, doc_id: str) -> None:
        """从 Milvus 移除某文档的全部 chunk（strict 脱管 / conservative 删除时调用）。"""
        if not self._vector_store:
            return
        try:
            chunks = await self._source_store.list_chunks(doc_id)
            ids = [c.chunk_id for c in chunks]
            if ids:
                await self._vector_store.delete_chunks(ids)
        except Exception as exc:
            logger.warning("Zotero remove index failed for %s: %s", doc_id, exc)

    async def _lightrag_cleanup(self, doc_id: str, collection: str) -> None:
        """删除某文档在 LightRAG workspace 的贡献（conservative 硬删除时调用）。"""
        if self._lightrag_registry is None:
            return
        try:
            await self._lightrag_registry.delete_doc(collection, doc_id)
        except Exception as exc:
            logger.warning("Zotero LRAG cleanup failed for %s: %s", doc_id, exc)

    # ── Zotero 同步公开门面 ──────────────────────────────────────

    async def get_zotero_config(self) -> dict[str, Any]:
        """返回 Zotero 同步配置 + 连接/数据目录/linked 探针状态（供设置与 sync 页）。"""
        from core.adapters.zotero import local_api
        from core.config import ZOTERO_STORAGE_LINKED

        if self._config is None:
            return {"enabled": False, "available": False}
        cfg = self._config.get_zotero_sync_config()
        out: dict[str, Any] = {
            "enabled": cfg.enabled,
            "zotero_data_dir": cfg.zotero_data_dir,
            "api_port": cfg.api_port,
            "storage_mode": cfg.storage_mode,
            "linked_root": cfg.linked_root,
            "sync_mode": cfg.sync_mode,
            "auto_sync_enabled": cfg.auto_sync_enabled,
            "auto_sync_interval_sec": cfg.auto_sync_interval_sec,
            "connection": local_api.probe_connection(cfg.api_port),
        }
        if self._zotero_pipeline is not None:
            out["availability"] = self._zotero_pipeline.is_available()
        if cfg.storage_mode == ZOTERO_STORAGE_LINKED:
            from core.adapters.zotero import paths as zpaths

            out["linked_probe"] = zpaths.probe_linked_root(cfg.linked_root)
        return out

    async def sync_zotero_pull(self, incremental: bool = True) -> dict[str, Any]:
        """执行一次 Zotero Pull；strict 模式变化后触发 Milvus 全量重建。"""
        if self._zotero_pipeline is None:
            return {"status": "error", "message": "Zotero 同步未启用或未装配"}
        result = await self._zotero_pipeline.pull(incremental=incremental)
        payload = result.to_dict()
        if result.needs_milvus_rebuild:
            try:
                payload["milvus_rebuild"] = await self.rebuild_vector_store()
            except Exception as exc:
                logger.warning("Zotero strict rebuild failed: %s", exc)
                payload["milvus_rebuild_error"] = str(exc)
        self._last_zotero_sync = payload
        return payload

    async def get_zotero_sync_status(self) -> dict[str, Any]:
        """返回上一次 Zotero Pull 的结果摘要（无则空）。"""
        return dict(self._last_zotero_sync)

    async def _sync_milvus_collection_move(self, doc_id: str, collection: str) -> None:
        if not self._config or self._config.get_vector_db_config().backend != "milvus":
            return
        chunks = await self._source_store.list_chunks(doc_id)
        if not chunks:
            return
        if not self._milvus_index_is_compatible():
            await self._mark_document_needs_reindex(doc_id)
            return
        assert self._vector_store is not None
        assert self._embedding_provider is not None
        try:
            await self._vector_store.delete_chunks([chunk.chunk_id for chunk in chunks])
            await self._upsert_milvus_chunks_with_retry(
                chunks,
                collection=collection,
                context=f"collection move: doc={doc_id}",
            )
            await self._clear_document_needs_reindex(doc_id)
        except Exception as exc:
            logger.error("Milvus collection move sync failed for %s: %s", doc_id, exc)
            await self._mark_document_needs_reindex(doc_id)
            self._mark_milvus_incompatible(f"Milvus collection move failed: {exc}")

    async def _invalidate_embedding_indexes(self, reason: str) -> None:
        if self._index_compatibility:
            self._index_compatibility.mark_all_incompatible(reason)
        for doc in await self._source_store.list_documents():
            doc.needs_reindex = True
            await self._source_store.update_document(doc)
            await self._mark_lightrag_pending(doc.doc_id, doc.collection)
        if self._config:
            self._config.add_diagnostic(
                "Embedding configuration changed; restart and rebuild Milvus/LightRAG indexes."
            )

    def _unlink_managed_document(self, file_path: str) -> None:
        """删除制品包：移除 library/<document_id>/ 整个目录（含 clean.md/pages.json/meta.json）。

        安全边界：仅当原件路径落在 managed 根（library/）内才删除；删除其所在制品包目录，
        而非仅删 original.pdf，避免残留派生制品。
        """
        if self._managed_documents_dir is None:
            return
        import shutil

        managed_root = self._managed_documents_dir.resolve()
        try:
            path = Path(file_path).resolve()
            path.relative_to(managed_root)
            bundle_dir = path.parent
            # 仅当 parent 是 managed 根下的子目录（制品包目录）时整体删除。
            if bundle_dir != managed_root and bundle_dir.parent == managed_root:
                shutil.rmtree(bundle_dir, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to remove managed document %s: %s", file_path, exc)


def _now() -> datetime:
    """统一的 UTC aware 时间戳。"""
    return datetime.now(timezone.utc)


__all__ = ["HighPrecisionQueryError", "KnowledgeRepositoryApi", "LightRAGNotReadyError"]
