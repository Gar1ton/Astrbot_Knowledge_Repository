"""重排器的退化实现：不做模型推理，保持入参顺序（repository 层）。

用于 provider=noop 或本地 cross-encoder 依赖缺失时，让 deep thinking 与单轮 ask
在无重排能力时仍可运行（按既有 RRF 顺序），保证「缺依赖不影响普通 ask」。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.repository.reranker.base import Reranker, ScoredChunk

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


class NoopReranker(Reranker):
    """按入参顺序原样返回，score 用名次倒数保证与顺序一致的降序。"""

    @property
    def is_passthrough(self) -> bool:
        return True

    async def rerank(
        self, query: str, candidates: list[DocumentChunk], *, top_n: int | None = None
    ) -> list[ScoredChunk]:
        limit = len(candidates) if top_n is None else min(top_n, len(candidates))
        return [
            ScoredChunk(chunk=chunk, score=1.0 / (rank + 1))
            for rank, chunk in enumerate(candidates[:limit])
        ]


__all__ = ["NoopReranker"]
