"""AstrBot 知识库读取接口（repository 层，接口先行）。

定义「读取 AstrBot 默认 KB」的契约：列集合、列文档、取分块、检索。生产实现经 adapters 访问
AstrBot 运行态 KB（FAISS+FTS5+RRF），测试实现 memory.py 以内存数据满足同接口。

只读取、不重造检索：检索沿用 AstrBot 自带 embedding 与 RRF 融合。本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


class KnowledgeBaseReader(ABC):
    """AstrBot 默认知识库的只读视图。

    契约：所有方法为只读；collection 为 AstrBot 知识库名。检索委托 AstrBot，不在本层实现向量计算。
    """

    @abstractmethod
    async def list_collections(self) -> list[str]:
        """列出 AstrBot 中已存在的知识库集合名。"""
        ...

    @abstractmethod
    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        """列出某集合下的全部分块。集合不存在返回空列表。"""
        ...

    @abstractmethod
    async def search(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        """在某集合内检索，返回最相关的 top_k 个分块（已按 AstrBot 的 RRF 融合排序）。

        集合不存在或无结果返回空列表；top_k<=0 视为无结果。
        """
        ...


__all__ = ["KnowledgeBaseReader"]
