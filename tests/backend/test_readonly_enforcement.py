"""service 层只读强制：Zotero 同步来源（origin=zotero）禁止用户侧删除/改/移动/删集合。"""
from __future__ import annotations

import pytest

from core.api import KnowledgeRepositoryApi, ReadOnlyError
from core.config import Config
from core.domain.models import Collection, DocumentOrigin, SourceDocument
from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore


def _zotero_doc() -> SourceDocument:
    return SourceDocument(
        doc_id="1_ITEM_ATT",
        title="Synced",
        file_path="/x/original.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="Zotero",
        library_id="1",
        zotero_item_key="ITEM",
        attachment_key="ATT",
        origin=DocumentOrigin.ZOTERO,
        read_only=True,
    )


def _local_doc() -> SourceDocument:
    return SourceDocument(
        doc_id="LOCAL_AA_BB",
        title="Local",
        file_path="/x/original.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="default",
    )


async def _api() -> tuple[KnowledgeRepositoryApi, InMemorySourceDocumentStore]:
    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="default"))
    await store.upsert_collection(Collection(name="_uncategorized"))
    await store.upsert_collection(
        Collection(name="Zotero", origin=DocumentOrigin.ZOTERO, read_only=True)
    )
    api = KnowledgeRepositoryApi(
        source_store=store, kb_reader=InMemoryKnowledgeBaseReader({}), config=Config({})
    )
    return api, store


async def test_delete_zotero_document_rejected() -> None:
    api, store = await _api()
    await store.add_document(_zotero_doc())
    with pytest.raises(ReadOnlyError):
        await api.delete_document("1_ITEM_ATT")
    assert await store.get_document("1_ITEM_ATT") is not None  # 未删除


async def test_classify_zotero_document_rejected() -> None:
    api, store = await _api()
    await store.add_document(_zotero_doc())
    with pytest.raises(ReadOnlyError):
        await api.classify_document("1_ITEM_ATT", collection="default")


async def test_delete_zotero_collection_rejected() -> None:
    api, _ = await _api()
    with pytest.raises(ReadOnlyError):
        await api.delete_collection("Zotero")


async def test_local_document_and_collection_still_mutable() -> None:
    api, store = await _api()
    await store.add_document(_local_doc())
    # 本地文档可分类、可删除；手动集合可删除
    assert await api.classify_document("LOCAL_AA_BB", tags=["x"]) is True
    assert await api.delete_document("LOCAL_AA_BB") is True
    await store.upsert_collection(Collection(name="manual"))
    assert await api.delete_collection("manual") is True
