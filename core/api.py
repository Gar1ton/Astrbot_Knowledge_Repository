"""业务门面（框架无关，见 api.README.md 与 ../ARCHITECTURE.md §7）。

为 WebUI / CLI / 其它入口提供统一的纯业务调用面：不含 HTTP 概念，只收发普通数据/domain 对象。
`web/` 把请求翻译后委派到这里，再把返回包装成 HTTP 响应。

落地策略：本门面当前直接依赖仓储端口（source_store/kb_reader/sync_targets）。后续版本引入
managers/pipelines（ingest/category/sync/quota）后，对应写操作改为委派到 manager，门面签名不变。
依赖经构造器注入，自身不创建依赖（装配在组合根）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.domain.models import Collection, SourceDocument, SyncTargetKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from core.config import Config
    from core.domain.models import DocumentChunk, QuotaUsage
    from core.managers.base import BaseCategoryManager, BaseIngestManager, BaseQuotaManager
    from core.pipelines.graph_build_pipeline import GraphBuildPipeline
    from core.pipelines.graph_search_pipeline import GraphSearchPipeline
    from core.pipelines.sync_pipeline import SyncPipeline
    from core.repository.graph_store.base import GraphStore
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.sync_targets.base import SyncTarget


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
    ) -> None:
        self._source_store = source_store
        self._kb_reader = kb_reader
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

    async def delete_collection(self, name: str) -> bool:
        """删除集合本身（不级联删其文档）。返回 False 表示 name 不存在。"""
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
        if self._ingest_manager:
            return await self._ingest_manager.ingest(
                title=title,
                file_path=file_path,
                content_type=content_type,
                size_bytes=size_bytes,
                collection=collection,
                tags=tags,
            )

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
        """删除文档及其分块。返回 False 表示 doc_id 不存在。"""
        return await self._source_store.delete_document(doc_id)

    # ── AstrBot 知识库（调用 / 检索）────────────────────────────

    async def list_kb_collections(self) -> list[str]:
        """列出 AstrBot 知识库中的集合名。"""
        return await self._kb_reader.list_collections()

    async def search_kb(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        """在某 AstrBot 知识库集合内检索（复用 AstrBot 的 embedding + RRF）。"""
        return await self._kb_reader.search(collection, query, top_k)

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
        """立即触发一次 R2 全量备份（原件 + manifest + kb.db 快照）。

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

    def _persist_config_value(self, section: str, key: str, value: object) -> None:
        if self._config is not None:
            self._config.set_value(section, key, value)
        if self._config_persist is not None:
            self._config_persist(section, key, value)


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
