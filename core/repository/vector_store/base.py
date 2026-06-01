"""本地向量检索存储接口（repository 层，接口先行）。

定义「可丢弃向量索引」的底层契约。此层不保留文档事实源，仅充当 SQLite 的索引投影。
生产实现 milvus_lite.py、测试实现 memory.py 共用本接口。
本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


class VectorStore(ABC):
    """向量库适配器接口。

    契约：仅作为 SQLite 文档分块的可重建投影索引。所有写入/删除都是幂等的。
    """

    @abstractmethod
    async def upsert_chunks(
        self, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        """批量同步或增量插入分块向量及元数据。

        如果 chunk_id 已存在，则予以更新（覆写）。
        """
        ...

    @abstractmethod
    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        """按 chunk_id 批量删除向量。若 id 不存在则静默忽略。"""
        ...

    @abstractmethod
    async def delete_collection(self, collection: str) -> None:
        """按 collection 标签删除该集合下的全部向量。"""
        ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filter_metadata: dict | None = None,
    ) -> list[tuple[str, float]]:
        """在指定集合中检索最相似的向量。

        返回 (chunk_id, distance_score) 列表，按相似度降序（如余弦相似度）或升序（L2 距离）。
        若集合内无数据返回空列表。
        """
        ...

    @abstractmethod
    async def clear(self) -> None:
        """清空向量数据库中的全部数据及索引。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """优雅关闭向量数据库连接，释放文件锁等系统资源。"""
        ...


__all__ = ["VectorStore"]
