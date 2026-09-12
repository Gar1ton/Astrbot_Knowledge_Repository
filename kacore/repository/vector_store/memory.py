"""VectorStore 的内存实现（无 I/O，供单元测试与接口验证）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kacore.repository.vector_store.base import VectorStore

if TYPE_CHECKING:
    from kacore.domain.models import DocumentChunk


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a in v1) ** 0.5
    norm_b = sum(b * b for b in v2) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class InMemoryVectorStore(VectorStore):
    """保存在内存中的向量检索库。"""

    def __init__(self) -> None:
        # 结构：chunk_id -> (DocumentChunk, vector)
        self._data: dict[str, tuple[DocumentChunk, list[float]]] = {}

    async def upsert_chunks(
        self, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        for chunk, emb in zip(chunks, embeddings):
            self._data[chunk.chunk_id] = (chunk, emb)

    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        for cid in chunk_ids:
            self._data.pop(cid, None)

    async def retain_document_chunks(self, doc_id: str, chunk_ids: frozenset[str]) -> None:
        self._data = {
            cid: item for cid, item in self._data.items()
            if item[0].doc_id != doc_id or cid in chunk_ids
        }

    async def delete_collection(self, collection: str) -> None:
        # 在内存库中，我们基于 doc_to_col 映射判定 chunk 是否属于要删除的 collection。
        # SQLite source_store 仍是文档的事实源，本内存库仅保持同步状态。
        doc_to_col = getattr(self, "_doc_to_col", {})
        self._data = {
            cid: (chunk, emb)
            for cid, (chunk, emb) in self._data.items()
            if doc_to_col.get(chunk.doc_id) != collection
        }

    def set_doc_collection_mapping(self, doc_id: str, collection: str) -> None:
        """测试辅助：注册文档与集合的关系。"""
        if not hasattr(self, "_doc_to_col"):
            self._doc_to_col: dict[str, str] = {}
        self._doc_to_col[doc_id] = collection

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
        if top_k <= 0:
            return []

        candidates = []
        doc_to_col = getattr(self, "_doc_to_col", {})
        for cid, (chunk, emb) in self._data.items():
            if allowed_doc_ids is not None and chunk.doc_id not in allowed_doc_ids:
                continue
            if exclude_chunk_ids and cid in exclude_chunk_ids:
                continue

            # 过滤 collection (利用已注册的映射)
            col_mapped = doc_to_col.get(chunk.doc_id)
            if col_mapped and col_mapped != collection:
                continue

            # metadata 过滤 (测试辅助)
            if filter_metadata:
                matched = True
                for k, v in filter_metadata.items():
                    if k == "doc_id" and chunk.doc_id != v:
                        matched = False
                        break
                if not matched:
                    continue

            score = _cosine_similarity(query_vector, emb)
            candidates.append((cid, score))

        # 按相似度降序排列
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    async def clear(self) -> None:
        self._data.clear()
        if hasattr(self, "_doc_to_col"):
            self._doc_to_col.clear()

    async def close(self) -> None:
        pass


__all__ = ["InMemoryVectorStore"]
