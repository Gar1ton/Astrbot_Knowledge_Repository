"""分类管理器实现（managers 层）。

提供集合（Collection）与标签（Tags）的 CRUD 功能，
提供文档手动分类支持，并预留自动打标签（auto-tagging）的 AI 扩展端口。
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.domain.models import Collection
from core.managers.base import BaseCategoryManager

if TYPE_CHECKING:
    from core.repository.source_store.base import SourceDocumentStore


class CategoryManager(BaseCategoryManager):
    """具体的分类与标签管理器。"""

    def __init__(self, *, source_store: SourceDocumentStore) -> None:
        super().__init__()
        self._source_store = source_store

    async def create_collection(self, name: str, description: str = "") -> None:
        now = datetime.now(timezone.utc)
        await self._source_store.upsert_collection(
            Collection(name=name, description=description, created_at=now)
        )
        self.logger.info(f"Collection created/updated: {name}")

    async def delete_collection(self, name: str) -> bool:
        success = await self._source_store.delete_collection(name)
        if success:
            self.logger.info(f"Collection deleted: {name}")
        else:
            self.logger.warning(f"Failed to delete collection (not found): {name}")
        return success

    async def classify_document(
        self, doc_id: str, *, collection: str | None = None, tags: list[str] | None = None
    ) -> bool:
        doc = await self._source_store.get_document(doc_id)
        if doc is None:
            self.logger.warning(f"Failed to classify document (not found): {doc_id}")
            return False

        if collection is not None:
            # 手动重分类语义为单集合归属：清空旧多归属，让 membership 跟随新 primary 重置。
            doc.collection = collection
            doc.collection_keys = []
        if tags is not None:
            doc.tags = tags

        doc.updated_at = datetime.now(timezone.utc)
        success = await self._source_store.update_document(doc)
        if success:
            self.logger.info(f"Document {doc_id} classified successfully.")
        return success

    async def auto_tag_document(self, doc_id: str) -> list[str]:
        # 预留 AI / 自动聚类打标签的 ABC 端口，默认关闭并给出软警告
        warnings.warn(
            "Auto tagging is currently disabled by default. "
            "Please configure an LLM / embedding clustering model in Backlog.",
            UserWarning,
        )
        self.logger.warning(
            f"Auto tagging requested for document {doc_id} "
            f"but is disabled by default."
        )
        return []


__all__ = ["CategoryManager"]
