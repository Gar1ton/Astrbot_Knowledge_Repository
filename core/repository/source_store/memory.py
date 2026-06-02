"""源文档库的内存实现（无 I/O，供接口对换测试）。

行为与 sqlite.py 应一致，仅以内存 dict 持久化。深拷贝进出，避免调用方持有内部引用造成隐式改动。
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from core.repository.source_store.base import SourceDocumentStore

if TYPE_CHECKING:
    from core.domain.models import (
        Collection,
        DocumentChunk,
        SourceDocument,
        SyncRecord,
        SyncTargetKind,
    )


class InMemorySourceDocumentStore(SourceDocumentStore):
    """纯内存的 SourceDocumentStore，确定性、无网络/磁盘。"""

    def __init__(self) -> None:
        self._collections: dict[str, Collection] = {}
        self._documents: dict[str, SourceDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._sync_records: dict[tuple[str, SyncTargetKind], SyncRecord] = {}

    # ── 集合 ────────────────────────────────────────────────────

    async def upsert_collection(self, collection: Collection) -> None:
        self._collections[collection.name] = copy.deepcopy(collection)

    async def list_collections(self) -> list[Collection]:
        return [copy.deepcopy(c) for c in sorted(self._collections.values(), key=lambda c: c.name)]

    async def delete_collection(self, name: str) -> bool:
        return self._collections.pop(name, None) is not None

    async def move_documents_to_collection(self, from_name: str, to_name: str) -> int:
        count = 0
        for doc in self._documents.values():
            if doc.collection == from_name:
                doc.collection = to_name
                count += 1
        return count

    async def list_pending_reindex_documents(self) -> list[SourceDocument]:
        import copy
        pending = [d for d in self._documents.values() if d.needs_reindex]
        return [
            copy.deepcopy(d)
            for d in sorted(pending, key=lambda d: (d.created_at is None, d.created_at, d.doc_id))
        ]

    # ── 文档 ────────────────────────────────────────────────────

    async def add_document(self, document: SourceDocument) -> None:
        if document.doc_id in self._documents:
            raise ValueError(f"duplicate doc_id: {document.doc_id}")
        self._documents[document.doc_id] = copy.deepcopy(document)

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        doc = self._documents.get(doc_id)
        return copy.deepcopy(doc) if doc is not None else None

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        docs = self._documents.values()
        if collection is not None:
            docs = [d for d in docs if d.collection == collection]
        if tag is not None:
            docs = [d for d in docs if tag in d.tags]
        ordered = sorted(docs, key=lambda d: (d.created_at is None, d.created_at, d.doc_id))
        return [copy.deepcopy(d) for d in ordered]

    async def update_document(self, document: SourceDocument) -> bool:
        if document.doc_id not in self._documents:
            return False
        self._documents[document.doc_id] = copy.deepcopy(document)
        return True

    async def delete_document(self, doc_id: str) -> bool:
        if doc_id not in self._documents:
            return False
        self._chunks.pop(doc_id, None)   # 先删分块
        self._sync_records = {
            key: record for key, record in self._sync_records.items() if key[0] != doc_id
        }
        del self._documents[doc_id]       # 再删文档
        return True

    # ── 分块 ────────────────────────────────────────────────────

    async def replace_chunks(self, doc_id: str, chunks: list[DocumentChunk]) -> None:
        self._chunks[doc_id] = [copy.deepcopy(c) for c in chunks]

    async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
        chunks = self._chunks.get(doc_id, [])
        ordered = sorted(chunks, key=lambda c: c.ordinal)
        return [copy.deepcopy(c) for c in ordered]

    # ── 同步状态 ──────────────────────────────────────────────────

    async def get_sync_record(self, doc_id: str, target: SyncTargetKind) -> SyncRecord | None:
        rec = self._sync_records.get((doc_id, target))
        return copy.deepcopy(rec) if rec is not None else None

    async def upsert_sync_record(self, record: SyncRecord) -> None:
        self._sync_records[(record.doc_id, record.target)] = copy.deepcopy(record)

    async def list_sync_records(self, target: SyncTargetKind | None = None) -> list[SyncRecord]:
        recs = self._sync_records.values()
        if target is not None:
            recs = [r for r in recs if r.target == target]
        ordered = sorted(recs, key=lambda r: (r.synced_at is None, r.synced_at, r.doc_id))
        return [copy.deepcopy(r) for r in ordered]


__all__ = ["InMemorySourceDocumentStore"]
