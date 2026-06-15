"""重排器接口（repository 层，接口先行）。

为何存在：RRF 融合只按名次加权，不看 query↔chunk 的真实语义匹配度。重排器用
cross-encoder 对候选二次联合打分，把真正相关的捞到顶。生产实现 bge_local.py、
退化实现 noop.py 共用本接口。本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


@dataclass(frozen=True)
class ScoredChunk:
    """重排打分后的候选：chunk 配其相关度分（score 越大越相关）。"""

    chunk: DocumentChunk
    score: float


class Reranker(ABC):
    """重排器适配器接口。

    契约：对召回候选按 (query, chunk) 语义相关度二次排序，不改变 chunk 内容、
    不引入 chunk。所有实现对空候选返回空列表，且不修改入参列表。
    """

    @property
    def is_passthrough(self) -> bool:
        """是否为「不做语义重排」的退化态（按入参顺序打分）。

        deep thinking 据此把 rerank 权重自动归零：无真实 cross-encoder 时 rerank 分只是
        顺序噪声，不应参与排序。默认 False（具备真实重排能力）；退化实现覆盖为 True。
        """
        return False

    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[DocumentChunk], *, top_n: int | None = None
    ) -> list[ScoredChunk]:
        """按 (query, chunk) 语义相关度对候选降序重排。

        契约：
            - 返回按 score 降序的 ScoredChunk；score 越大越相关。
            - top_n 非 None 时只返回前 top_n 个；None 返回全部候选的打分。
            - 候选为空返回空列表；本方法不修改入参。
        """
        ...


__all__ = ["Reranker", "ScoredChunk"]
