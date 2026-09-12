"""基于 Milvus Lite (内嵌式单文件) 的向量数据库实现。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from kacore.repository.vector_store.base import VectorStore

if TYPE_CHECKING:
    from kacore.domain.models import DocumentChunk

logger = logging.getLogger("MilvusLiteVectorStore")

_FILTER_KEY_RE = re.compile(r"[A-Za-z0-9_]+")


def _quote_filter_value(value: object) -> str:
    """Milvus filter 表达式的字符串值：转义单引号，防表达式注入/语法破坏。"""
    return str(value).replace("'", "\\'")


class MilvusSchemaMismatchError(RuntimeError):
    """Existing Milvus collection cannot be used with the active embedding dimension."""


class MilvusLiteVectorStore(VectorStore):
    """基于 Milvus Lite 的向量检索适配器。

    契约：仅作为 SQLite 文档分块的可重建投影索引。所有写入/删除都是幂等的。
    """

    def __init__(self, db_path: str = "./data/milvus_lite.db", dim: int = 384) -> None:
        self._db_path = db_path
        self._dim = dim
        self._client = None
        self._doc_to_col: dict[str, str] = {}
        self._collection_name = "kb_chunks"
        self._initialized = False
        self._created_collection = False
        # 懒初始化会在首次检索/写入时触发（开库 + load 秒级），加锁防并发重复初始化。
        self._init_lock = asyncio.Lock()

    @property
    def created_collection(self) -> bool:
        return self._created_collection

    def set_doc_collection_mapping(self, doc_id: str, collection: str) -> None:
        """注册或更新文档与集合的关系。"""
        self._doc_to_col[doc_id] = collection

    def validate_schema(self) -> None:
        """Eagerly validate dependencies and the existing collection schema."""
        self._init_client()

    def _relocate_legacy_store(self) -> None:
        """把 Milvus Lite 2.x 的单文件数据库挪开，让 3.x 以目录形式重建。

        为何需要：Milvus Lite 3.0 起用目录存数据，直接对 2.x 留下的**文件**开库会在
        `os.makedirs(data_dir)` 上抛 `FileExistsError`，对外表现为
        `ConnectionConfigException: Open local milvus failed`，整个向量库就此不可用。

        安全性：本类的契约是「SQLite 文档分块的可重建投影索引」，挪走旧文件不丢原始数据；
        新库为空会让组合根按既有逻辑标记全量 needs_reindex，用户重建索引即可恢复检索。
        """
        path = Path(self._db_path)
        if not path.is_file():  # 目录（3.x）或尚不存在：无需处理
            return

        backup = path.with_name(f"{path.name}.legacy-{int(time.time())}")
        path.rename(backup)
        logger.warning(
            "检测到 Milvus Lite 2.x 单文件数据库 %s；3.x 改用目录存储，已重命名为 %s 并重建空索引。"
            "原始分块保存在 SQLite 中，重建索引后检索即可恢复。",
            path.name,
            backup.name,
        )

    def _init_client(self) -> None:
        if self._initialized:
            return

        from pymilvus import DataType, MilvusClient

        # 确保父目录存在
        db_dir = os.path.dirname(os.path.abspath(self._db_path))
        os.makedirs(db_dir, exist_ok=True)

        self._relocate_legacy_store()
        self._client = MilvusClient(self._db_path)

        # 如果集合不存在，则创建符合 VARCHAR 主键的 Collection Schema
        if not self._client.has_collection(self._collection_name):
            self._created_collection = True
            schema = self._client.create_schema(
                auto_id=False,
                enable_dynamic_field=True,
            )
            schema.add_field(
                field_name="id", datatype=DataType.VARCHAR, max_length=64, is_primary=True
            )
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self._dim)

            index_params = self._client.prepare_index_params()
            index_params.add_index(
                field_name="vector", metric_type="COSINE", index_type="FLAT"
            )

            self._client.create_collection(
                collection_name=self._collection_name,
                schema=schema,
                index_params=index_params,
                consistency_level="Strong",
            )
            logger.info(
                f"Created Milvus Lite collection '{self._collection_name}' "
                f"with dimension {self._dim} successfully."
            )
        else:
            existing_dim = self._existing_dimension()
            if existing_dim is not None and existing_dim != self._dim:
                raise MilvusSchemaMismatchError(
                    f"Milvus collection dimension is {existing_dim}, but the configured "
                    f"embedding dimension is {self._dim}. Rebuild the Milvus index."
                )

        # 打开磁盘上已存在的集合时其处于 released 状态，必须显式 load 才能 search/get/query；
        # 新建集合 create_collection 已自动 load，这里再 load 是幂等的。统一保证 loaded，
        # 避免「跳过 rebuild 直接复用既有索引」时首次检索报 code=101 collection released。
        self._client.load_collection(self._collection_name)
        self._initialized = True

    async def _ensure_client(self) -> None:
        """异步侧的懒初始化入口：to_thread + 锁，避免开库/load 阻塞事件循环或并发重入。"""
        if self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await asyncio.to_thread(self._init_client)

    def _existing_dimension(self) -> int | None:
        description = self._client.describe_collection(self._collection_name)
        for field in description.get("fields", []):
            if (field.get("name") or field.get("field_name")) != "vector":
                continue
            params = field.get("params") or {}
            value = params.get("dim") or field.get("dim")
            return int(value) if value is not None else None
        return None

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self._dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._dim}, got {len(vector)}."
            )

    async def upsert_chunks(
        self, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        if not chunks or not embeddings:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")

        for embedding in embeddings:
            self._validate_vector(embedding)
        await self._ensure_client()

        data = []
        for chunk, emb in zip(chunks, embeddings):
            col = self._doc_to_col.get(chunk.doc_id) or "default"
            data.append({
                "id": chunk.chunk_id,
                "vector": emb,
                "doc_id": chunk.doc_id,
                "collection_tag": col,
                "text": chunk.text,
            })

        logger.info("Milvus upsert: %d chunks", len(chunks))
        try:
            await asyncio.to_thread(
                self._client.upsert, collection_name=self._collection_name, data=data
            )
        except Exception as e:
            logger.warning(f"Milvus client.upsert failed ({e}), falling back to delete & insert...")
            chunk_ids = [c.chunk_id for c in chunks]
            try:
                await asyncio.to_thread(
                    self._client.delete, collection_name=self._collection_name, ids=chunk_ids
                )
            except Exception as del_exc:
                logger.debug("Milvus pre-insert delete failed (best-effort): %s", del_exc)
            await asyncio.to_thread(
                self._client.insert, collection_name=self._collection_name, data=data
            )

    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        await self._ensure_client()
        try:
            await asyncio.to_thread(
                self._client.delete, collection_name=self._collection_name, ids=chunk_ids
            )
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            raise RuntimeError(f"Failed to delete chunks: {e}") from e

    async def retain_document_chunks(self, doc_id: str, chunk_ids: frozenset[str]) -> None:
        await self._ensure_client()
        expression = f"doc_id == '{_quote_filter_value(doc_id)}'"
        if chunk_ids:
            ids = ", ".join(f"'{_quote_filter_value(cid)}'" for cid in sorted(chunk_ids))
            expression += f" and id not in [{ids}]"
        await asyncio.to_thread(
            self._client.delete, collection_name=self._collection_name, filter=expression,
        )

    async def delete_collection(self, collection: str) -> None:
        await self._ensure_client()
        try:
            # 根据 collection_tag 属性删除匹配的向量数据
            await asyncio.to_thread(
                self._client.delete,
                collection_name=self._collection_name,
                filter=f"collection_tag == '{_quote_filter_value(collection)}'",
            )
            # 清理映射缓存
            self._doc_to_col = {
                d: c for d, c in self._doc_to_col.items() if c != collection
            }
        except Exception as e:
            logger.error(f"Failed to delete collection {collection}: {e}")
            raise RuntimeError(f"Failed to delete collection {collection}: {e}") from e

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filter_metadata: dict | None = None,
        *,
        exclude_chunk_ids: frozenset[str] | None = None,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> list[tuple[str, float]]:
        if top_k <= 0 or allowed_doc_ids == frozenset():
            return []

        self._validate_vector(query_vector)
        await self._ensure_client()

        filter_expr = f"collection_tag == '{_quote_filter_value(collection)}'"
        if filter_metadata:
            for k, v in filter_metadata.items():
                if not _FILTER_KEY_RE.fullmatch(k):
                    raise ValueError(f"Invalid metadata filter key: {k!r}")
                filter_expr += f" and {k} == '{_quote_filter_value(v)}'"
        if allowed_doc_ids is not None:
            docs = ", ".join(f"'{_quote_filter_value(d)}'" for d in sorted(allowed_doc_ids))
            filter_expr += f" and doc_id in [{docs}]"
        if exclude_chunk_ids:
            # 用 Milvus 原生 `not in` 表达式在候选截断前下推排除，不做事后过滤
            # （W0 隔离探针已验证 pymilvus 2.6.x + milvus-lite 3.x 对动态字段同样生效）。
            excluded = ", ".join(f"'{_quote_filter_value(cid)}'" for cid in exclude_chunk_ids)
            filter_expr += f" and id not in [{excluded}]"

        try:
            results = await asyncio.to_thread(
                self._client.search,
                collection_name=self._collection_name,
                data=[query_vector],
                limit=top_k,
                filter=filter_expr,
                output_fields=["id"],
            )

            res_list = []
            if results and len(results) > 0:
                for r in results[0]:
                    res_list.append((r["id"], r["distance"]))
            return res_list
        except Exception as e:
            logger.error(f"Milvus search failed: {e}")
            raise RuntimeError(f"Milvus search failed: {e}") from e

    def _clear_sync(self) -> None:
        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(self._db_path)
        if self._client.has_collection(self._collection_name):
            self._client.drop_collection(self._collection_name)
        self._client.close()
        self._client = None
        self._initialized = False
        self._doc_to_col.clear()
        self._init_client()

    async def clear(self) -> None:
        try:
            # 与懒初始化共用同一把锁：drop + 重建期间不允许并发触发 _ensure_client。
            async with self._init_lock:
                await asyncio.to_thread(self._clear_sync)
        except Exception as e:
            logger.error(f"Failed to clear vector store: {e}")
            raise RuntimeError(f"Failed to clear vector store: {e}") from e

    async def close(self) -> None:
        if self._client:
            try:
                # Lite 的 client.close 只断开 RPC；先刷盘，避免解释器退出时才调用 PyArrow。
                if self._initialized:
                    await asyncio.to_thread(self._client.flush, self._collection_name)
            finally:
                try:
                    await asyncio.to_thread(self._client.close)
                finally:
                    self._client = None
                    self._initialized = False


__all__ = ["MilvusLiteVectorStore", "MilvusSchemaMismatchError"]
