"""SourceDocumentStore 契约测试（接口对换：注入内存实现，无 I/O）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.domain.models import (
    Collection,
    ConsoleScopeState,
    DocumentChunk,
    ScopedNote,
    SourceDocument,
)
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


async def test_scoped_notes_chat_lock_and_console_state(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.add_scoped_note(
        ScopedNote(
            id="n1",
            scope_type="document",
            scope_key="d1",
            content="plain note",
            note_html="<p>plain note</p>",
            doc_id="d1",
            parent_item_key="ITEM1",
            raw_zotero_json={"itemType": "note", "note": "<p>plain note</p>"},
        )
    )
    notes = await store.list_scoped_notes("document", "d1")
    assert len(notes) == 1
    assert notes[0].raw_zotero_json["itemType"] == "note"

    notes[0].content = "updated"
    assert await store.update_scoped_note(notes[0]) is True
    got = await store.get_scoped_note("n1")
    assert got is not None and got.content == "updated"

    await store.add_chat_message("conv", "user", "q")
    await store.add_chat_message("conv", "assistant", "a")
    locked = await store.set_chat_message_locked("conv", 1, True)
    assert locked is not None and locked["locked"] is True
    await store.clear_chat_messages("conv", preserve_locked=True)
    messages = await store.get_chat_messages("conv")
    assert [(m["role"], m["locked"]) for m in messages] == [("assistant", True)]

    await store.upsert_console_scope_state(
        ConsoleScopeState(
            scope_type="collection",
            scope_key="papers",
            selected_collection="papers",
            selected_doc_id="d1",
            note_doc_id="d1",
            payload={"right": "notes"},
        )
    )
    state = await store.get_console_scope_state("collection", "papers")
    assert state is not None
    assert state.selected_doc_id == "d1"
    assert state.payload == {"right": "notes"}


# ── 统一多归属集合树（v0.26.3）────────────────────────────────────


async def _build_tree(store: InMemorySourceDocumentStore) -> dict[str, str]:
    """建一棵 root → child → grand 的本地集合树，返回 name→coll_key。"""
    keys: dict[str, str] = {}
    parent = ""
    for name in ("root", "child", "grand"):
        c = Collection(name=name, parent_key=parent)
        await store.upsert_collection(c)
        keys[name] = c.coll_key  # upsert 回填 coll_key
        parent = c.coll_key
    return keys


async def test_upsert_collection_backfills_coll_key(store: InMemorySourceDocumentStore) -> None:
    c = Collection(name="solo")
    await store.upsert_collection(c)
    assert c.coll_key.startswith("L")
    fetched = await store.get_collection(c.coll_key)
    assert fetched is not None and fetched.name == "solo"
    assert (await store.get_collection_by_name("solo")).coll_key == c.coll_key


async def test_same_name_under_different_parents(store: InMemorySourceDocumentStore) -> None:
    a = Collection(name="A")
    await store.upsert_collection(a)
    b = Collection(name="B")
    await store.upsert_collection(b)
    # 两个不同父下的同名子集合
    s1 = Collection(name="Methods", parent_key=a.coll_key)
    s2 = Collection(name="Methods", parent_key=b.coll_key)
    await store.upsert_collection(s1)
    await store.upsert_collection(s2)
    assert s1.coll_key != s2.coll_key
    assert len([c for c in await store.list_collections() if c.name == "Methods"]) == 2


async def test_local_collection_descendants(store: InMemorySourceDocumentStore) -> None:
    keys = await _build_tree(store)
    assert set(await store.get_local_collection_descendants(keys["root"])) == set(keys.values())
    assert set(await store.get_local_collection_descendants(keys["child"])) == {
        keys["child"],
        keys["grand"],
    }
    assert await store.get_local_collection_descendants("missing") == []


async def test_multi_membership_and_scoped_listing(store: InMemorySourceDocumentStore) -> None:
    keys = await _build_tree(store)
    extra = Collection(name="extra")
    await store.upsert_collection(extra)

    # d1 在 child；d2 在 grand；d3 多归属 child + extra
    d1 = _doc("d1")
    d1.collection_keys = [keys["child"]]
    await store.add_document(d1)
    d2 = _doc("d2")
    d2.collection_keys = [keys["grand"]]
    await store.add_document(d2)
    d3 = _doc("d3")
    d3.collection_keys = [keys["child"], extra.coll_key]
    await store.add_document(d3)

    # 本级：child 只含 d1, d3
    assert {d.doc_id for d in await store.list_documents_by_collection_key(keys["child"])} == {
        "d1",
        "d3",
    }
    # 含后代：root 含 child+grand 的全部 = d1, d2, d3
    assert {
        d.doc_id
        for d in await store.list_documents_by_collection_key(keys["root"], descendants=True)
    } == {"d1", "d2", "d3"}
    # 多归属真相源回填
    assert set((await store.get_document("d3")).collection_keys) == {keys["child"], extra.coll_key}
    assert set(await store.list_document_collection_keys("d3")) == {keys["child"], extra.coll_key}

    # 整体替换归属
    await store.set_document_collections("d3", [extra.coll_key])
    assert await store.list_document_collection_keys("d3") == [extra.coll_key]
    assert {d.doc_id for d in await store.list_documents_by_collection_key(keys["child"])} == {"d1"}


# ── 正文精确命中（search_exact_mentions）契约 ─────────────────────────
#
# 全部用中性占位词（EXACT_TERM_A / ROOT_SCOPE_A / CHILD_SCOPE_B / SIBLING_SCOPE_C），
# 不含任何真实关键词、集合名或论文信息。


async def _seed_exact_corpus(store: InMemorySourceDocumentStore) -> dict[str, str]:
    """建 ROOT_SCOPE_A → CHILD_SCOPE_B 树 + 同级 SIBLING_SCOPE_C，正文含占位词、标题不含。"""
    root = Collection(name="ROOT_SCOPE_A")
    await store.upsert_collection(root)
    child = Collection(name="CHILD_SCOPE_B", parent_key=root.coll_key)
    await store.upsert_collection(child)
    sibling = Collection(name="SIBLING_SCOPE_C")
    await store.upsert_collection(sibling)

    child_doc = _doc("doc-child", collection="CHILD_SCOPE_B")
    child_doc.collection_keys = [child.coll_key]
    await store.add_document(child_doc)
    await store.replace_chunks(
        "doc-child",
        [DocumentChunk("ch-0", "doc-child", 0, "intro mentions EXACT_TERM_A in body", "h0")],
    )

    sib_doc = _doc("doc-sibling", collection="SIBLING_SCOPE_C")
    sib_doc.collection_keys = [sibling.coll_key]
    await store.add_document(sib_doc)
    await store.replace_chunks(
        "doc-sibling",
        [DocumentChunk("sb-0", "doc-sibling", 0, "another note about EXACT_TERM_A here", "h1")],
    )
    return {"root": root.coll_key, "child": child.coll_key, "sibling": sibling.coll_key}


async def test_exact_mentions_global_finds_body_only_term(
    store: InMemorySourceDocumentStore,
) -> None:
    await _seed_exact_corpus(store)
    hits = await store.search_exact_mentions(["EXACT_TERM_A"], None)
    # 标题里没有该词（title-doc-child），仍能靠正文命中——杜绝「metadata 空就判没有」。
    assert {h["doc_id"] for h in hits} == {"doc-child", "doc-sibling"}
    assert all("EXACT_TERM_A" not in h["title"] for h in hits)
    assert all("EXACT_TERM_A".lower() in h["matched_terms"] for h in hits)


async def test_exact_mentions_parent_scope_covers_subtree(
    store: InMemorySourceDocumentStore,
) -> None:
    keys = await _seed_exact_corpus(store)
    hits = await store.search_exact_mentions(["EXACT_TERM_A"], keys["root"])
    # 指定父集合 → 覆盖子集合的正文命中，但不含树外的 SIBLING_SCOPE_C。
    assert {h["doc_id"] for h in hits} == {"doc-child"}


async def test_exact_mentions_child_scope_excludes_siblings(
    store: InMemorySourceDocumentStore,
) -> None:
    keys = await _seed_exact_corpus(store)
    child_hits = await store.search_exact_mentions(["EXACT_TERM_A"], keys["child"])
    assert {h["doc_id"] for h in child_hits} == {"doc-child"}
    sibling_hits = await store.search_exact_mentions(["EXACT_TERM_A"], keys["sibling"])
    assert {h["doc_id"] for h in sibling_hits} == {"doc-sibling"}


async def test_exact_mentions_no_hit_and_short_terms(
    store: InMemorySourceDocumentStore,
) -> None:
    await _seed_exact_corpus(store)
    assert await store.search_exact_mentions(["MISSING_TERM_Z"], None) == []
    # 过短词被丢弃 → 空 terms → 空结果（不退化为全表）。
    assert await store.search_exact_mentions(["a"], None) == []
