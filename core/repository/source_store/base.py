"""源文档库接口（repository 层，接口先行）。

定义原件（PDF 等）与集合/分块的持久化契约。生产实现 sqlite.py、测试实现 memory.py 共用本接口。
本层只依赖 domain，不依赖 managers/框架（见 ../README.md）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

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


class SourceDocumentStore(ABC):
    """原件 + 集合 + 分块的仓储。

    标识约定：外部用稳定 doc_id（UUID）；同一 (collection) 下 name 唯一由调用方语义保证。
    同步顺序约定写在涉及多表的方法 docstring 中。
    """

    # ── 集合 ────────────────────────────────────────────────────

    @abstractmethod
    async def upsert_collection(self, collection: Collection) -> None:
        """新建或更新集合（按 name 主键 upsert）。"""
        ...

    @abstractmethod
    async def list_collections(self) -> list[Collection]:
        """列出全部集合，按 name 升序。"""
        ...

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """删除集合本身（不级联删其文档）。返回 False 表示 name 不存在。"""
        ...

    @abstractmethod
    async def move_documents_to_collection(self, from_name: str, to_name: str) -> int:
        """将所有属于 from_name 的文档批量迁移到 to_name。返回迁移文档数量。"""
        ...

    @abstractmethod
    async def list_pending_reindex_documents(self) -> list[SourceDocument]:
        """列出所有标记为待重建索引（needs_reindex=True）的文档。"""
        ...

    # ── 文档 ────────────────────────────────────────────────────

    @abstractmethod
    async def add_document(self, document: SourceDocument) -> None:
        """登记一个原件。doc_id 已存在视为重复，由实现抛错（调用方应先查重或用 update）。"""
        ...

    @abstractmethod
    async def get_document(self, doc_id: str) -> SourceDocument | None:
        """按 doc_id 取一条；不存在返回 None（非异常）。"""
        ...

    @abstractmethod
    async def list_documents(
        self, collection: str | None = None, tag: str | None = None
    ) -> list[SourceDocument]:
        """列出文档，可按集合与单个标签过滤（两者为 AND）。无过滤则返回全部，按 created_at 升序。"""
        ...

    @abstractmethod
    async def update_document(self, document: SourceDocument) -> bool:
        """整体更新一个文档（含 collection/tags/content_hash）。返回 False 表示 doc_id 不存在。"""
        ...

    @abstractmethod
    async def delete_document(self, doc_id: str) -> bool:
        """删除文档及其分块。同步顺序：先删 chunks → 再删文档。返回 False 表示 doc_id 不存在。"""
        ...

    # ── 分块 ────────────────────────────────────────────────────

    @abstractmethod
    async def replace_chunks(self, doc_id: str, chunks: list[DocumentChunk]) -> None:
        """以新分块整体替换某文档的旧分块。同步顺序：先删该 doc 旧 chunks → 再插入新 chunks。"""
        ...

    @abstractmethod
    async def list_chunks(self, doc_id: str) -> list[DocumentChunk]:
        """列出某文档的分块，按 ordinal 升序。文档不存在或无分块返回空列表。"""
        ...

    # ── LightRAG 索引状态 ───────────────────────────────────────

    @abstractmethod
    async def set_lightrag_index_status(
        self, doc_id: str, collection: str, status: str, last_error: str = ""
    ) -> None:
        """设置独立 LightRAG 索引状态；不得复用 needs_reindex。"""
        ...

    @abstractmethod
    async def get_lightrag_index_status(self, doc_id: str) -> dict[str, str] | None:
        """读取文档的独立 LightRAG 索引状态。"""
        ...

    # ── 文档/集合笔记 ───────────────────────────────────────────

    @abstractmethod
    async def list_scoped_notes(self, scope_type: str, scope_key: str) -> list[ScopedNote]:
        """列出某个 document/collection 作用域下的全部笔记，按更新时间倒序。"""
        ...

    @abstractmethod
    async def add_scoped_note(self, note: ScopedNote) -> None:
        """新增一条 Zotero-shaped scoped note。id 已存在时由实现抛错。"""
        ...

    @abstractmethod
    async def update_scoped_note(self, note: ScopedNote) -> bool:
        """整体更新一条笔记。返回 False 表示 note id 不存在。"""
        ...

    @abstractmethod
    async def get_scoped_note(self, note_id: str) -> ScopedNote | None:
        """按 note id 获取笔记；不存在返回 None。"""
        ...

    # ── 聊天记录 ─────────────────────────────────────────────────

    @abstractmethod
    async def add_chat_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list | None = None,
        retrieval_mode: str = "",
        locked: bool = False,
    ) -> None:
        """追加一条聊天记录（role='user'|'assistant'）。"""
        ...

    @abstractmethod
    async def get_chat_messages(self, conversation_id: str) -> list[dict]:
        """返回某会话的全部消息，按 id 升序。"""
        ...

    @abstractmethod
    async def set_chat_message_locked(
        self, conversation_id: str, msg_idx: int, locked: bool
    ) -> dict | None:
        """按前端消息序号设置锁定状态；不存在返回 None。"""
        ...

    @abstractmethod
    async def clear_chat_messages(
        self, conversation_id: str, preserve_locked: bool = False
    ) -> None:
        """删除某会话消息；preserve_locked=True 时保留已锁定消息。"""
        ...

    # ── 控制台上下文状态 ─────────────────────────────────────────

    @abstractmethod
    async def get_console_scope_state(
        self, scope_type: str, scope_key: str
    ) -> ConsoleScopeState | None:
        """获取某个 console scope 的右侧上下文状态。"""
        ...

    @abstractmethod
    async def upsert_console_scope_state(self, state: ConsoleScopeState) -> None:
        """创建或更新某个 console scope 的右侧上下文状态。"""
        ...

    # ── 同步状态 ──────────────────────────────────────────────────

    @abstractmethod
    async def get_sync_record(self, doc_id: str, target: SyncTargetKind) -> SyncRecord | None:
        """获取指定文档在指定同步目标上的同步账目；不存在返回 None。"""
        ...

    @abstractmethod
    async def upsert_sync_record(self, record: SyncRecord) -> None:
        """登记或更新同步账目（以 doc_id 与 target 为组合键进行 upsert）。"""
        ...

    @abstractmethod
    async def list_sync_records(self, target: SyncTargetKind | None = None) -> list[SyncRecord]:
        """列出同步记录，可按目标进行过滤；按 synced_at 升序。"""
        ...

    # ── 图谱构建任务持久化 ─────────────────────────────────────────

    @abstractmethod
    async def upsert_build_job(self, job: dict) -> None:
        """持久化或更新构建任务快照（以 job_id 为主键 upsert）。"""
        ...

    @abstractmethod
    async def list_build_jobs(
        self, collection: str | None = None, limit: int = 20
    ) -> list[dict]:
        """列出构建任务历史；可按 collection 过滤，按创建时间倒序，最多返回 limit 条。"""
        ...

    @abstractmethod
    async def mark_interrupted_build_jobs(self) -> int:
        """将所有 status=queued/running 的任务标记为 interrupted；返回受影响行数。"""
        ...

    # ── Zotero 逻辑镜像（单向 Pull）───────────────────────────────
    #
    # 这些方法持久化 Zotero 上游的只读镜像（含本地上传的合成 LOCAL 库）。
    # 标识约定：Zotero key 仅在单个 library 内稳定，故所有方法都以 (library_id, key) 复合定位。

    @abstractmethod
    async def upsert_zotero_library(self, library: ZoteroLibrary) -> None:
        """按 library_id 主键 upsert 一个库（含 LOCAL 合成库）。"""
        ...

    @abstractmethod
    async def upsert_zotero_collection(self, collection: ZoteroCollection) -> None:
        """按 (library_id, collection_key) upsert 一个 Zotero 集合节点（树状）。"""
        ...

    @abstractmethod
    async def upsert_zotero_item(self, item: ZoteroItem) -> None:
        """按 (library_id, item_key) upsert 一个条目（归一化字段 + raw json）。"""
        ...

    @abstractmethod
    async def upsert_zotero_attachment(self, attachment: ZoteroAttachment) -> None:
        """按 (library_id, attachment_key) upsert 一个附件。"""
        ...

    @abstractmethod
    async def set_item_collections(
        self, library_id: str, item_key: str, collection_keys: list[str]
    ) -> None:
        """整体替换某条目的集合归属（先删该 item 旧映射 → 再插入新集合 key 列表）。"""
        ...

    @abstractmethod
    async def replace_item_tags(
        self, library_id: str, item_key: str, tags: list[ZoteroTag]
    ) -> None:
        """整体替换某条目的标签集合（先删旧 → 再插入）。"""
        ...

    @abstractmethod
    async def upsert_zotero_relation(self, relation: ZoteroRelation, library_id: str) -> None:
        """upsert 一条条目间关系（复合键去重）。"""
        ...

    @abstractmethod
    async def list_zotero_items(self, library_id: str | None = None) -> list[ZoteroItem]:
        """列出条目，可按库过滤；按 (library_id, item_key) 升序。"""
        ...

    @abstractmethod
    async def get_zotero_item(self, library_id: str, item_key: str) -> ZoteroItem | None:
        """取一个条目；不存在返回 None。"""
        ...

    @abstractmethod
    async def list_zotero_attachments(
        self, library_id: str, parent_item_key: str | None = None
    ) -> list[ZoteroAttachment]:
        """列出附件，可按父条目过滤。"""
        ...

    @abstractmethod
    async def list_item_tags(self, library_id: str, item_key: str) -> list[ZoteroTag]:
        """列出某条目的标签。"""
        ...

    @abstractmethod
    async def get_collection_descendants(
        self, library_id: str, collection_key: str
    ) -> list[str]:
        """返回某集合及其所有后代集合的 collection_key（含自身）。

        Zotero 集合是树状；作用域检索 collection scope 需要含后代（design §5）。
        """
        ...

    @abstractmethod
    async def get_items_in_collections(
        self, library_id: str, collection_keys: list[str]
    ) -> list[str]:
        """返回属于给定集合（任一）的去重 item_key 列表。"""
        ...

    @abstractmethod
    async def get_items_with_tag(self, library_id: str, tag: str) -> list[str]:
        """返回带指定标签的 item_key 列表。"""
        ...

    # ── 页面级 provenance（clean.md 字符偏移）────────────────────

    @abstractmethod
    async def replace_page_chunks(
        self, document_id: str, page_chunks: list[PageChunk]
    ) -> None:
        """整体替换某文档的页面偏移表（先删旧 → 再插入）。"""
        ...

    @abstractmethod
    async def list_page_chunks(self, document_id: str) -> list[PageChunk]:
        """列出某文档的页面偏移表，按 page 升序。"""
        ...


__all__ = ["SourceDocumentStore"]
