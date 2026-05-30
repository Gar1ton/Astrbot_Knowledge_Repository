"""CategoryManager 单元测试。

验证集合 CRUD 动作、文档手动分类流转以及预留自动分类端口的行为符合预期。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.domain.models import SourceDocument
from core.managers.category_manager import CategoryManager
from core.repository.source_store.memory import InMemorySourceDocumentStore


def _doc(doc_id: str, collection: str = "default", tags: list[str] | None = None) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"title-{doc_id}",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        content_hash=f"hash-{doc_id}",
        collection=collection,
        tags=list(tags or []),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def store() -> InMemorySourceDocumentStore:
    return InMemorySourceDocumentStore()


@pytest.fixture
def manager(store: InMemorySourceDocumentStore) -> CategoryManager:
    return CategoryManager(source_store=store)


async def test_collection_crud_via_manager(
    manager: CategoryManager,
    store: InMemorySourceDocumentStore,
) -> None:
    await manager.create_collection("tech", "Technology Papers")
    cols = await store.list_collections()
    assert len(cols) == 1
    assert cols[0].name == "tech"
    assert cols[0].description == "Technology Papers"

    assert await manager.delete_collection("tech") is True
    cols_after = await store.list_collections()
    assert len(cols_after) == 0


async def test_document_classification(
    manager: CategoryManager,
    store: InMemorySourceDocumentStore,
) -> None:
    # 登记初始文档
    await store.add_document(_doc("d1", collection="default", tags=["t1"]))

    # 手动分类更改集合
    assert await manager.classify_document("d1", collection="papers") is True
    doc = await store.get_document("d1")
    assert doc is not None
    assert doc.collection == "papers"
    assert doc.tags == ["t1"]

    # 手动分类更改标签
    assert await manager.classify_document("d1", tags=["transformer"]) is True
    doc = await store.get_document("d1")
    assert doc is not None
    assert doc.collection == "papers"
    assert doc.tags == ["transformer"]

    # 针对不存在的文档分类返回 False
    assert await manager.classify_document("missing", collection="papers") is False


async def test_auto_tagging_raises_warning(manager: CategoryManager) -> None:
    # 预留 AI / 自动打标签接口，应当触发用户软警告并回空列表
    with pytest.warns(UserWarning, match="Auto tagging is currently disabled"):
        tags = await manager.auto_tag_document("d1")
        assert tags == []
