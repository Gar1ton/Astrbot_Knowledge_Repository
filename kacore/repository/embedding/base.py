"""Embedding 计算接口（repository 层，接口先行）。

定义将文本分块或提问转换为稠密浮点向量（dense vector）的契约。
本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Embedding 向量计算提供者接口。"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """将单个查询文本转换为稠密向量。"""
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量将文档分块文本转换为稠密向量列表。"""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """获取当前 Embedding 模型输出向量的维度（如 384, 1536 等）。"""
        ...


__all__ = ["EmbeddingProvider"]
