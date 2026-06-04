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

from core.domain.models import Collection, SourceDocument, SyncTargetKind

logger = logging.getLogger("KnowledgeRepositoryApi")

SYSTEM_COLLECTION_UNCATEGORIZED = "_uncategorized"

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


class KnowledgeRepositoryApi:
    """知识库应用的业务门面。依赖经构造器注入，自身不创建依赖（装配在组合根）。"""

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
        self._config = config
        self._config_persist = config_persist
        self._llm_adapter = llm_adapter
        self._managed_documents_dir = managed_documents_dir
        self._metrics = metrics
        self._progress_store = progress_store
        self._index_compatibility = index_compatibility
        self._embedding_fingerprint = embedding_fingerprint

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
        """删除集合。非空集合的文档将迁入 _uncategorized 系统集合。返回 False 表示 name 不存在。"""
        if name == SYSTEM_COLLECTION_UNCATEGORIZED:
            raise ValueError(f"系统集合 '{SYSTEM_COLLECTION_UNCATEGORIZED}' 不可删除。")

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
                        if hasattr(self._vector_store, "set_doc_collection_mapping"):
                            self._vector_store.set_doc_collection_mapping(doc_id, collection)
                        chunks = await self._source_store.list_chunks(doc_id)
                        if chunks:
                            texts = [c.text for c in chunks]
                            embeddings = await self._embedding_provider.embed_documents(texts)
                            await self._vector_store.upsert_chunks(chunks, embeddings)
                    except Exception as exc:
                        logger.error("Milvus indexing failed for %s: %s", doc_id, exc)
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
        """删除文档、图谱贡献、远端镜像和插件托管原件。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return False

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

    async def search_kb(self, collection: str, query: str, top_k: int) -> list[DocumentChunk]:
        """在某 AstrBot 知识库集合内检索。"""
        if self._retrieval_orchestrator is not None:
            return await self._retrieval_orchestrator.retrieve(collection, query, top_k)
        return await self._kb_reader.search(collection, query, top_k)

    async def rebuild_vector_store(self) -> dict[str, int]:
        """清除并从 SQLite 事实源全量 rebuild 本地向量数据库。"""
        if not self._config or not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

        self._mark_milvus_incompatible("Milvus full rebuild is in progress.")

        # 1. 清空向量库
        await self._vector_store.clear()

        # 2. 从 SQLite 中读取所有的文档
        docs = await self._source_store.list_documents()
        total_chunks = 0

        # 3. 逐个文档批量进行 Embedding 计算与 upsert
        for doc in docs:
            chunks = await self._source_store.list_chunks(doc.doc_id)
            if chunks:
                if hasattr(self._vector_store, "set_doc_collection_mapping"):
                    self._vector_store.set_doc_collection_mapping(doc.doc_id, doc.collection)
                texts = [c.text for c in chunks]
                embeddings = await self._embedding_provider.embed_documents(texts)
                await self._vector_store.upsert_chunks(chunks, embeddings)
                total_chunks += len(chunks)

        for doc in docs:
            if doc.needs_reindex:
                doc.needs_reindex = False
                await self._source_store.update_document(doc)

        logger.info("Successfully rebuilt vector store index: %d chunks", total_chunks)
        if self._index_compatibility and self._embedding_fingerprint:
            self._index_compatibility.mark_milvus_compatible(self._embedding_fingerprint)
        return {"rebuilt_chunks": total_chunks}

    async def rebuild_index_pending(self) -> dict[str, int]:
        """仅对 needs_reindex=True 的文档进行增量索引重建，完成后清除标记。"""
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

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

        for doc in docs:
            chunks = await self._source_store.list_chunks(doc.doc_id)
            if chunks:
                if hasattr(self._vector_store, "set_doc_collection_mapping"):
                    self._vector_store.set_doc_collection_mapping(doc.doc_id, doc.collection)
                texts = [c.text for c in chunks]
                embeddings = await self._embedding_provider.embed_documents(texts)
                await self._vector_store.upsert_chunks(chunks, embeddings)
                total_chunks += len(chunks)
            doc.needs_reindex = False
            await self._source_store.update_document(doc)

        logger.info("Rebuilt pending index: %d docs, %d chunks", len(docs), total_chunks)
        return {"rebuilt_docs": len(docs), "rebuilt_chunks": total_chunks}

    async def get_pending_reindex_count(self) -> int:
        """返回待重建索引的文档数量。"""
        docs = await self._source_store.list_pending_reindex_documents()
        return len(docs)

    async def ask(
        self,
        question: str,
        collection: str | None = None,
        top_k: int = 5,
        conversation_id: str | None = None,
        persona_enabled: bool = False,
        retrieval_mode: str = "default",
    ) -> dict:
        """Retrieve evidence and generate one final answer."""
        if retrieval_mode not in {"default", "high_precision"}:
            raise ValueError("retrieval_mode must be 'default' or 'high_precision'")
        if retrieval_mode == "high_precision" and not collection:
            raise ValueError("high_precision retrieval requires a collection")

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

        if retrieval_mode == "high_precision":
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
        _progress("vector_search", 20)
        t_vs = time.monotonic()
        seen_ids: set[str] = set()
        for col in await self._resolve_ask_collections(collection):
            try:
                if self._retrieval_orchestrator is not None:
                    outcome = await self._retrieval_orchestrator.retrieve_with_outcome(
                        col, question, top_k
                    )
                    current_chunks = outcome.chunks
                    engines.extend(outcome.engines)
                    fallback_reason = fallback_reason or outcome.fallback_reason
                else:
                    current_chunks = await self._kb_reader.search(col, question, top_k)
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
                    collection or "", question
                )
                engines.append("lightrag")
            except Exception as exc:
                raise HighPrecisionQueryError(collection or "", str(exc)) from exc

        _progress("rrf_fusion", 65)

        sources = []
        context_parts = []
        for i, chunk in enumerate(chunks):
            n = i + 1
            doc = await self.get_document(chunk.doc_id)
            title = doc.title if doc else chunk.doc_id
            sources.append(
                {
                    "n": n,
                    "doc_id": chunk.doc_id,
                    "title": title,
                    "chunk_id": chunk.chunk_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "metadata": chunk.metadata,
                }
            )
            has_page = chunk.metadata and "page_number" in chunk.metadata
            page_info = f" (Page {chunk.metadata['page_number']})" if has_page else ""
            context_parts.append(f"[{n}] {title}{page_info}\n{chunk.text}")

        _progress("llm_generate", 80)
        t_llm = time.monotonic()

        has_evidence = bool(context_parts or lightrag_context)
        if self._llm_adapter is not None and has_evidence:
            system_prompt = (
                "You are a helpful academic assistant. "
                "Answer the question based solely on the provided context. "
                "Cite sources using [n] notation (e.g. [1], [2]). "
                "Answer in the same language as the question."
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
        invalid = 0
        for doc in docs:
            status = await self._source_store.get_lightrag_index_status(doc.doc_id)
            if (
                status is None
                or status.get("collection") != collection
                or status.get("status") != "indexed"
            ):
                invalid += 1
        if invalid:
            return {
                "ready": False,
                "reason": f"{invalid} document(s) require LightRAG indexing.",
                "build_available": True,
            }
        return {"ready": True, "reason": "", "build_available": False}

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

    # 修改这些字段需要重建索引，运行时直接写入会静默破坏已有数据
    _STRUCTURAL_KEYS: dict[str, frozenset[str]] = {
        "graph": frozenset({"working_dir"}),
        "vector_db": frozenset({"db_filename"}),
    }
    _CONFIG_UPDATE_KEYS: dict[str, frozenset[str]] = {
        "vector_db": frozenset({"backend", "auto_index_enabled"}),
        "embedding": frozenset({"provider", "model", "base_url", "max_token_size"}),
        "ask": frozenset({"conversation_enhancement_mode"}),
        "graph": frozenset(
            {"enabled", "query_mode", "llm_max_async", "embedding_max_async"}
        ),
    }
    _EMBEDDING_INDEX_KEYS = frozenset({"provider", "model", "base_url"})

    async def update_config_value(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Persist a safe config value without hot-swapping embedding-backed runtime state."""
        logger.info("update_config: %s.%s", section, key)
        if section not in ("vector_db", "embedding", "ask", "graph"):
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
        restart_required = changed and section in {"embedding", "vector_db", "graph"}
        rebuild_required = (
            changed and section == "embedding" and key in self._EMBEDDING_INDEX_KEYS
        )
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
        estimate = estimate_lightrag_build(docs, chunks_by_doc)
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
        asyncio.create_task(self._run_lightrag_build_job(job_id))
        return {"job_id": job_id, "status": job.status, "engine": job.engine, "collection": col}

    async def get_graph_build_job(self, job_id: str) -> dict | None:
        job = self._graph_build_jobs.get(job_id)
        return job.to_dict() if job else None

    async def _run_lightrag_build_job(self, job_id: str) -> None:
        job = self._graph_build_jobs[job_id]
        assert self._lightrag_registry is not None
        job.status = "running"
        job.stage = "reading_documents"
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
            for doc in docs:
                job.stage = "indexing"
                chunks = await self._source_store.list_chunks(doc.doc_id)
                text = "\n\n".join(chunk.text for chunk in chunks if chunk.text.strip())
                if not text.strip():
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                    continue
                try:
                    await self._lightrag_registry.insert_document(job.collection, doc.doc_id, text)
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "indexed"
                    )
                    job.processed_docs += 1
                except Exception as exc:
                    job.failed_docs += 1
                    job.recent_error = str(exc)
                    await self._source_store.set_lightrag_index_status(
                        doc.doc_id, job.collection, "error", str(exc)
                    )
                    logger.error("LightRAG build failed for doc %s: %s", doc.doc_id, exc)
            job.stage = "done"
            job.status = "success" if job.failed_docs == 0 else "partial_failure"
            if (
                job.status == "success"
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
            job.finished_at = time.time()

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
        """Export a valid existing LightRAG workspace for visualization."""
        if self._lightrag_registry is None:
            raise NotImplementedError("get_graph requires LightRAG Core")
        col = await self._resolve_collection(collection)
        readiness = await self.get_lightrag_readiness(col)
        if not readiness["ready"]:
            raise RuntimeError(readiness["reason"])
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
            "docs_dir": str((data_dir / "documents").resolve()),
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

    async def _mark_lightrag_pending(self, doc_id: str, collection: str) -> None:
        await self._source_store.set_lightrag_index_status(doc_id, collection, "pending")

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
            if hasattr(self._vector_store, "set_doc_collection_mapping"):
                self._vector_store.set_doc_collection_mapping(doc_id, collection)
            embeddings = await self._embedding_provider.embed_documents(
                [chunk.text for chunk in chunks]
            )
            await self._vector_store.upsert_chunks(chunks, embeddings)
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
        if self._managed_documents_dir is None:
            return
        try:
            path = Path(file_path).resolve()
            path.relative_to(self._managed_documents_dir.resolve())
            path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to remove managed document %s: %s", file_path, exc)


def _now() -> datetime:
    """统一的 UTC aware 时间戳。"""
    return datetime.now(timezone.utc)


__all__ = ["HighPrecisionQueryError", "KnowledgeRepositoryApi", "LightRAGNotReadyError"]
