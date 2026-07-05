"""AstrBot 默认知识库读取的生产仓储实现。

复用 AstrBot 自带的 KB（FAISS+FTS5+RRF）只读检索，
不重造向量计算，通过 adapters/astrbot_kb.py 做翻译。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from core.domain.models import DocumentChunk
from core.repository.kb_reader.base import KnowledgeBaseReader

logger = logging.getLogger("AstrBotKnowledgeBaseReader")


class AstrBotKnowledgeBaseReader(KnowledgeBaseReader):
    """从 AstrBot 运行态上下文读取默认 KB 的只读仓储。

    AstrBot v4 实际接口：
      - context.kb_manager  →  KnowledgeBaseManager
      - kb_manager.list_kbs()  →  list[KnowledgeBase]（每项有 .kb_name）
      - kb_manager.retrieve(query, kb_names, top_k_fusion, top_m_final)
          →  {"context_text": str, "results": [{chunk_id, doc_id, kb_id,
               kb_name, doc_name, chunk_index, content, score, char_count}]}
    """

    def __init__(self, context: Any) -> None:
        self._context = context

    def _kb_manager(self) -> Any | None:
        return getattr(self._context, "kb_manager", None) if self._context else None

    async def list_collections(self) -> list[str]:
        """列出 AstrBot 中已存在的知识库名称（对应本插件的 collection 概念）。"""
        mgr = self._kb_manager()
        if mgr is None:
            return []
        try:
            kbs = await mgr.list_kbs()
            return [kb.kb_name for kb in kbs if kb.kb_name]
        except Exception as e:
            logger.error("Failed to list AstrBot KBs: %s", e)
        return []

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        """列出某知识库下的全部分块（不常用，仅供诊断）。"""
        return []

    async def search(
        self, collection: str, query: str, top_k: int
    ) -> list[DocumentChunk]:
        """在 AstrBot KB 中检索，返回最相关的 top_k 个分块。

        collection 优先映射到同名的 AstrBot KB；若不存在则搜索全部 KB。
        """
        if top_k <= 0 or not self._context:
            return []
        mgr = self._kb_manager()
        if mgr is None:
            return []
        try:
            all_kbs = await mgr.list_kbs()
            all_names = [kb.kb_name for kb in all_kbs if kb.kb_name]
            if not all_names:
                return []

            # 优先只搜 collection 对应的 KB；找不到则搜全部
            kb_names = [collection] if collection in all_names else all_names

            result = await mgr.retrieve(
                query=query,
                kb_names=kb_names,
                top_k_fusion=top_k * 4,
                top_m_final=top_k,
            )
            if not result or "results" not in result:
                return []

            chunks: list[DocumentChunk] = []
            for item in result["results"]:
                content = item.get("content", "")
                chunks.append(
                    DocumentChunk(
                        chunk_id=item.get("chunk_id", ""),
                        doc_id=item.get("doc_id", ""),
                        ordinal=item.get("chunk_index", 0),
                        text=content,
                        content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
            return chunks
        except Exception as e:
            logger.error(
                "Failed to search AstrBot KB collection=%r query=%r: %s",
                collection, query, e,
            )
        return []


__all__ = ["AstrBotKnowledgeBaseReader"]
