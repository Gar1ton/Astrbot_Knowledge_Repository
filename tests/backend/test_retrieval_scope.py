"""作用域检索测试：resolve_scope（item/collection 后代/tag/library）+ 跨通道硬过滤 + 图谱越界。"""
from __future__ import annotations

import pytest

from core.config import Config
from core.domain.models import (
    Collection,
    DocumentChunk,
    DocumentLifecycle,
    DocumentOrigin,
    SourceDocument,
    ZoteroCollection,
    ZoteroTag,
)
from core.pipelines.retrieval_orchestrator import (
    SCOPE_COLLECTION,
    SCOPE_ITEM,
    SCOPE_LIBRARY,
    SCOPE_TAG,
    RetrievalOrchestrator,
    RetrievalScope,
)
from core.repository.kb_reader.base import KnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore

LIB = "1"


class _KB(KnowledgeBaseReader):
    """返回固定 chunk 的 mock KB（用于触发 astrbot 召回通道以验证硬过滤）。"""

    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks

    async def list_collections(self) -> list[str]:
        return ["kb"]

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        return self._chunks

    async def search(self, collection: str, query: str, top_k: int) -> list[DocumentChunk]:
        return list(self._chunks)


def _doc(doc_id: str, item_key: str, *, lifecycle=DocumentLifecycle.ACTIVE) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=doc_id,
        file_path=f"/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="kb",
        library_id=LIB,
        zotero_item_key=item_key,
        origin=DocumentOrigin.ZOTERO,
        lifecycle_state=lifecycle,
    )


async def _store_with_mirror() -> InMemorySourceDocumentStore:
    store = InMemorySourceDocumentStore()
    await store.upsert_collection(Collection(name="kb"))
    # 集合树 root -> child；item A 在 root，item B 在 child，item C 无集合但有 tag
    await store.upsert_zotero_collection(
        ZoteroCollection(collection_key="root", library_id=LIB, name="Root")
    )
    await store.upsert_zotero_collection(
        ZoteroCollection(
            collection_key="child", library_id=LIB, name="Child", parent_collection_key="root"
        )
    )
    await store.set_item_collections(LIB, "ITEMA", ["root"])
    await store.set_item_collections(LIB, "ITEMB", ["child"])
    await store.replace_item_tags(LIB, "ITEMC", [ZoteroTag("ITEMC", "shared", 0)])
    await store.replace_item_tags(LIB, "ITEMA", [ZoteroTag("ITEMA", "shared", 0)])
    # 统一 collections 树（coll_key 复用 root/child）+ 多归属（collection scope 走此路径）。
    await store.upsert_collection(
        Collection(name="Root", coll_key="root", origin=DocumentOrigin.ZOTERO, library_id=LIB)
    )
    await store.upsert_collection(
        Collection(
            name="Child", coll_key="child", parent_key="root",
            origin=DocumentOrigin.ZOTERO, library_id=LIB,
        )
    )
    for doc_id, item in [("dA", "ITEMA"), ("dB", "ITEMB"), ("dC", "ITEMC")]:
        await store.add_document(_doc(doc_id, item))
    await store.set_document_collections("dA", ["root"])
    await store.set_document_collections("dB", ["child"])
    return store


def _orch(store: InMemorySourceDocumentStore, kb: _KB) -> RetrievalOrchestrator:
    return RetrievalOrchestrator(
        source_store=store, kb_reader=kb, config=Config({"vector_db": {"backend": "astr"}})
    )


# ── resolve_scope ────────────────────────────────────────────────


async def test_resolve_scope_item() -> None:
    store = await _store_with_mirror()
    orch = _orch(store, _KB([]))
    allowed = await orch.resolve_scope(RetrievalScope(SCOPE_ITEM, "ITEMA", LIB))
    assert allowed == {"dA"}


async def test_resolve_scope_collection_includes_descendants() -> None:
    store = await _store_with_mirror()
    orch = _orch(store, _KB([]))
    allowed = await orch.resolve_scope(RetrievalScope(SCOPE_COLLECTION, "root", LIB))
    assert allowed == {"dA", "dB"}  # root + child 后代


async def test_resolve_scope_tag() -> None:
    store = await _store_with_mirror()
    orch = _orch(store, _KB([]))
    allowed = await orch.resolve_scope(RetrievalScope(SCOPE_TAG, "shared", LIB))
    assert allowed == {"dA", "dC"}


async def test_resolve_scope_library_excludes_detached() -> None:
    store = await _store_with_mirror()
    detached = _doc("dD", "ITEMD", lifecycle=DocumentLifecycle.DETACHED)
    await store.add_document(detached)
    orch = _orch(store, _KB([]))
    allowed = await orch.resolve_scope(RetrievalScope(SCOPE_LIBRARY, LIB, LIB))
    assert allowed == {"dA", "dB", "dC"}  # 排除 detached dD


async def test_no_scope_returns_none() -> None:
    store = await _store_with_mirror()
    orch = _orch(store, _KB([]))
    assert await orch.resolve_scope(None) is None
    assert await orch.resolve_scope(RetrievalScope("", "", "")) is None


# ── 跨通道硬过滤 ─────────────────────────────────────────────────


async def test_hard_filter_restricts_candidates_before_rrf() -> None:
    store = await _store_with_mirror()
    # KB 召回通道返回 dA 与 dB 的 chunk；item 作用域应只保留 dA。
    kb = _KB([
        DocumentChunk("dA_c0", "dA", 0, "alpha", "h"),
        DocumentChunk("dB_c0", "dB", 0, "beta", "h"),
    ])
    orch = _orch(store, kb)
    outcome = await orch.retrieve_with_outcome(
        "kb", "alpha beta", top_k=5, scope=RetrievalScope(SCOPE_ITEM, "ITEMA", LIB)
    )
    assert [c.doc_id for c in outcome.chunks] == ["dA"]


async def test_empty_scope_returns_no_chunks() -> None:
    store = await _store_with_mirror()
    kb = _KB([DocumentChunk("dA_c0", "dA", 0, "alpha", "h")])
    orch = _orch(store, kb)
    outcome = await orch.retrieve_with_outcome(
        "kb", "alpha", top_k=5, scope=RetrievalScope(SCOPE_ITEM, "NONEXIST", LIB)
    )
    assert outcome.chunks == []


# ── 图谱越界拒绝 ─────────────────────────────────────────────────


async def test_lightrag_context_rejects_item_and_tag_scope() -> None:
    store = await _store_with_mirror()
    orch = _orch(store, _KB([]))
    with pytest.raises(RuntimeError, match="item/tag scope"):
        await orch.retrieve_lightrag_context("kb", "q", RetrievalScope(SCOPE_ITEM, "ITEMA", LIB))
    with pytest.raises(RuntimeError, match="item/tag scope"):
        await orch.retrieve_lightrag_context("kb", "q", RetrievalScope(SCOPE_TAG, "shared", LIB))
