"""KnowledgeBaseReader 的内存实现（无 I/O，供接口对换测试）。

检索用确定性的朴素子串打分替代真实向量检索，仅为验证业务编排契约，不追求召回质量。
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from core.repository.kb_reader.base import KnowledgeBaseReader

if TYPE_CHECKING:
    from core.domain.models import DocumentChunk


class InMemoryKnowledgeBaseReader(KnowledgeBaseReader):
    """纯内存只读 KB：按 collection 持有分块，检索用子串命中计数排序（确定性）。"""

    def __init__(self, data: dict[str, list[DocumentChunk]] | None = None) -> None:
        self._data: dict[str, list[DocumentChunk]] = data or {}

    async def list_collections(self) -> list[str]:
        return sorted(self._data.keys())

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        return [copy.deepcopy(c) for c in self._data.get(collection, [])]

    async def search(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        if top_k <= 0:
            return []
        chunks = self._data.get(collection, [])
        q = query.lower()
        scored = [(c.text.lower().count(q), c) for c in chunks]
        hits = [c for score, c in scored if score > 0]
        hits.sort(key=lambda c: (-c.text.lower().count(q), c.ordinal))
        return [copy.deepcopy(c) for c in hits[:top_k]]


__all__ = ["InMemoryKnowledgeBaseReader"]
