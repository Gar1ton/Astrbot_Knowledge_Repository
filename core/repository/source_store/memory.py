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
        PageChunk,
        SourceDocument,
        SyncRecord,
        SyncTargetKind,
        ZoteroAttachment,
        ZoteroCollection,
        ZoteroItem,
        ZoteroLibrary,
        ZoteroRelation,
        ZoteroTag,
    )


class InMemorySourceDocumentStore(SourceDocumentStore):
    """纯内存的 SourceDocumentStore，确定性、无网络/磁盘。"""

    def __init__(self) -> None:
        self._collections: dict[str, Collection] = {}
        self._documents: dict[str, SourceDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._sync_records: dict[tuple[str, SyncTargetKind], SyncRecord] = {}
        self._lightrag_status: dict[str, dict[str, str]] = {}
        # Zotero 镜像 + 页面 provenance（key 均含 library_id 命名空间）
        self._zlibraries: dict[str, ZoteroLibrary] = {}
        self._zcollections: dict[tuple[str, str], ZoteroCollection] = {}
        self._zitems: dict[tuple[str, str], ZoteroItem] = {}
        self._zattachments: dict[tuple[str, str], ZoteroAttachment] = {}
        self._zcollection_items: set[tuple[str, str, str]] = set()  # (lib, coll_key, item_key)
        self._zitem_tags: dict[tuple[str, str], list[ZoteroTag]] = {}
        self._zrelations: set[tuple[str, str, str, str]] = set()
        self._page_chunks: dict[str, list[PageChunk]] = {}

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
        self._chunks.pop(doc_id, None)  # 先删分块
        self._page_chunks.pop(doc_id, None)
        self._sync_records = {
            key: record for key, record in self._sync_records.items() if key[0] != doc_id
        }
        self._lightrag_status.pop(doc_id, None)
        del self._documents[doc_id]  # 再删文档
        return True

    # ── 分块 ────────────────────────────────────────────────────

    async def replace_chunks(self, doc_id: str, chunks: list[DocumentChunk]) -> None:
        self._chunks[doc_id] = [copy.deepcopy(c) for c in chunks]

    async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
        chunks = self._chunks.get(doc_id, [])
        ordered = sorted(chunks, key=lambda c: c.ordinal)
        return [copy.deepcopy(c) for c in ordered]

    # ── LightRAG 索引状态 ───────────────────────────────────────

    async def set_lightrag_index_status(
        self, doc_id: str, collection: str, status: str, last_error: str = ""
    ) -> None:
        self._lightrag_status[doc_id] = {
            "doc_id": doc_id,
            "collection": collection,
            "status": status,
            "last_error": last_error,
        }

    async def get_lightrag_index_status(self, doc_id: str) -> dict[str, str] | None:
        value = self._lightrag_status.get(doc_id)
        return copy.deepcopy(value) if value else None

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


    # ── 聊天记录（内存实现：进程重启后丢失，仅用于测试）───────────

    async def add_chat_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list | None = None,
        retrieval_mode: str = "",
    ) -> None:
        pass  # 内存实现不持久化聊天记录

    async def get_chat_messages(self, conversation_id: str) -> list[dict]:
        return []

    async def clear_chat_messages(self, conversation_id: str) -> None:
        pass

    # ── 图谱构建任务持久化（内存实现：进程重启后丢失，仅用于测试）───

    async def upsert_build_job(self, job: dict) -> None:
        pass

    async def list_build_jobs(
        self, collection: str | None = None, limit: int = 20
    ) -> list[dict]:
        return []

    async def mark_interrupted_build_jobs(self) -> int:
        return 0

    # ── Zotero 逻辑镜像 ──────────────────────────────────────────

    async def upsert_zotero_library(self, library: ZoteroLibrary) -> None:
        self._zlibraries[library.library_id] = copy.deepcopy(library)

    async def upsert_zotero_collection(self, collection: ZoteroCollection) -> None:
        self._zcollections[(collection.library_id, collection.collection_key)] = copy.deepcopy(
            collection
        )

    async def upsert_zotero_item(self, item: ZoteroItem) -> None:
        self._zitems[(item.library_id, item.item_key)] = copy.deepcopy(item)

    async def upsert_zotero_attachment(self, attachment: ZoteroAttachment) -> None:
        self._zattachments[(attachment.library_id, attachment.attachment_key)] = copy.deepcopy(
            attachment
        )

    async def set_item_collections(
        self, library_id: str, item_key: str, collection_keys: list[str]
    ) -> None:
        self._zcollection_items = {
            t for t in self._zcollection_items if not (t[0] == library_id and t[2] == item_key)
        }
        for key in collection_keys:
            self._zcollection_items.add((library_id, key, item_key))

    async def replace_item_tags(
        self, library_id: str, item_key: str, tags: list[ZoteroTag]
    ) -> None:
        self._zitem_tags[(library_id, item_key)] = [copy.deepcopy(t) for t in tags]

    async def upsert_zotero_relation(self, relation: ZoteroRelation, library_id: str) -> None:
        self._zrelations.add(
            (
                library_id,
                relation.source_item_key,
                relation.relation_type,
                relation.target_item_key,
            )
        )

    async def list_zotero_items(self, library_id: str | None = None) -> list[ZoteroItem]:
        items = self._zitems.values()
        if library_id is not None:
            items = [i for i in items if i.library_id == library_id]
        ordered = sorted(items, key=lambda i: (i.library_id, i.item_key))
        return [copy.deepcopy(i) for i in ordered]

    async def get_zotero_item(self, library_id: str, item_key: str) -> ZoteroItem | None:
        item = self._zitems.get((library_id, item_key))
        return copy.deepcopy(item) if item is not None else None

    async def list_zotero_attachments(
        self, library_id: str, parent_item_key: str | None = None
    ) -> list[ZoteroAttachment]:
        atts = [a for a in self._zattachments.values() if a.library_id == library_id]
        if parent_item_key is not None:
            atts = [a for a in atts if a.parent_item_key == parent_item_key]
        ordered = sorted(atts, key=lambda a: a.attachment_key)
        return [copy.deepcopy(a) for a in ordered]

    async def list_item_tags(self, library_id: str, item_key: str) -> list[ZoteroTag]:
        tags = self._zitem_tags.get((library_id, item_key), [])
        ordered = sorted(tags, key=lambda t: t.tag)
        return [copy.deepcopy(t) for t in ordered]

    async def get_collection_descendants(
        self, library_id: str, collection_key: str
    ) -> list[str]:
        # 自顶向下 BFS 遍历集合树，含自身。
        if (library_id, collection_key) not in self._zcollections:
            return []
        children: dict[str, list[str]] = {}
        for (lib, ck), coll in self._zcollections.items():
            if lib != library_id:
                continue
            children.setdefault(coll.parent_collection_key, []).append(ck)
        result: list[str] = []
        queue = [collection_key]
        seen: set[str] = set()
        while queue:
            cur = queue.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            result.append(cur)
            queue.extend(children.get(cur, []))
        return result

    async def get_items_in_collections(
        self, library_id: str, collection_keys: list[str]
    ) -> list[str]:
        wanted = set(collection_keys)
        items = {
            t[2]
            for t in self._zcollection_items
            if t[0] == library_id and t[1] in wanted
        }
        return sorted(items)

    async def get_items_with_tag(self, library_id: str, tag: str) -> list[str]:
        items = {
            key[1]
            for key, tags in self._zitem_tags.items()
            if key[0] == library_id and any(t.tag == tag for t in tags)
        }
        return sorted(items)

    # ── 页面级 provenance ────────────────────────────────────────

    async def replace_page_chunks(
        self, document_id: str, page_chunks: list[PageChunk]
    ) -> None:
        self._page_chunks[document_id] = [copy.deepcopy(pc) for pc in page_chunks]

    async def list_page_chunks(self, document_id: str) -> list[PageChunk]:
        pcs = self._page_chunks.get(document_id, [])
        ordered = sorted(pcs, key=lambda pc: pc.page)
        return [copy.deepcopy(pc) for pc in ordered]


__all__ = ["InMemorySourceDocumentStore"]
