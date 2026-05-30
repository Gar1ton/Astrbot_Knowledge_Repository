"""AstrBot 运行态知识库数据结构适配器（防腐层）。

把 AstrBot 内部的知识库（FAISS/FTS5/SQLite 记录）与项目 domain 模型 (DocumentChunk) 双向翻译。
安全屏蔽运行态的不确定性。
"""
from __future__ import annotations

from typing import Any

from core.domain.models import DocumentChunk


def to_document_chunk(raw_chunk: Any) -> DocumentChunk:
    """把 AstrBot 内部的 chunk 对象/字典翻译为 clean domain DocumentChunk。"""
    # 兼容字典和对象属性取值，确保鲁棒性
    if isinstance(raw_chunk, dict):
        return DocumentChunk(
            chunk_id=str(raw_chunk.get("chunk_id") or raw_chunk.get("id") or ""),
            doc_id=str(raw_chunk.get("doc_id") or ""),
            ordinal=int(raw_chunk.get("ordinal") or 0),
            text=str(raw_chunk.get("text") or ""),
            content_hash=str(raw_chunk.get("content_hash") or ""),
        )

    return DocumentChunk(
        chunk_id=str(
            getattr(raw_chunk, "chunk_id", None)
            or getattr(raw_chunk, "id", None)
            or ""
        ),
        doc_id=str(getattr(raw_chunk, "doc_id", "")),
        ordinal=int(getattr(raw_chunk, "ordinal", 0)),
        text=str(getattr(raw_chunk, "text", "")),
        content_hash=str(getattr(raw_chunk, "content_hash", "")),
    )


__all__ = ["to_document_chunk"]
