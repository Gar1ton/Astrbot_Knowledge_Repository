"""本地 cross-encoder 重排器（repository 层，可选依赖 sentence-transformers）。

为何存在：bge-reranker 这类 cross-encoder 对每个 (query, chunk) 对联合编码打分，
精度远高于双塔向量召回，但每对一次前向、成本随候选数线性增长。故由 max_candidates
截断候选、batch 推理，并把阻塞推理下放 executor，不阻塞事件循环。

两个稳健性设计：
    - 懒加载：模型在首次 rerank 时才加载，避免插件启动即下载大模型。
    - 自我保护：加载或推理失败时记一次 warning 并永久回退为「按入参顺序」，绝不向上
      抛异常拖垮 deep thinking（reranker 不可用 = 退化，不是错误）。

不做 timeout：本地线程内的推理无法可靠中断，改由 max_candidates / batch_size 控成本。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.repository.reranker.base import Reranker, ScoredChunk

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk

logger = logging.getLogger("Reranker")


def _passthrough(pool: list[DocumentChunk], top_n: int | None) -> list[ScoredChunk]:
    """回退：按入参顺序打分（名次倒数），语义同 NoopReranker。"""
    limit = len(pool) if top_n is None else min(top_n, len(pool))
    return [ScoredChunk(chunk=chunk, score=1.0 / (i + 1)) for i, chunk in enumerate(pool[:limit])]


class CrossEncoderReranker(Reranker):
    """sentence-transformers CrossEncoder 封装（懒加载 + 自我保护）。

    契约：构造不加载模型（不触发下载）；首次 rerank 时懒加载。加载/推理任一失败 →
    记一次 warning、置 disabled、回退按序返回，后续直接按序（不再重试）。
    """

    def __init__(
        self,
        *,
        model: str,
        device: str = "auto",
        batch_size: int = 32,
        max_candidates: int = 30,
    ) -> None:
        self._model_name = model
        self._device = None if device == "auto" else device
        self._batch_size = batch_size
        self._max_candidates = max_candidates
        self._model: Any = None
        self._disabled = False

    @property
    def is_passthrough(self) -> bool:
        # 加载/推理失败后永久退化为按序（_disabled=True），此时视为 passthrough。
        return self._disabled

    def _ensure_model(self) -> None:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name, device=self._device)

    async def rerank(
        self, query: str, candidates: list[DocumentChunk], *, top_n: int | None = None
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        pool = candidates[: self._max_candidates]
        if self._disabled:
            return _passthrough(pool, top_n)
        try:
            await asyncio.to_thread(self._ensure_model)
            pairs = [(query, chunk.text) for chunk in pool]
            scores = await asyncio.to_thread(
                self._model.predict, pairs, batch_size=self._batch_size
            )
        except Exception as exc:  # 加载/推理失败 → 永久退化为按序，不抛崩 deep thinking。
            logger.warning("CrossEncoder rerank failed, fallback to input order: %s", exc)
            self._disabled = True
            return _passthrough(pool, top_n)
        scored = [
            ScoredChunk(chunk=chunk, score=float(score))
            for chunk, score in zip(pool, scores)
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored if top_n is None else scored[:top_n]


__all__ = ["CrossEncoderReranker"]
