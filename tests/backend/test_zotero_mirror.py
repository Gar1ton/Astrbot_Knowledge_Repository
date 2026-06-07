"""Zotero 逻辑镜像 + 制品包字段 + 页面 provenance 的契约测试（接口对换）。

同一组断言同时跑 SQLite 生产实现与内存实现，保证两者行为一致（CONVENTIONS §6）。
覆盖：制品包/origin 新字段、collection 来源标记、Zotero item/attachment/tag/collection 镜像，
作用域解析助手（collection 后代 / 集合内条目 / tag→items）、page_chunks 替换/级联删除。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from core.domain.models import (
    Collection,
    DocumentOrigin,
    PageChunk,
    SourceDocument,
    ZoteroAttachment,
    ZoteroCollection,
    ZoteroItem,
    ZoteroLibrary,
    ZoteroTag,
)
from core.migration_runner import run_migrations
from core.repository.source_store.base import SourceDocumentStore
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore


@pytest.fixture(params=["sqlite", "memory"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[SourceDocumentStore]:
    if request.param == "memory":
        yield InMemorySourceDocumentStore()
        return
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")
    await run_migrations(conn)
    s = SQLiteSourceDocumentStore(conn)
    # documents.collection 是指向 collections(name) 的外键
    await s.upsert_collection(Collection(name="default"))
    yield s
    await conn.close()


def _zotero_doc(doc_id: str = "USER1_ITEM1_PDF1") -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title="Zotero Paper",
        file_path=f"/data/library/{doc_id}/original.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        content_hash="hash1",
        collection="default",
        library_id="USER1",
        zotero_item_key="ITEM1",
        attachment_key="PDF1",
        origin=DocumentOrigin.ZOTERO,
        read_only=True,
        zotero_version=42,
        markdown_rel_path="clean.md",
        pages_rel_path="pages.json",
        converter="pymupdf4llm",
        converter_version="0.0.27",
    )


# ── 制品包 / origin 字段往返 ──────────────────────────────────────


async def test_document_artifact_fields_roundtrip(store: SourceDocumentStore) -> None:
    await store.add_document(_zotero_doc())
    got = await store.get_document("USER1_ITEM1_PDF1")
    assert got is not None
    assert got.library_id == "USER1"
    assert got.zotero_item_key == "ITEM1"
    assert got.attachment_key == "PDF1"
    assert got.origin is DocumentOrigin.ZOTERO
    assert got.read_only is True
    assert got.zotero_version == 42
    assert got.markdown_rel_path == "clean.md"
    assert got.converter == "pymupdf4llm"
    assert got.document_id == got.doc_id  # 语义别名同值


async def test_local_document_defaults_local_origin(store: SourceDocumentStore) -> None:
    doc = SourceDocument(
        doc_id="LOCAL_AB_CD",
        title="Local Upload",
        file_path="/data/library/LOCAL_AB_CD/original.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="default",
    )
    await store.add_document(doc)
    got = await store.get_document("LOCAL_AB_CD")
    assert got is not None
    assert got.origin is DocumentOrigin.LOCAL
    assert got.read_only is False
    assert got.library_id == "LOCAL"


async def test_collection_origin_roundtrip(store: SourceDocumentStore) -> None:
    await store.upsert_collection(
        Collection(
            name="Value Ecology",
            origin=DocumentOrigin.ZOTERO,
            zotero_collection_key="COLL1",
            read_only=True,
        )
    )
    cols = {c.name: c for c in await store.list_collections()}
    assert cols["Value Ecology"].origin is DocumentOrigin.ZOTERO
    assert cols["Value Ecology"].zotero_collection_key == "COLL1"
    assert cols["Value Ecology"].read_only is True


# ── Zotero 镜像 upsert + 读取 ────────────────────────────────────


async def test_zotero_item_and_attachment_mirror(store: SourceDocumentStore) -> None:
    await store.upsert_zotero_library(ZoteroLibrary(library_id="USER1", library_type="user"))
    await store.upsert_zotero_item(
        ZoteroItem(
            item_key="ITEM1",
            library_id="USER1",
            item_type="journalArticle",
            version=42,
            title="Ecological Value",
            creators=["Li, Wei", "Massumi, B."],
            year="2025",
            venue="Journal of Ecology",
            doi="10.1/x",
            raw_zotero_json={"key": "ITEM1"},
        )
    )
    await store.upsert_zotero_attachment(
        ZoteroAttachment(
            attachment_key="PDF1",
            parent_item_key="ITEM1",
            library_id="USER1",
            content_type="application/pdf",
            filename="paper.pdf",
            md5="abc",
        )
    )
    item = await store.get_zotero_item("USER1", "ITEM1")
    assert item is not None
    assert item.creators == ["Li, Wei", "Massumi, B."]
    assert item.year == "2025"
    assert item.raw_zotero_json == {"key": "ITEM1"}
    assert [i.item_key for i in await store.list_zotero_items("USER1")] == ["ITEM1"]
    atts = await store.list_zotero_attachments("USER1", "ITEM1")
    assert len(atts) == 1 and atts[0].md5 == "abc"


async def test_item_tags_replace(store: SourceDocumentStore) -> None:
    await store.replace_item_tags(
        "USER1",
        "ITEM1",
        [ZoteroTag("ITEM1", "ecology", 0), ZoteroTag("ITEM1", "value", 0)],
    )
    assert {t.tag for t in await store.list_item_tags("USER1", "ITEM1")} == {"ecology", "value"}
    # 整体替换
    await store.replace_item_tags("USER1", "ITEM1", [ZoteroTag("ITEM1", "only", 0)])
    assert [t.tag for t in await store.list_item_tags("USER1", "ITEM1")] == ["only"]


# ── 作用域解析助手 ───────────────────────────────────────────────


async def test_collection_descendants_and_items(store: SourceDocumentStore) -> None:
    # 集合树: root -> child -> grandchild
    await store.upsert_zotero_collection(
        ZoteroCollection(collection_key="root", library_id="USER1", name="Root")
    )
    await store.upsert_zotero_collection(
        ZoteroCollection(
            collection_key="child", library_id="USER1", name="Child", parent_collection_key="root"
        )
    )
    await store.upsert_zotero_collection(
        ZoteroCollection(
            collection_key="grand", library_id="USER1", name="Grand", parent_collection_key="child"
        )
    )
    descendants = await store.get_collection_descendants("USER1", "root")
    assert set(descendants) == {"root", "child", "grand"}

    await store.set_item_collections("USER1", "ITEM_A", ["root"])
    await store.set_item_collections("USER1", "ITEM_B", ["grand"])
    items = await store.get_items_in_collections("USER1", descendants)
    assert set(items) == {"ITEM_A", "ITEM_B"}


async def test_get_items_with_tag(store: SourceDocumentStore) -> None:
    await store.replace_item_tags("USER1", "ITEM_A", [ZoteroTag("ITEM_A", "shared", 0)])
    await store.replace_item_tags("USER1", "ITEM_B", [ZoteroTag("ITEM_B", "shared", 0)])
    await store.replace_item_tags("USER1", "ITEM_C", [ZoteroTag("ITEM_C", "other", 0)])
    assert set(await store.get_items_with_tag("USER1", "shared")) == {"ITEM_A", "ITEM_B"}


# ── 页面级 provenance ────────────────────────────────────────────


async def test_page_chunks_replace_and_cascade(store: SourceDocumentStore) -> None:
    await store.add_document(_zotero_doc("USER1_ITEM1_PDF1"))
    await store.replace_page_chunks(
        "USER1_ITEM1_PDF1",
        [
            PageChunk("USER1_ITEM1_PDF1", 1, 0, 100),
            PageChunk("USER1_ITEM1_PDF1", 2, 100, 240),
        ],
    )
    pcs = await store.list_page_chunks("USER1_ITEM1_PDF1")
    assert [(p.page, p.markdown_start_char, p.markdown_end_char) for p in pcs] == [
        (1, 0, 100),
        (2, 100, 240),
    ]
    # 删除文档应级联清空页面表
    assert await store.delete_document("USER1_ITEM1_PDF1") is True
    assert await store.list_page_chunks("USER1_ITEM1_PDF1") == []
