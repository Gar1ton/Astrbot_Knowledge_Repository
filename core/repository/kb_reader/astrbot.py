"""AstrBot 默认知识库读取的生产仓储实现。

复用 AstrBot 自带的 KB（FAISS+FTS5+RRF）只读检索，
不重造向量计算，通过 adapters/astrbot_kb.py 做翻译。
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.astrbot_kb import to_document_chunk
from core.domain.models import DocumentChunk
from core.repository.kb_reader.base import KnowledgeBaseReader

logger = logging.getLogger("AstrBotKnowledgeBaseReader")


class AstrBotKnowledgeBaseReader(KnowledgeBaseReader):
    """从 AstrBot 运行态上下文读取默认 KB 的只读仓储。"""

    def __init__(self, context: Any) -> None:
        self._context = context

    async def list_collections(self) -> list[str]:
        """列出 AstrBot 中已存在的知识库集合名。"""
        if not self._context:
            return []
        try:
            # 兼容多种可能的运行态获取方法
            kb_manager = getattr(self._context, "kb_manager", None)
            if kb_manager is not None:
                if hasattr(kb_manager, "list_collections"):
                    return await kb_manager.list_collections()
                elif hasattr(kb_manager, "get_collections"):
                    return await kb_manager.get_collections()

            # 回退：直接从 context 取 collections 属性/方法
            get_cols = getattr(self._context, "list_collections", None)
            if callable(get_cols):
                return await get_cols()

            cols = getattr(self._context, "collections", None)
            if isinstance(cols, list):
                return [str(c) for c in cols]
            elif isinstance(cols, dict):
                return sorted(cols.keys())
        except Exception as e:
            logger.error(f"Failed to list collections from context: {e}")
        return []

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        """列出某集合下的全部分块。"""
        if not self._context:
            return []
        try:
            kb_manager = getattr(self._context, "kb_manager", None)
            raw_chunks = None
            if kb_manager is not None and hasattr(kb_manager, "list_chunks"):
                raw_chunks = await kb_manager.list_chunks(collection)
            else:
                get_chunks = getattr(self._context, "list_chunks", None)
                if callable(get_chunks):
                    raw_chunks = await get_chunks(collection)

            if raw_chunks:
                return [to_document_chunk(c) for c in raw_chunks]
        except Exception as e:
            logger.error(f"Failed to list chunks for collection {collection}: {e}")
        return []

    async def search(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        """在某集合内检索，返回最相关的 top_k 个分块。"""
        if top_k <= 0 or not self._context:
            return []
        try:
            kb_manager = getattr(self._context, "kb_manager", None)
            raw_results = None
            if kb_manager is not None and hasattr(kb_manager, "search"):
                raw_results = await kb_manager.search(collection, query, top_k)
            else:
                search_fn = getattr(self._context, "search", None)
                if callable(search_fn):
                    raw_results = await search_fn(collection, query, top_k)

            if raw_results:
                return [to_document_chunk(c) for c in raw_results]
        except Exception as e:
            logger.error(
                f"Failed to search collection {collection} with query '{query}': {e}"
            )
        return []


__all__ = ["AstrBotKnowledgeBaseReader"]
