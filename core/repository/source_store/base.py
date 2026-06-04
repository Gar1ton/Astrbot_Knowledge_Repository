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
        DocumentChunk,
        SourceDocument,
        SyncRecord,
        SyncTargetKind,
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


__all__ = ["SourceDocumentStore"]
