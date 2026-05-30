"""SourceDocumentStore 契约测试（接口对换：注入内存实现，无 I/O）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.domain.models import Collection, DocumentChunk, SourceDocument
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


async def test_add_and_get_document(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1"))
    got = await store.get_document("d1")
    assert got is not None
    assert got.doc_id == "d1"
    assert await store.get_document("missing") is None


async def test_add_duplicate_raises(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1"))
    with pytest.raises(ValueError):
        await store.add_document(_doc("d1"))


async def test_get_returns_copy_not_reference(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1", tags=["a"]))
    got = await store.get_document("d1")
    assert got is not None
    got.tags.append("mutated")
    again = await store.get_document("d1")
    assert again is not None
    assert again.tags == ["a"]


async def test_list_documents_filters_by_collection_and_tag(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.add_document(_doc("d1", collection="x", tags=["t1"]))
    await store.add_document(_doc("d2", collection="x", tags=["t2"]))
    await store.add_document(_doc("d3", collection="y", tags=["t1"]))
    assert {d.doc_id for d in await store.list_documents(collection="x")} == {"d1", "d2"}
    assert {d.doc_id for d in await store.list_documents(tag="t1")} == {"d1", "d3"}
    assert {d.doc_id for d in await store.list_documents(collection="x", tag="t1")} == {"d1"}
    assert len(await store.list_documents()) == 3


async def test_update_document(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1", collection="x"))
    updated = _doc("d1", collection="y", tags=["new"])
    assert await store.update_document(updated) is True
    got = await store.get_document("d1")
    assert got is not None and got.collection == "y" and got.tags == ["new"]
    assert await store.update_document(_doc("missing")) is False


async def test_delete_document_cascades_chunks(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1"))
    await store.replace_chunks("d1", [DocumentChunk("c0", "d1", 0, "text", "h0")])
    assert await store.delete_document("d1") is True
    assert await store.get_document("d1") is None
    assert await store.list_chunks("d1") == []
    assert await store.delete_document("d1") is False


async def test_replace_and_list_chunks_ordered(store: InMemorySourceDocumentStore) -> None:
    await store.add_document(_doc("d1"))
    await store.replace_chunks(
        "d1",
        [
            DocumentChunk("c2", "d1", 2, "t2", "h2"),
            DocumentChunk("c0", "d1", 0, "t0", "h0"),
            DocumentChunk("c1", "d1", 1, "t1", "h1"),
        ],
    )
    assert [c.ordinal for c in await store.list_chunks("d1")] == [0, 1, 2]
    # 整体替换语义：旧分块被覆盖
    await store.replace_chunks("d1", [DocumentChunk("cX", "d1", 0, "tx", "hx")])
    chunks = await store.list_chunks("d1")
    assert len(chunks) == 1 and chunks[0].chunk_id == "cX"


async def test_collection_crud(store: InMemorySourceDocumentStore) -> None:
    await store.upsert_collection(Collection(name="b"))
    await store.upsert_collection(Collection(name="a", description="first"))
    await store.upsert_collection(Collection(name="a", description="updated"))  # upsert
    cols = await store.list_collections()
    assert [c.name for c in cols] == ["a", "b"]
    assert cols[0].description == "updated"
    assert await store.delete_collection("a") is True
    assert await store.delete_collection("a") is False
