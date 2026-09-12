"""单文档派生数据的 SQLite 原子写入；由仓储写锁保护，失败由调用方回滚。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from kacore.domain.models import DocumentChunk, PageChunk, SourceDocument


async def commit_processing(
    db: aiosqlite.Connection, document: SourceDocument,
    chunks: list[DocumentChunk], pages: list[PageChunk],
) -> None:
    """仅更新处理字段，保留集合、标题及其他用户元数据；全部 DML 共用事务。"""
    async with db.execute(
        "SELECT local_meta FROM documents WHERE doc_id = ?", (document.doc_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise FileNotFoundError(document.doc_id)
    metadata = json.loads(row[0] or "{}")
    for key in ("chunk_schema", "processing_version"):
        if key in document.local_meta:
            metadata[key] = document.local_meta[key]
    metadata.pop("processing_pending", None)
    await db.execute("DELETE FROM chunks WHERE doc_id = ?", (document.doc_id,))
    await db.executemany(
        "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(c.chunk_id, document.doc_id, c.ordinal, c.text, c.content_hash,
          json.dumps(c.metadata)) for c in chunks],
    )
    await db.execute("DELETE FROM page_chunks WHERE document_id = ?", (document.doc_id,))
    await db.executemany(
        "INSERT INTO page_chunks (document_id, page, markdown_start_char, markdown_end_char) "
        "VALUES (?, ?, ?, ?)",
        [(document.doc_id, p.page, p.markdown_start_char, p.markdown_end_char) for p in pages],
    )
    await db.execute(
        "UPDATE documents SET converter = ?, converter_version = ?, needs_reindex = 1, "
        "local_meta = ? WHERE doc_id = ?",
        (document.converter, document.converter_version, json.dumps(metadata), document.doc_id),
    )
    await db.commit()
