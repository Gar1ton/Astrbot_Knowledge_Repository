"""本地向量检索存储接口（repository 层，接口先行）。

定义「可丢弃向量索引」的底层契约。此层不保留文档事实源，仅充当 SQLite 的索引投影。
生产实现 milvus_lite.py、测试实现 memory.py 共用本接口。
本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kacore.domain.models import DocumentChunk


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
    async def retain_document_chunks(self, doc_id: str, chunk_ids: frozenset[str]) -> None:
        """只保留该文档指定的完整 chunk 集，删除其余修订的向量；不影响其他文档。

        调用方必须先成功写入新集合再调用，不能传部分批次；空集表示清理该文档全部向量。
        操作幂等，失败上抛，由调用方保留 needs_reindex 以重试。
        """
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
        *,
        exclude_chunk_ids: frozenset[str] | None = None,
        allowed_doc_ids: frozenset[str] | None = None,
    ) -> list[tuple[str, float]]:
        """在指定集合中检索最相似的向量。

        返回 (chunk_id, distance_score) 列表，按相似度降序（如余弦相似度）或升序（L2 距离）。
        若集合内无数据返回空列表。

        allowed_doc_ids 非 None 时在 top_k 前限制文档，空集返回空结果。
        exclude_chunk_ids 非空时，实现必须在候选截断（top_k）**之前**排除这些 chunk_id——
        发现性补查排除已命中 chunk 的语义要求排除发生在候选生成阶段，不是事后从结果里
        再过滤一遍（否则会把本该进入 top_k 的下一个候选误伤挤出结果）。不传或为空集合时
        行为与旧签名完全一致，不影响普通检索路径。
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
