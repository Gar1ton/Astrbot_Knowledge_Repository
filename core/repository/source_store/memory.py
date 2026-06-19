"""源文档库的内存实现（无 I/O，供接口对换测试）。

行为与 sqlite.py 应一致，仅以内存 dict 持久化。深拷贝进出，避免调用方持有内部引用造成隐式改动。
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.repository.source_store.base import SourceDocumentStore


def _new_local_coll_key() -> str:
    """为本地集合生成稳定唯一 coll_key（与 sqlite 实现一致）。"""
    return "L" + uuid.uuid4().hex

if TYPE_CHECKING:
    from core.domain.models import (
        Collection,
        ConsoleScopeState,
        DocumentChunk,
        PageChunk,
        ScopedNote,
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
        self._collections: dict[str, Collection] = {}  # keyed by coll_key
        self._doc_collections: dict[str, list[str]] = {}  # doc_id → coll_keys
        self._documents: dict[str, SourceDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._sync_records: dict[tuple[str, SyncTargetKind], SyncRecord] = {}
        self._lightrag_status: dict[str, dict[str, str]] = {}
        self._build_jobs: dict[str, dict] = {}
        # Zotero 镜像 + 页面 provenance（key 均含 library_id 命名空间）
        self._zlibraries: dict[str, ZoteroLibrary] = {}
        self._zcollections: dict[tuple[str, str], ZoteroCollection] = {}
        self._zitems: dict[tuple[str, str], ZoteroItem] = {}
        self._zattachments: dict[tuple[str, str], ZoteroAttachment] = {}
        self._zcollection_items: set[tuple[str, str, str]] = set()  # (lib, coll_key, item_key)
        self._zitem_tags: dict[tuple[str, str], list[ZoteroTag]] = {}
        self._zrelations: set[tuple[str, str, str, str]] = set()
        self._page_chunks: dict[str, list[PageChunk]] = {}
        self._notes: dict[str, ScopedNote] = {}
        self._chat_history: dict[str, list[dict]] = {}
        self._chat_id_seq = 1
        self._console_scope_states: dict[tuple[str, str], ConsoleScopeState] = {}

    # ── 集合（树形 + 多归属）────────────────────────────────────

    async def upsert_collection(self, collection: Collection) -> None:
        coll_key = collection.coll_key
        if not coll_key:
            # 兼容旧调用：按 (name, parent_key) 复用现有 key，否则发放新 local key。
            match = next(
                (
                    c.coll_key
                    for c in self._collections.values()
                    if c.name == collection.name and c.parent_key == collection.parent_key
                ),
                None,
            )
            coll_key = match or _new_local_coll_key()
            collection.coll_key = coll_key
        self._collections[coll_key] = copy.deepcopy(collection)

    async def get_collection(self, coll_key: str) -> Collection | None:
        c = self._collections.get(coll_key)
        return copy.deepcopy(c) if c is not None else None

    async def get_collection_by_name(self, name: str) -> Collection | None:
        matches = sorted(
            (c for c in self._collections.values() if c.name == name),
            key=lambda c: c.coll_key,
        )
        return copy.deepcopy(matches[0]) if matches else None

    async def list_collections(self) -> list[Collection]:
        return [copy.deepcopy(c) for c in sorted(self._collections.values(), key=lambda c: c.name)]

    async def get_local_collection_descendants(self, coll_key: str) -> list[str]:
        if coll_key not in self._collections:
            return []
        result = [coll_key]
        frontier = [coll_key]
        while frontier:
            current = frontier.pop()
            for c in self._collections.values():
                if c.parent_key == current and c.coll_key not in result:
                    result.append(c.coll_key)
                    frontier.append(c.coll_key)
        return result

    async def delete_collection(self, name: str) -> bool:
        match = next((k for k, c in self._collections.items() if c.name == name), None)
        if match is None:
            return False
        del self._collections[match]
        return True

    async def delete_collection_by_key(self, coll_key: str) -> bool:
        return self._collections.pop(coll_key, None) is not None

    async def move_documents_to_collection(self, from_name: str, to_name: str) -> int:
        from_coll = await self.get_collection_by_name(from_name)
        to_coll = await self.get_collection_by_name(to_name)
        count = 0
        for doc in self._documents.values():
            if doc.collection == from_name:
                doc.collection = to_name
                count += 1
        if from_coll and to_coll:
            for doc_id, keys in self._doc_collections.items():
                self._doc_collections[doc_id] = list(
                    dict.fromkeys(
                        to_coll.coll_key if k == from_coll.coll_key else k for k in keys
                    )
                )
        return count

    # ── 文档多归属 ──────────────────────────────────────────────

    async def set_document_collections(self, doc_id: str, coll_keys: list[str]) -> None:
        self._doc_collections[doc_id] = list(dict.fromkeys(coll_keys))

    async def list_document_collection_keys(self, doc_id: str) -> list[str]:
        return list(self._doc_collections.get(doc_id, []))

    async def list_documents_by_collection_key(
        self, coll_key: str, *, descendants: bool = False
    ) -> list[SourceDocument]:
        keys = (
            set(await self.get_local_collection_descendants(coll_key))
            if descendants
            else {coll_key}
        )
        matched = [
            d
            for d in self._documents.values()
            if keys & set(self._doc_collections.get(d.doc_id, []))
        ]
        ordered = sorted(matched, key=lambda d: (d.created_at is None, d.created_at, d.doc_id))
        return [self._with_keys(d) for d in ordered]

    def _with_keys(self, doc: SourceDocument) -> SourceDocument:
        """返回带多归属 collection_keys 回填的深拷贝。"""
        out = copy.deepcopy(doc)
        out.collection_keys = list(self._doc_collections.get(doc.doc_id, []))
        return out

    async def _sync_doc_memberships(self, document: SourceDocument) -> None:
        keys = list(dict.fromkeys(document.collection_keys))
        if not keys and document.collection:
            primary = await self.get_collection_by_name(document.collection)
            if primary:
                keys = [primary.coll_key]
        self._doc_collections[document.doc_id] = keys

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
        await self._sync_doc_memberships(document)

    async def get_document(self, doc_id: str) -> SourceDocument | None:
        doc = self._documents.get(doc_id)
        return self._with_keys(doc) if doc is not None else None

    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        docs = self._documents.values()
        if collection is not None:
            docs = [d for d in docs if d.collection == collection]
        if tag is not None:
            docs = [d for d in docs if tag in d.tags]
        ordered = sorted(docs, key=lambda d: (d.created_at is None, d.created_at, d.doc_id))
        return [self._with_keys(d) for d in ordered]

    async def update_document(self, document: SourceDocument) -> bool:
        if document.doc_id not in self._documents:
            return False
        self._documents[document.doc_id] = copy.deepcopy(document)
        await self._sync_doc_memberships(document)
        return True

    async def delete_document(self, doc_id: str) -> bool:
        if doc_id not in self._documents:
            return False
        self._chunks.pop(doc_id, None)  # 先删分块
        self._doc_collections.pop(doc_id, None)
        self._page_chunks.pop(doc_id, None)
        self._notes = {
            note_id: note
            for note_id, note in self._notes.items()
            if note.scope_type != "document" or note.scope_key != doc_id
        }
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


    # ── 文档/集合笔记 ───────────────────────────────────────────

    async def list_scoped_notes(self, scope_type: str, scope_key: str) -> list[ScopedNote]:
        notes = [
            n
            for n in self._notes.values()
            if n.scope_type == scope_type and n.scope_key == scope_key
        ]
        ordered = sorted(
            notes,
            key=lambda n: (n.updated_at is None, n.updated_at, n.created_at, n.id),
            reverse=True,
        )
        return [copy.deepcopy(n) for n in ordered]

    async def add_scoped_note(self, note: ScopedNote) -> None:
        if note.id in self._notes:
            raise ValueError(f"duplicate note id: {note.id}")
        now = datetime.now(timezone.utc)
        stored = copy.deepcopy(note)
        stored.created_at = stored.created_at or now
        stored.updated_at = stored.updated_at or stored.created_at
        self._notes[stored.id] = stored

    async def update_scoped_note(self, note: ScopedNote) -> bool:
        if note.id not in self._notes:
            return False
        stored = copy.deepcopy(note)
        stored.updated_at = stored.updated_at or datetime.now(timezone.utc)
        self._notes[stored.id] = stored
        return True

    async def get_scoped_note(self, note_id: str) -> ScopedNote | None:
        note = self._notes.get(note_id)
        return copy.deepcopy(note) if note is not None else None

    # ── 聊天记录（内存实现：进程重启后丢失，仅用于测试）───────────

    async def add_chat_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list | None = None,
        retrieval_mode: str = "",
        locked: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        message = {
            "id": self._chat_id_seq,
            "role": role,
            "content": content,
            "sources": copy.deepcopy(sources or []),
            "retrieval_mode": retrieval_mode,
            "created_at": now,
            "locked": bool(locked),
            "locked_at": now if locked else None,
            "updated_at": now,
        }
        self._chat_id_seq += 1
        self._chat_history.setdefault(conversation_id, []).append(message)

    async def get_chat_messages(self, conversation_id: str) -> list[dict]:
        return copy.deepcopy(self._chat_history.get(conversation_id, []))

    async def set_chat_message_locked(
        self, conversation_id: str, msg_idx: int, locked: bool
    ) -> dict | None:
        messages = self._chat_history.get(conversation_id, [])
        if msg_idx < 0 or msg_idx >= len(messages):
            return None
        now = datetime.now(timezone.utc).isoformat()
        messages[msg_idx]["locked"] = bool(locked)
        messages[msg_idx]["locked_at"] = now if locked else None
        messages[msg_idx]["updated_at"] = now
        return copy.deepcopy(messages[msg_idx])

    async def clear_chat_messages(
        self, conversation_id: str, preserve_locked: bool = False
    ) -> None:
        if not preserve_locked:
            self._chat_history.pop(conversation_id, None)
            return
        self._chat_history[conversation_id] = [
            m for m in self._chat_history.get(conversation_id, []) if m.get("locked")
        ]

    # ── 控制台上下文状态 ─────────────────────────────────────────

    async def get_console_scope_state(
        self, scope_type: str, scope_key: str
    ) -> ConsoleScopeState | None:
        state = self._console_scope_states.get((scope_type, scope_key))
        return copy.deepcopy(state) if state is not None else None

    async def upsert_console_scope_state(self, state: ConsoleScopeState) -> None:
        stored = copy.deepcopy(state)
        stored.updated_at = stored.updated_at or datetime.now(timezone.utc)
        self._console_scope_states[(stored.scope_type, stored.scope_key)] = stored

    # ── 图谱构建任务持久化（内存实现：进程重启后丢失，仅用于测试）───

    async def upsert_build_job(self, job: dict) -> None:
        stored = copy.deepcopy(job)
        stored.setdefault("created_at", stored.get("started_at", ""))
        self._build_jobs[str(stored["job_id"])] = stored

    async def list_build_jobs(
        self, collection: str | None = None, limit: int = 20
    ) -> list[dict]:
        jobs = list(self._build_jobs.values())
        if collection is not None:
            jobs = [job for job in jobs if job.get("collection") == collection]
        jobs.sort(key=lambda job: str(job.get("created_at") or ""), reverse=True)
        return [copy.deepcopy(job) for job in jobs[:limit]]

    async def get_latest_resumable_build_job(self) -> dict | None:
        jobs = [
            job for job in self._build_jobs.values() if job.get("status") == "paused"
        ]
        if not jobs:
            return None
        jobs.sort(key=lambda job: str(job.get("created_at") or ""), reverse=True)
        return copy.deepcopy(jobs[0])

    async def mark_interrupted_build_jobs(self) -> int:
        count = 0
        for job in self._build_jobs.values():
            if job.get("status") in {"queued", "running", "pause_requested"}:
                job["status"] = "interrupted"
                job["stage"] = "interrupted"
                count += 1
        return count

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
