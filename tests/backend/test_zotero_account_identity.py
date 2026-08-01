"""Zotero 跨源（local/Web API）重复文档识别与账号身份合并测试（v1.0.11）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.domain.models import DocumentChunk, DocumentOrigin, SourceDocument
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore


def _zotero_doc(
    doc_id: str,
    *,
    library_id: str,
    item_key: str,
    attachment_key: str,
    collection: str = "papers",
) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"title-{doc_id}",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=10,
        content_hash=f"hash-{doc_id}",
        collection=collection,
        library_id=library_id,
        zotero_item_key=item_key,
        attachment_key=attachment_key,
        origin=DocumentOrigin.ZOTERO,
        read_only=True,
    )


async def _make_api() -> tuple[KnowledgeRepositoryApi, InMemorySourceDocumentStore]:
    store = InMemorySourceDocumentStore()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=MagicMock(),  # type: ignore[arg-type]
    )
    return api, store


async def test_detect_finds_cross_library_duplicate_ignoring_library_id() -> None:
    """同一 (item_key, attachment_key) 跨 library_id 出现两次即视为重复。"""
    api, store = await _make_api()
    await store.add_document(
        _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    )
    await store.add_document(
        _zotero_doc(
            "12595538_ABCD_WXYZ",
            library_id="12595538",
            item_key="ABCD",
            attachment_key="WXYZ",
        )
    )
    await store.add_document(
        _zotero_doc("1_ONLY_ONE", library_id="1", item_key="ONLY", attachment_key="ONE")
    )

    result = await api.detect_zotero_duplicate_documents()

    assert result["total_duplicate_groups"] == 1
    group = result["groups"][0]
    assert group["item_key"] == "ABCD"
    assert group["attachment_key"] == "WXYZ"
    assert {doc["library_id"] for doc in group["docs"]} == {"1", "12595538"}


async def test_detect_ignores_same_library_repeats_and_non_zotero_docs() -> None:
    """同一 library_id 内不算跨源重复；非 Zotero 来源文档不参与分组。"""
    api, store = await _make_api()
    await store.add_document(
        _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    )
    local_doc = SourceDocument(
        doc_id="LOCAL_manual",
        title="manual upload",
        file_path="/data/manual.pdf",
        content_type="application/pdf",
        size_bytes=1,
        content_hash="h",
        collection="papers",
        origin=DocumentOrigin.LOCAL,
    )
    await store.add_document(local_doc)

    result = await api.detect_zotero_duplicate_documents()

    assert result["total_duplicate_groups"] == 0


async def test_preview_merge_reports_matched_docs_collections_and_chunk_counts() -> None:
    """预览只读，展示匹配文档数、受影响集合与 chunk 数，不做任何修改。"""
    api, store = await _make_api()
    doc_a = _zotero_doc(
        "1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ", collection="papers"
    )
    doc_b = _zotero_doc(
        "12595538_ABCD_WXYZ",
        library_id="12595538",
        item_key="ABCD",
        attachment_key="WXYZ",
        collection="papers",
    )
    await store.add_document(doc_a)
    await store.add_document(doc_b)
    await store.replace_chunks(
        doc_a.doc_id, [DocumentChunk("c1", doc_a.doc_id, 0, "text", "h1")]
    )
    await store.replace_chunks(
        doc_b.doc_id,
        [
            DocumentChunk("c2", doc_b.doc_id, 0, "text", "h2"),
            DocumentChunk("c3", doc_b.doc_id, 1, "text2", "h3"),
        ],
    )

    preview = await api.preview_zotero_account_merge("1", "12595538")

    assert preview["matched_groups"] == 1
    assert preview["matched_docs"] == 2
    assert preview["affected_collections"] == ["papers"]
    assert preview["total_chunks"] == 3

    # 只读：文档仍然都在。
    assert await store.get_document(doc_a.doc_id) is not None
    assert await store.get_document(doc_b.doc_id) is not None


async def test_confirm_merge_deletes_non_canonical_duplicate_and_links_identity() -> None:
    """确认合并后：非 canonical 副本被删除，canonical 副本不受影响，且记录账号链接。"""
    api, store = await _make_api()
    doc_a = _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    doc_b = _zotero_doc(
        "12595538_ABCD_WXYZ", library_id="12595538", item_key="ABCD", attachment_key="WXYZ"
    )
    await store.add_document(doc_a)
    await store.add_document(doc_b)
    await store.replace_chunks(
        doc_b.doc_id, [DocumentChunk("c-loser", doc_b.doc_id, 0, "text", "h")]
    )

    result = await api.confirm_zotero_account_merge(
        "1", "12595538", keep="a", access_mode_a="local", access_mode_b="server"
    )

    assert result["status"] == "merged"
    assert result["canonical_library_id"] == "1"
    assert result["removed_document_ids"] == [doc_b.doc_id]

    # canonical 副本保留；非 canonical 副本及其 chunks 被删除。
    assert await store.get_document(doc_a.doc_id) is not None
    assert await store.get_document(doc_b.doc_id) is None
    assert await store.list_chunks(doc_b.doc_id) == []

    # 两个命名空间已链接到同一逻辑账号。
    local_identity = await store.get_zotero_account_identity("local:1")
    server_identity = await store.get_zotero_account_identity("server:12595538")
    assert local_identity is not None and server_identity is not None
    assert local_identity["account_key"] == server_identity["account_key"]


async def test_confirm_merge_never_touches_unrelated_zotero_metadata() -> None:
    """合并只删除确认重复的 KB 侧文档；不涉及任何「删除 Zotero 原条目」的操作面。"""
    api, store = await _make_api()
    doc_a = _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    doc_b = _zotero_doc(
        "12595538_ABCD_WXYZ", library_id="12595538", item_key="ABCD", attachment_key="WXYZ"
    )
    await store.add_document(doc_a)
    await store.add_document(doc_b)

    # 不相关的第三方文档必须在合并过程中保持完全不受影响。
    unrelated = _zotero_doc(
        "1_OTHER_ITEM", library_id="1", item_key="OTHER", attachment_key="ITEM"
    )
    await store.add_document(unrelated)

    await api.confirm_zotero_account_merge("1", "12595538", keep="a")

    assert await store.get_document(unrelated.doc_id) is not None


async def test_access_mode_switch_blocked_when_unresolved_duplicates_exist() -> None:
    """已知未解决的跨命名空间重复时，切换 access_mode 抛 ValueError 而不是静默放行。

    必须是异常而不是一个「看起来正常」的返回 dict：前端两条现有 update_config_value
    调用路径（SettingModal.tsx/FlowPageContent.tsx）只处理 rebuild_required/
    restart_required 或吞掉非异常返回值，一个新的 status 字段会被两边都误报成
    「已保存」。抛异常才能复用 update_config_value() 已有的、被前端正确处理的
    ValueError → HTTP 400 → toast 报错路径，配置也确实不会被持久化。
    """
    api, store = await _make_api()
    from kacore.config import Config

    api._config = Config({})
    await store.add_document(
        _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    )
    await store.add_document(
        _zotero_doc(
            "12595538_ABCD_WXYZ",
            library_id="12595538",
            item_key="ABCD",
            attachment_key="WXYZ",
        )
    )

    with pytest.raises(ValueError, match="重复"):
        await api.update_config_value("zotero_sync", "access_mode", "server")


async def test_access_mode_switch_noop_is_not_blocked_by_stale_duplicates() -> None:
    """重新提交与当前值相同的 access_mode（未真正切换）不应被历史遗留重复拦截。

    某些前端调用路径（如 SettingModal.tsx 的标签点击）没有「已是当前值就不发请求」的
    前置判断；对已存在历史遗留跨源重复的老实例，重新点击当前已选中的模式不该报错。
    """
    api, store = await _make_api()
    from kacore.config import Config

    api._config = Config({"zotero_sync": {"access_mode": "local"}})
    await store.add_document(
        _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    )
    await store.add_document(
        _zotero_doc(
            "12595538_ABCD_WXYZ",
            library_id="12595538",
            item_key="ABCD",
            attachment_key="WXYZ",
        )
    )

    result = await api.update_config_value("zotero_sync", "access_mode", "local")

    assert result["status"] == "success"


async def test_access_mode_switch_allowed_when_no_duplicates() -> None:
    """没有已知重复时，access_mode 切换正常放行、不受本次改动影响。"""
    api, store = await _make_api()
    from kacore.config import Config

    api._config = Config({})
    await store.add_document(
        _zotero_doc("1_ABCD_WXYZ", library_id="1", item_key="ABCD", attachment_key="WXYZ")
    )

    result = await api.update_config_value("zotero_sync", "access_mode", "server")

    assert result["status"] == "success"
