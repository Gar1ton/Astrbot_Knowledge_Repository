"""业务门面（框架无关，见 api.README.md 与 ../ARCHITECTURE.md §7）。

为 WebUI / CLI / 其它入口提供统一的纯业务调用面：不含 HTTP 概念，只收发普通数据/domain 对象。
`web/` 把请求翻译后委派到这里，再把返回包装成 HTTP 响应。

落地策略：本门面当前直接依赖仓储端口（source_store/kb_reader/sync_targets）。后续版本引入
managers/pipelines（ingest/category/sync/quota）后，对应写操作改为委派到 manager，门面签名不变。
依赖经构造器注入，自身不创建依赖（装配在组合根）。
"""
from __future__ import annotations

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
    from core.managers.base import BaseCategoryManager, BaseIngestManager, BaseQuotaManager
    from core.metrics import PerformanceTracker
    from core.pipelines.graph_build_pipeline import GraphBuildPipeline
    from core.pipelines.graph_search_pipeline import GraphSearchPipeline
    from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
    from core.pipelines.sync_pipeline import SyncPipeline
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.graph_store.base import GraphStore
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
        graph_store: GraphStore | None = None,
        graph_build_pipeline: GraphBuildPipeline | None = None,
        graph_search_pipeline: GraphSearchPipeline | None = None,
        config: Config | None = None,
        config_persist: Callable[[str, str, object], None] | None = None,
        llm_adapter: LLMAdapter | None = None,
        managed_documents_dir: Path | None = None,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        retrieval_orchestrator: RetrievalOrchestrator | None = None,
        metrics: PerformanceTracker | None = None,
        progress_store: ProgressStore | None = None,
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
        self._graph_store = graph_store
        self._graph_build_pipeline = graph_build_pipeline
        self._graph_search_pipeline = graph_search_pipeline
        self._config = config
        self._config_persist = config_persist
        self._llm_adapter = llm_adapter
        self._managed_documents_dir = managed_documents_dir
        self._metrics = metrics
        self._progress_store = progress_store

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
        await self._source_store.move_documents_to_collection(name, SYSTEM_COLLECTION_UNCATEGORIZED)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus" and self._vector_store:
                await self._vector_store.delete_collection(name)

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
            if auto_index and self._config:
                vdb = self._config.get_vector_db_config()
                if vdb.backend == "milvus" and self._vector_store and self._embedding_provider:
                    if hasattr(self._vector_store, "set_doc_collection_mapping"):
                        self._vector_store.set_doc_collection_mapping(doc_id, collection)
                    chunks = await self._source_store.list_chunks(doc_id)
                    if chunks:
                        texts = [c.text for c in chunks]
                        embeddings = await self._embedding_provider.embed_documents(texts)
                        await self._vector_store.upsert_chunks(chunks, embeddings)
            elif not auto_index:
                doc = await self._source_store.get_document(doc_id)
                if doc:
                    doc.needs_reindex = True
                    await self._source_store.update_document(doc)
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
        return doc_id

    async def classify_document(
        self, doc_id: str, *, collection: str | None = None, tags: list[str] | None = None
    ) -> bool:
        """调整文档的集合/标签（手动分类）。返回 False 表示 doc_id 不存在。

        仅改动传入的维度：collection/tags 为 None 时该维度保持不变。
        """
        if self._category_manager:
            return await self._category_manager.classify_document(
                doc_id, collection=collection, tags=tags
            )

        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return False
        if collection is not None:
            doc.collection = collection
        if tags is not None:
            doc.tags = tags
        doc.updated_at = _now()
        return await self._source_store.update_document(doc)

    async def delete_document(self, doc_id: str) -> bool:
        """删除文档、图谱贡献、远端镜像和插件托管原件。"""
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            return False

        chunks = await self._source_store.list_chunks(doc_id)
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

        if self._graph_store is not None:
            for chunk in chunks:
                await self._graph_store.delete_by_chunk(chunk.chunk_id)

        if self._config:
            vdb = self._config.get_vector_db_config()
            if vdb.backend == "milvus" and self._vector_store:
                chunk_ids = [c.chunk_id for c in chunks]
                if chunk_ids:
                    await self._vector_store.delete_chunks(chunk_ids)

        deleted = await self._source_store.delete_document(doc_id)
        if deleted:
            self._unlink_managed_document(doc.file_path)
        return deleted

    # ── AstrBot 知识库（调用 / 检索）────────────────────────────

    async def list_kb_collections(self) -> list[str]:
        """列出 AstrBot 知识库中的集合名。"""
        return await self._kb_reader.list_collections()

    async def search_kb(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        """在某 AstrBot 知识库集合内检索。"""
        if self._retrieval_orchestrator is not None:
            return await self._retrieval_orchestrator.retrieve(collection, query, top_k)
        return await self._kb_reader.search(collection, query, top_k)

    async def rebuild_vector_store(self) -> dict[str, int]:
        """清除并从 SQLite 事实源全量 rebuild 本地向量数据库。"""
        if not self._config or not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

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

        logger.info("Successfully rebuilt vector store index: %d chunks", total_chunks)
        return {"rebuilt_chunks": total_chunks}

    async def rebuild_index_pending(self) -> dict[str, int]:
        """仅对 needs_reindex=True 的文档进行增量索引重建，完成后清除标记。"""
        if not self._vector_store or not self._embedding_provider:
            raise RuntimeError("VectorStore or EmbeddingProvider is not configured.")

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
            doc.updated_at = _now()
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
    ) -> dict:
        """基于知识库检索 + LLM 生成答案，返回 answer + sources（Ask Agent 端口）。"""
        cid = conversation_id or uuid.uuid4().hex
        ask_start = time.monotonic()

        def _progress(stage: str, pct: int) -> None:
            if self._progress_store is not None:
                self._progress_store.set(cid, stage, pct)

        def _record(op: str, t0: float, **meta: object) -> None:
            if self._metrics is not None:
                self._metrics.record(op, (time.monotonic() - t0) * 1000, meta or None)

        # 阶段 1：向量嵌入 / 准备检索
        _progress("embed_query", 0)
        t0 = time.monotonic()

        # 1. 检索相关 chunks
        chunks: list[DocumentChunk] = []
        if collection:
            _progress("vector_search", 20)
            t_vs = time.monotonic()
            chunks = await self.search_kb(collection, question, top_k)
            _record("vector_search", t_vs, hits=len(chunks))
        else:
            # 优先从本地源库获取集合列表，如果没有再回退到 AstrBot 知识库列表
            cols = await self.list_collections()
            all_cols = [c.name for c in cols]
            if not all_cols:
                all_cols = await self.list_kb_collections()
            _progress("vector_search", 20)
            t_vs = time.monotonic()
            seen_ids: set[str] = set()
            for col in all_cols[:5]:
                for ch in await self.search_kb(col, question, top_k):
                    if ch.chunk_id not in seen_ids:
                        seen_ids.add(ch.chunk_id)
                        chunks.append(ch)
                    if len(chunks) >= top_k:
                        break
                if len(chunks) >= top_k:
                    break
            _record("vector_search", t_vs, hits=len(chunks))

        _record("embed_query", t0)

        # 阶段 2：图谱扩展（此处已在 retrieval_orchestrator 内完成，记录占位进度）
        _progress("graph_expand", 50)

        # 阶段 3：RRF 融合（同上）
        _progress("rrf_fusion", 65)

        # 2. 构造来源列表 + LLM 上下文
        sources = []
        context_parts = []
        for i, chunk in enumerate(chunks):
            n = i + 1
            doc = await self.get_document(chunk.doc_id)
            title = doc.title if doc else chunk.doc_id
            sources.append({
                "n": n,
                "doc_id": chunk.doc_id,
                "title": title,
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "metadata": chunk.metadata,
            })
            has_page = chunk.metadata and "page_number" in chunk.metadata
            page_info = (
                f" (Page {chunk.metadata['page_number']})"
                if has_page
                else ""
            )
            context_parts.append(f"[{n}] {title}{page_info}\n{chunk.text}")

        # 阶段 4：LLM 生成答案
        _progress("llm_generate", 80)
        t_llm = time.monotonic()

        # 3. 调用 LLM 生成答案（无 LLM 时降级为摘要回答）
        if self._llm_adapter is not None and context_parts:
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

            user_prompt = (
                "Context:\n\n"
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
        else:
            answer = "未在知识库中找到与该问题相关的内容。请尝试其他关键词或上传相关文档。"

        _record("llm_generate", t_llm)
        _record("ask_total", ask_start, sources=len(sources))
        _progress("done", 100)

        return {
            "conversation_id": cid,
            "answer": answer,
            "sources": sources,
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

    async def sync_documents(
        self, target: str, doc_ids: list[str] | None = None
    ) -> dict:
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

    async def update_config_value(self, section: str, key: str, value: Any) -> None:
        """更新受限配置项，并进行写保护校验与运行时热重载。"""
        if section not in ("vector_db", "ask"):
            raise ValueError(f"Section '{section}' is write-protected or read-only.")

        # 保存配置到内存与物理存储
        self._persist_config_value(section, key, value)

        # 针对 vector_db 的改动，触发热重载 (Hot-reload)
        if section == "vector_db" and self._config:
            vdb = self._config.get_vector_db_config()
            
            # 如果 vector_db 开启了 milvus，但 vector_store 尚未初始化，在此进行动态构建
            if vdb.backend == "milvus" and not self._vector_store:
                from core.repository.vector_store.milvus_lite import MilvusLiteVectorStore
                db_dir_path = (
                    self._managed_documents_dir.parent
                    if self._managed_documents_dir
                    else Path("./data")
                )
                milvus_db_path = str(db_dir_path / vdb.db_filename)
                self._vector_store = MilvusLiteVectorStore(db_path=milvus_db_path)
            
            # 重新实例化并构建 Embedding Provider 实例
            from core.repository.embedding.factory import EmbeddingProviderFactory
            db_dir_str = (
                str(self._managed_documents_dir.parent)
                if self._managed_documents_dir
                else "./data"
            )
            self._embedding_provider = EmbeddingProviderFactory.create_provider(
                self._config, db_dir=db_dir_str
            )
            
            # 将更新后的实例同步回统一检索编排器 (RetrievalOrchestrator) 内部
            if self._retrieval_orchestrator:
                self._retrieval_orchestrator._embedding_provider = self._embedding_provider
                self._retrieval_orchestrator._vector_store = self._vector_store


    async def test_embedding_connection(
        self, api_key: str, base_url: str, model_name: str
    ) -> dict:
        """临时创建一个 ExternalEmbeddingProvider 并发送测试请求，验证云端 API 可连通性。"""
        from core.repository.embedding.external import ExternalEmbeddingProvider
        provider = ExternalEmbeddingProvider(
            api_key=api_key,
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

    async def build_graph(self, collection: str | None = None) -> dict:
        """构建/增量更新知识图谱（仅对变化 chunk 抽取）。

        Reserved（v0.6.0 LightRAG）：返回新增/更新的实体与关系数。
        """
        if self._graph_build_pipeline:
            return await self._graph_build_pipeline.build_graph(collection)
        raise NotImplementedError("build_graph: available in v0.6.0")

    async def query_graph(
        self,
        query: str,
        top_k: int = 5,
        collection: str | None = None,
        debug: bool = False,
    ) -> dict:
        """知识图谱查询（向量召回 + 图邻域扩展 + RRF 融合）。

        Reserved（v0.6.0）：返回命中实体/关系与来源 chunk。
        """
        if self._graph_search_pipeline:
            col = collection
            if col is None:
                cols = await self.list_collections()
                col = cols[0].name if cols else "default"

            res = await self._graph_search_pipeline.search(
                collection=col,
                query=query,
                top_k=top_k,
                debug=debug,
            )

            # 序列化为纯 dict 以确保 Web/JSON 兼容性
            serialized_chunks = []
            for ch in res.get("chunks", []):
                serialized_chunks.append({
                    "chunk_id": ch.chunk_id,
                    "doc_id": ch.doc_id,
                    "ordinal": ch.ordinal,
                    "text": ch.text,
                    "content_hash": ch.content_hash,
                })

            serialized_entities = []
            for ent in res.get("entities", []):
                serialized_entities.append({
                    "entity_id": ent.entity_id,
                    "name": ent.name,
                    "entity_type": ent.entity_type,
                    "description": ent.description,
                    "source_chunk_ids": ent.source_chunk_ids,
                    "degree": ent.degree,
                })

            serialized_relations = []
            for rel in res.get("relations", []):
                serialized_relations.append({
                    "relation_id": rel.relation_id,
                    "src_entity_id": rel.src_entity_id,
                    "dst_entity_id": rel.dst_entity_id,
                    "relation": rel.relation,
                    "description": rel.description,
                    "weight": rel.weight,
                    "source_chunk_ids": rel.source_chunk_ids,
                })

            payload = {
                "status": "success",
                "query": res.get("query", query),
                "collection": col,
                "chunks": serialized_chunks,
                "entities": serialized_entities,
                "relations": serialized_relations,
                "context": res.get("context", ""),
            }
            if debug:
                payload["debug"] = res.get("debug", {})
            return payload

        raise NotImplementedError("query_graph: available in v0.6.0")

    async def get_graph(self, collection: str | None = None) -> dict:
        """取图谱可视化数据（节点 + 边）。

        Reserved（v0.7.0 图谱可视化）：返回 {nodes:[...], edges:[...]}。
        """
        if self._graph_store:
            col = collection
            if col is None:
                cols = await self.list_collections()
                col = cols[0].name if cols else "default"

            docs = await self._source_store.list_documents(collection=col)
            chunk_by_id: dict[str, DocumentChunk] = {}
            for doc in docs:
                for chunk in await self._source_store.list_chunks(doc.doc_id):
                    chunk_by_id[chunk.chunk_id] = chunk
            scoped_chunk_ids = set(chunk_by_id)

            nodes = []
            for ent in await self._graph_store.list_entities():
                source_ids = [cid for cid in ent.source_chunk_ids if cid in scoped_chunk_ids]
                if not source_ids:
                    continue
                nodes.append({
                    "id": ent.entity_id,
                    "name": ent.name,
                    "type": ent.entity_type,
                    "description": ent.description,
                    "degree": ent.degree,
                    "source_chunk_ids": source_ids,
                    "source_previews": _chunk_previews(chunk_by_id, source_ids),
                })

            node_ids = {node["id"] for node in nodes}
            edges = []
            for rel in await self._graph_store.list_relations():
                source_ids = [cid for cid in rel.source_chunk_ids if cid in scoped_chunk_ids]
                if not source_ids:
                    continue
                if rel.src_entity_id not in node_ids or rel.dst_entity_id not in node_ids:
                    continue
                edges.append({
                    "id": rel.relation_id,
                    "source": rel.src_entity_id,
                    "target": rel.dst_entity_id,
                    "relation": rel.relation,
                    "description": rel.description,
                    "weight": rel.weight,
                    "source_chunk_ids": source_ids,
                    "source_previews": _chunk_previews(chunk_by_id, source_ids),
                })

            return {
                "status": "success",
                "collection": col,
                "nodes": nodes,
                "edges": edges,
            }

        raise NotImplementedError("get_graph: available in v0.7.0")

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
        if self._graph_store is None:
            return {"entities_count": 0, "relations_count": 0, "collections_covered": 0}
        entities = await self._graph_store.list_entities()
        relations = await self._graph_store.list_relations()
        chunk_ids: set[str] = set()
        for ent in entities:
            chunk_ids.update(ent.source_chunk_ids)
        collections: set[str] = set()
        for cid in chunk_ids:
            # 通过 doc_id 映射集合（best-effort）
            chunk_rows = await self._source_store.list_chunks_by_id([cid]) if hasattr(
                self._source_store, "list_chunks_by_id"
            ) else []
            for chunk in chunk_rows:
                doc = await self._source_store.get_document(chunk.doc_id)
                if doc:
                    collections.add(doc.collection)
        return {
            "entities_count": len(entities),
            "relations_count": len(relations),
            "collections_covered": len(collections),
        }

    # ── 调试：系统信息 & 文件列表 ─────────────────────────────────

    def get_system_info(self) -> dict:
        """返回后端运行环境基础信息，供调试面板使用。"""
        import sys
        data_dir = (
            self._managed_documents_dir.parent
            if self._managed_documents_dir else Path("data")
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
            entries.append({
                "name": item.name,
                "type": "file" if item.is_file() else "dir",
                "size_bytes": stat.st_size if item.is_file() else None,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return {
            "path": str(target.relative_to(data_dir)),
            "entries": entries,
        }

    # ── HuggingFace 本地模型管理 ──────────────────────────────────

    def list_local_embedding_models(self) -> list[dict]:
        """列出 HuggingFace hub 缓存中的本地 embedding 模型目录。"""
        import os
        hf_cache = Path(
            os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        ) / "hub"
        if not hf_cache.is_dir():
            return []
        models = []
        for entry in sorted(hf_cache.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("models--"):
                continue
            raw_name = entry.name[len("models--"):]
            display_name = raw_name.replace("--", "/")
            size_bytes = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            try:
                mtime = max(f.stat().st_mtime for f in entry.rglob("*") if f.is_file())
                last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except ValueError:
                last_modified = None
            models.append({
                "name": display_name,
                "dir_name": entry.name,
                "size_bytes": size_bytes,
                "last_modified": last_modified,
                "path": str(entry),
            })
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
        hf_cache = Path(
            os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        ) / "hub"
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


def _chunk_previews(
    chunk_by_id: dict[str, DocumentChunk],
    chunk_ids: list[str],
    limit: int = 360,
) -> list[dict]:
    previews = []
    for chunk_id in chunk_ids[:5]:
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            continue
        text = chunk.text.strip()
        previews.append({
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "ordinal": chunk.ordinal,
            "text": text[:limit],
            "truncated": len(text) > limit,
        })
    return previews


__all__ = ["KnowledgeRepositoryApi"]
