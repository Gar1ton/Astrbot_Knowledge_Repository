"""基于 Milvus Lite (内嵌式单文件) 的向量数据库实现。"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from core.repository.vector_store.base import VectorStore

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk

logger = logging.getLogger("MilvusLiteVectorStore")


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

    @property
    def created_collection(self) -> bool:
        return self._created_collection

    def set_doc_collection_mapping(self, doc_id: str, collection: str) -> None:
        """注册或更新文档与集合的关系。"""
        self._doc_to_col[doc_id] = collection

    def validate_schema(self) -> None:
        """Eagerly validate dependencies and the existing collection schema."""
        self._init_client()

    def _init_client(self) -> None:
        if self._initialized:
            return

        from pymilvus import DataType, MilvusClient

        # 确保父目录存在
        db_dir = os.path.dirname(os.path.abspath(self._db_path))
        os.makedirs(db_dir, exist_ok=True)

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
        self._init_client()

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
            self._client.upsert(collection_name=self._collection_name, data=data)
        except Exception as e:
            logger.warning(f"Milvus client.upsert failed ({e}), falling back to delete & insert...")
            chunk_ids = [c.chunk_id for c in chunks]
            try:
                self._client.delete(collection_name=self._collection_name, ids=chunk_ids)
            except Exception:
                pass
            self._client.insert(collection_name=self._collection_name, data=data)

    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._init_client()
        try:
            self._client.delete(collection_name=self._collection_name, ids=chunk_ids)
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            raise RuntimeError(f"Failed to delete chunks: {e}") from e

    async def delete_collection(self, collection: str) -> None:
        self._init_client()
        try:
            # 根据 collection_tag 属性删除匹配的向量数据
            self._client.delete(
                collection_name=self._collection_name,
                filter=f"collection_tag == '{collection}'",
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
    ) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        self._validate_vector(query_vector)
        self._init_client()

        filter_expr = f"collection_tag == '{collection}'"
        if filter_metadata:
            for k, v in filter_metadata.items():
                val_str = str(v).replace("'", "\\'")
                filter_expr += f" and {k} == '{val_str}'"

        try:
            results = self._client.search(
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

    async def clear(self) -> None:
        try:
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
        except Exception as e:
            logger.error(f"Failed to clear vector store: {e}")
            raise RuntimeError(f"Failed to clear vector store: {e}") from e

    async def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.error(f"Failed to close Milvus client: {e}")
            self._client = None
            self._initialized = False


__all__ = ["MilvusLiteVectorStore", "MilvusSchemaMismatchError"]
