"""NotionSyncPipeline 契约测试（接口对换：内存 store + fake tool_caller 驱动 target）。

覆盖：首推全量、零变更 0 调用、改 tag 仅 1 update、集合改名联动子树文章、
force 全推、outbox 补推与存根清空、citations 按需 upsert、孤儿清理、并发重入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from knowledge_arch.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError
from knowledge_arch.config import NotionSyncConfig
from knowledge_arch.domain.models import (
    NOTION_ENTITY_DOCUMENT,
    NOTION_OUTBOX_PUSHED,
    NOTION_PUSH_DEGRADED,
    NOTION_PUSH_FAILED,
    NOTION_PUSH_SYNCED,
    Collection,
    NotionOutboxItem,
    SourceDocument,
    SyncTargetKind,
)
from knowledge_arch.pipelines.notion_sync_pipeline import NotionSyncPipeline
from knowledge_arch.repository.source_store.memory import InMemorySourceDocumentStore
from knowledge_arch.repository.sync_targets.notion import NotionSyncTarget


@dataclass
class RoutedToolCaller:
    """按工具名路由响应；create 类默认返回自增 page id，query 默认空（miss）。"""

    handlers: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _seq: int = 0

    async def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool_name, arguments))
        handler = self.handlers.get(tool_name)
        if callable(handler):
            return handler(arguments)
        if isinstance(handler, list) and handler:
            value = handler.pop(0)
        elif handler is not None and not isinstance(handler, list):
            value = handler
        else:
            value = self._default(tool_name)
        if isinstance(value, Exception):
            raise value
        return value

    def _default(self, tool_name: str) -> Any:
        if tool_name in ("notion_query_database", "notion_retrieve_block_children"):
            return {"results": [], "has_more": False}
        if tool_name in ("notion_create_database_item", "notion_create_database"):
            self._seq += 1
            return {"id": f"page-{self._seq}"}
        return {}

    def count(self, tool_name: str) -> int:
        return sum(1 for name, _ in self.calls if name == tool_name)


def _config() -> NotionSyncConfig:
    return NotionSyncConfig(
        enabled=True,
        mcp_server_name="notion",
        database_id="db-articles",
        qa_database_id="db-qa",
    )


def _pipeline(
    store: InMemorySourceDocumentStore, caller: RoutedToolCaller
) -> NotionSyncPipeline:
    adapter = NotionMCPAdapter(None, tool_caller=caller, rate_limit_rps=1000)
    target = NotionSyncTarget(_config(), store, adapter=adapter)
    return NotionSyncPipeline(source_store=store, notion_target=target)


def _doc(doc_id: str, tags: list[str] | None = None) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"doc_{doc_id}",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        content_hash=f"hash_{doc_id}",
        collection="default",
        tags=list(tags or ["ai"]),
    )


@pytest.fixture
def store() -> InMemorySourceDocumentStore:
    return InMemorySourceDocumentStore()


# ── 全量推送与增量 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_all_first_run_creates_all(store: InMemorySourceDocumentStore) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1"))
    await store.add_document(_doc("d2"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)

    result = await pipeline.push_all()

    assert result["status"] == "success"
    assert result["documents"]["created"] == 2
    assert caller.count("notion_create_database_item") == 2
    # 账本回填 + sync_records 冗余
    rec = await store.get_notion_entity(NOTION_ENTITY_DOCUMENT, "d1")
    assert rec is not None and rec.page_id
    assert await store.get_sync_record("d1", SyncTargetKind.NOTION) is not None


@pytest.mark.asyncio
async def test_push_all_no_change_makes_zero_writes(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await pipeline.push_all()

    caller.calls.clear()
    result = await pipeline.push_all()

    assert result["documents"]["skipped"] == 1
    # 指纹相等 → 完全跳过，零 MCP 调用
    assert caller.calls == []


@pytest.mark.asyncio
async def test_tag_change_updates_only_that_doc(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1", tags=["ai"]))
    await store.add_document(_doc("d2", tags=["ml"]))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await pipeline.push_all()

    # 只改 d1 的 tag
    d1 = await store.get_document("d1")
    assert d1 is not None
    d1.tags = ["ai", "rag"]
    await store.update_document(d1)

    caller.calls.clear()
    result = await pipeline.push_all()

    assert result["documents"]["updated"] == 1
    assert result["documents"]["skipped"] == 1
    assert caller.count("notion_update_page_properties") == 1
    assert caller.count("notion_create_database_item") == 0


@pytest.mark.asyncio
async def test_collection_rename_propagates_to_subtree_docs(
    store: InMemorySourceDocumentStore,
) -> None:
    root = Collection(name="根", coll_key="k-root")
    sub = Collection(name="子", coll_key="k-sub", parent_key="k-root")
    await store.upsert_collection(root)
    await store.upsert_collection(sub)
    doc = _doc("d1")
    doc.collection = "子"
    doc.collection_keys = ["k-sub"]
    await store.add_document(doc)
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await pipeline.push_all()

    # 祖先「根」改名 → 子孙文章的 Collections/Path 指纹变化，应被重推
    root.name = "根新名"
    await store.upsert_collection(root)

    caller.calls.clear()
    result = await pipeline.push_all()

    assert result["documents"]["updated"] == 1
    update_props = next(
        args for name, args in caller.calls if name == "notion_update_page_properties"
    )["properties"]
    assert "根新名" in {c["name"] for c in update_props["Collections"]["multi_select"]}


@pytest.mark.asyncio
async def test_force_repushes_everything(store: InMemorySourceDocumentStore) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await pipeline.push_all()

    caller.calls.clear()
    result = await pipeline.push_all(force=True)

    assert result["documents"]["updated"] == 1  # force 忽略指纹全量重推
    assert caller.count("notion_retrieve_block_children") == 1
    assert caller.count("notion_append_block_children") == 1


@pytest.mark.asyncio
async def test_orphan_map_rows_cleaned_up(store: InMemorySourceDocumentStore) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await pipeline.push_all()
    assert await store.get_notion_entity(NOTION_ENTITY_DOCUMENT, "d1") is not None

    await store.delete_document("d1")
    await pipeline.push_all()

    # 本地文档已删 → 账本行清理（不触碰远端）
    assert await store.get_notion_entity(NOTION_ENTITY_DOCUMENT, "d1") is None


# ── QA 暂存箱与 citations ───────────────────────────────────────


@pytest.mark.asyncio
async def test_push_outbox_item_clears_content_on_success(
    store: InMemorySourceDocumentStore,
) -> None:
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    await store.add_notion_outbox(
        NotionOutboxItem(id="ob1", title="Q1", content="研究全文", source="research")
    )

    result = await pipeline.push_outbox_item("ob1")

    assert result["status"] == "success"
    stub = await store.get_notion_outbox("ob1")
    assert stub is not None
    assert stub.status == NOTION_OUTBOX_PUSHED
    assert stub.content == ""  # 中转即焚，只留存根
    assert stub.page_id


@pytest.mark.asyncio
async def test_push_qa_resolves_citations_to_page_ids(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("cited-1"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)
    # cited-1 尚未同步 → 按需先 upsert 进 Articles 再链接
    result = await pipeline.push_qa_record(
        note_id="outbox:x",
        title="Q",
        content="body",
        tags=[],
        citations=["cited-1", "ghost-doc"],
        source="research",
    )

    assert result["status"] == "success"
    assert result["unresolved_citations"] == ["ghost-doc"]  # 本地不存在 → 降级文本
    qa_create = next(
        args for name, args in caller.calls if name == "notion_create_database_item"
        and args["database_id"] == "db-qa"
    )
    assert len(qa_create["properties"]["Citations"]["relation"]) == 1


@pytest.mark.asyncio
async def test_push_all_retries_pending_outbox(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.upsert_collection(Collection(name="default"))
    await store.add_notion_outbox(
        NotionOutboxItem(id="ob1", title="Q1", content="待补推", source="chat")
    )
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)

    result = await pipeline.push_all()

    assert result["qa"]["pushed"] == 1
    stub = await store.get_notion_outbox("ob1")
    assert stub is not None and stub.status == NOTION_OUTBOX_PUSHED


@pytest.mark.asyncio
async def test_qa_outbox_partial_then_recovers_without_losing_body(
    store: InMemorySourceDocumentStore,
) -> None:
    """P1 回归：建页成功但正文追加失败 → outbox 保留全文（failed）；补推时复用
    该页重写正文成功 → body 落地、outbox 清正文。全程正文不丢。"""
    await store.upsert_collection(Collection(name="default"))
    await store.add_notion_outbox(
        NotionOutboxItem(id="ob1", title="Q1", content="研究结论全文", source="research")
    )
    caller = RoutedToolCaller(
        handlers={
            # 第一轮 NoteID 反查 miss，第二轮命中上轮建好的 qa-1
            "notion_query_database": [
                {"results": [], "has_more": False},
                {"results": [{"id": "qa-1"}], "has_more": False},
            ],
            "notion_create_database_item": {"id": "qa-1"},
            # 第一轮追加正文失败，第二轮成功
            "notion_append_block_children": [NotionMCPError("append timeout"), {}],
            "notion_retrieve_block_children": {"results": [], "has_more": False},
        }
    )
    pipeline = _pipeline(store, caller)

    # 第一轮：追加失败 → 保留全文
    r1 = await pipeline.push_outbox_item("ob1")
    assert r1["status"] != "success"
    stub = await store.get_notion_outbox("ob1")
    assert stub is not None
    assert stub.status == NOTION_PUSH_FAILED
    assert stub.content == "研究结论全文"  # 正文未丢

    # 第二轮：复用 qa-1 重写正文成功 → 清正文留存根
    r2 = await pipeline.push_outbox_item("ob1")
    assert r2["status"] == "success"
    stub = await store.get_notion_outbox("ob1")
    assert stub is not None
    assert stub.status == NOTION_OUTBOX_PUSHED
    assert stub.content == ""
    # 未重复建行；第二轮正文写在 qa-1 上
    assert caller.count("notion_create_database_item") == 1
    append_targets = [
        args["block_id"] for name, args in caller.calls
        if name == "notion_append_block_children"
    ]
    assert append_targets[-1] == "qa-1"


@pytest.mark.asyncio
async def test_article_body_failure_not_marked_synced_then_retries(
    store: InMemorySourceDocumentStore,
) -> None:
    """P1 回归：文章正文写入失败 → 账本不推进 content_hash、状态 degraded（不跳过）；
    下一轮重写正文成功后才标 synced。缺正文页不会被误固化为 synced。"""
    await store.upsert_collection(Collection(name="default"))
    await store.add_document(_doc("d1"))
    caller = RoutedToolCaller(
        handlers={
            "notion_create_database_item": {"id": "page-1"},
            "notion_append_block_children": [NotionMCPError("append 5xx"), {}],
            "notion_retrieve_block_children": {"results": [], "has_more": False},
        }
    )
    pipeline = _pipeline(store, caller)

    # 第一轮：正文失败 → degraded，content_hash 未推进
    r1 = await pipeline.push_all()
    assert r1["documents"]["created"] == 1
    rec = await store.get_notion_entity(NOTION_ENTITY_DOCUMENT, "d1")
    assert rec is not None
    assert rec.status == NOTION_PUSH_DEGRADED
    assert rec.content_hash == ""  # 未推进 → 下轮判定为待重写

    # 第二轮：degraded 不跳过 → 重写正文成功 → synced
    r2 = await pipeline.push_all()
    assert r2["documents"]["updated"] == 1
    rec = await store.get_notion_entity(NOTION_ENTITY_DOCUMENT, "d1")
    assert rec is not None
    assert rec.status == NOTION_PUSH_SYNCED
    assert rec.content_hash == "hash_d1"


@pytest.mark.asyncio
async def test_push_all_reentrant_returns_already_running(
    store: InMemorySourceDocumentStore,
) -> None:
    await store.upsert_collection(Collection(name="default"))
    caller = RoutedToolCaller()
    pipeline = _pipeline(store, caller)

    # 持锁期间再次 push_all → 直接返回 already_running（防并发重入）
    async with pipeline._lock:
        result = await pipeline.push_all()
    assert result["status"] == "already_running"


# ── 保护：未初始化 / 未启用 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_push_all_disabled_returns_early(
    store: InMemorySourceDocumentStore,
) -> None:
    caller = RoutedToolCaller()
    adapter = NotionMCPAdapter(None, tool_caller=caller, rate_limit_rps=1000)
    config = NotionSyncConfig(enabled=False, database_id="db-a", qa_database_id="db-q")
    target = NotionSyncTarget(config, store, adapter=adapter)
    pipeline = NotionSyncPipeline(source_store=store, notion_target=target)

    result = await pipeline.push_all()

    assert result["status"] == "disabled"
    assert caller.calls == []


@pytest.mark.asyncio
async def test_push_all_without_database_id_errors(
    store: InMemorySourceDocumentStore,
) -> None:
    caller = RoutedToolCaller()
    adapter = NotionMCPAdapter(None, tool_caller=caller, rate_limit_rps=1000)
    config = NotionSyncConfig(enabled=True, database_id="")
    target = NotionSyncTarget(config, store, adapter=adapter)
    pipeline = NotionSyncPipeline(source_store=store, notion_target=target)

    result = await pipeline.push_all()

    assert result["status"] == "error"
