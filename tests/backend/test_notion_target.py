"""单元与契约测试：AstrBotKnowledgeBaseReader 与 NotionSyncTarget（幂等 upsert 版）。

Notion 部分经 tool_caller fake 驱动（接口对换，不 mock 宿主对象），重点回归：
防重复建页（幂等序列）、渐进降级（Name+DocID 最小集）、大文件 callout、
正文块按 content_hash 重写、QA NoteID 防重、两表建库对账。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kacore.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError
from kacore.config import NotionSyncConfig
from kacore.domain.models import (
    Collection,
    DocumentChunk,
    NotionEntityRecord,
    SourceDocument,
)
from kacore.repository.kb_reader.astrbot import AstrBotKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.sync_targets import notion_schema as schema
from kacore.repository.sync_targets.notion import (
    ACTION_CREATED,
    ACTION_UPDATED,
    NotionSyncTarget,
)

# ── AstrBot KB Reader 测试 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_astrbot_kb_reader_list_collections() -> None:
    class Kb:
        def __init__(self, name: str) -> None:
            self.kb_name = name

    mock_kb_manager = MagicMock()
    mock_kb_manager.list_kbs = AsyncMock(return_value=[Kb("papers"), Kb("manuals")])
    mock_context = MagicMock()
    mock_context.kb_manager = mock_kb_manager

    reader = AstrBotKnowledgeBaseReader(mock_context)
    cols = await reader.list_collections()
    assert cols == ["papers", "manuals"]


@pytest.mark.asyncio
async def test_astrbot_kb_reader_list_chunks_translation() -> None:
    reader = AstrBotKnowledgeBaseReader(MagicMock())
    chunks = await reader.list_chunks("papers")
    assert chunks == []


@pytest.mark.asyncio
async def test_astrbot_kb_reader_search() -> None:
    class Kb:
        kb_name = "papers"

    mock_kb_manager = MagicMock()
    mock_kb_manager.list_kbs = AsyncMock(return_value=[Kb()])
    mock_kb_manager.retrieve = AsyncMock(
        return_value={
            "context_text": "search match",
            "results": [
                {
                    "chunk_id": "c2",
                    "doc_id": "d1",
                    "chunk_index": 0,
                    "content": "search match",
                }
            ],
        }
    )
    mock_context = MagicMock()
    mock_context.kb_manager = mock_kb_manager

    reader = AstrBotKnowledgeBaseReader(mock_context)
    results = await reader.search("papers", "query", top_k=5)
    assert len(results) == 1
    assert results[0].chunk_id == "c2"
    assert results[0].text == "search match"
    mock_kb_manager.retrieve.assert_awaited_once_with(
        query="query",
        kb_names=["papers"],
        top_k_fusion=20,
        top_m_final=5,
    )


# ── Notion Sync Target 测试基建 ─────────────────────────────────


@dataclass
class RoutedToolCaller:
    """按工具名路由响应的 tool_caller fake；list 值按序弹出，callable 值动态计算。"""

    handlers: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    _DEFAULTS: dict[str, Any] = field(
        default_factory=lambda: {
            "notion_query_database": {"results": [], "has_more": False},
            "notion_retrieve_block_children": {"results": [], "has_more": False},
            "notion_create_database_item": {"id": "page-new"},
            "notion_create_database": {"id": "db-new"},
        }
    )

    async def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool_name, arguments))
        handler = self.handlers.get(tool_name)
        if callable(handler):
            return handler(arguments)
        if isinstance(handler, list):
            value = handler.pop(0) if handler else {}
        elif handler is not None:
            value = handler
        else:
            value = self._DEFAULTS.get(tool_name, {})
        if isinstance(value, Exception):
            raise value
        return value

    def tools_called(self) -> list[str]:
        return [name for name, _ in self.calls]

    def args_of(self, tool_name: str, index: int = 0) -> dict[str, Any]:
        matched = [args for name, args in self.calls if name == tool_name]
        return matched[index]


def _target(
    caller: RoutedToolCaller,
    store: InMemorySourceDocumentStore,
    config: NotionSyncConfig,
) -> NotionSyncTarget:
    adapter = NotionMCPAdapter(None, tool_caller=caller, rate_limit_rps=1000)
    return NotionSyncTarget(config, store, adapter=adapter)


@pytest.fixture
def store() -> InMemorySourceDocumentStore:
    return InMemorySourceDocumentStore()


@pytest.fixture
def notion_config() -> NotionSyncConfig:
    return NotionSyncConfig(
        enabled=True,
        mcp_server_name="notion",
        database_id="db-articles",
        qa_database_id="db-qa",
    )


def _doc(doc_id: str, size: int = 1000) -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id,
        title=f"doc_{doc_id}.pdf",
        file_path=f"/data/{doc_id}.pdf",
        content_type="application/pdf",
        size_bytes=size,
        content_hash=f"hash_{doc_id}",
        collection="default",
        tags=["academic", "ai"],
    )


# ── 文章幂等 upsert ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_first_push_creates_then_appends(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    await store.add_document(_doc("d1"))
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "Chunk text 1", "h1")])
    caller = RoutedToolCaller(
        handlers={"notion_create_database_item": {"id": "page-1"}}
    )
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        _doc("d1"), path="根 / 子", collection_names=["根", "子"], prior=None
    )

    assert result.page_id == "page-1"
    assert result.action == ACTION_CREATED
    assert not result.degraded
    # 幂等序列：先 DocID 反查（miss）→ create → append，两步分离（server 不支持 children）
    assert caller.tools_called() == [
        "notion_query_database",
        "notion_create_database_item",
        "notion_append_block_children",
    ]
    query_args = caller.args_of("notion_query_database")
    assert query_args["filter"] == {
        "property": "DocID",
        "rich_text": {"equals": "d1"},
    }
    props = caller.args_of("notion_create_database_item")["properties"]
    assert props["Name"]["title"][0]["text"]["content"] == "doc_d1.pdf"
    assert props["DocID"]["rich_text"][0]["text"]["content"] == "d1"
    assert {t["name"] for t in props["Tags"]["multi_select"]} == {"academic", "ai"}
    assert {c["name"] for c in props["Collections"]["multi_select"]} == {"根", "子"}
    assert props["Collection Path"]["select"]["name"] == "根 / 子"
    blocks = caller.args_of("notion_append_block_children")["children"]
    assert blocks[0]["type"] == "toggle"
    toggle = blocks[0]["toggle"]
    assert "Chunks Preview" in toggle["rich_text"][0]["text"]["content"]
    assert toggle["children"][0]["paragraph"]["rich_text"][0]["text"]["content"] == (
        "[Chunk #0] Chunk text 1"
    )


@pytest.mark.asyncio
async def test_upsert_with_prior_updates_without_create(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    doc = _doc("d1")
    prior = NotionEntityRecord(
        entity_type="document",
        entity_key="d1",
        page_id="page-existing",
        content_hash=doc.content_hash,  # 正文未变 → 不重写块
    )
    caller = RoutedToolCaller()
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        doc, path="default", collection_names=["default"], prior=prior
    )

    assert result.page_id == "page-existing"
    assert result.action == ACTION_UPDATED
    # 只有一次属性 update：不反查、不 create、不动正文块
    assert caller.tools_called() == ["notion_update_page_properties"]


@pytest.mark.asyncio
async def test_upsert_map_miss_but_remote_hit_updates_not_creates(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    """防重复建页回归：账本 miss 但远端已有同 DocID 页面时必须走 update。"""
    caller = RoutedToolCaller(
        handlers={
            "notion_query_database": {
                "results": [{"id": "page-remote"}],
                "has_more": False,
            }
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        _doc("d1"), path="default", collection_names=["default"], prior=None
    )

    assert result.page_id == "page-remote"
    assert result.action == ACTION_UPDATED
    assert "notion_create_database_item" not in caller.tools_called()


@pytest.mark.asyncio
async def test_upsert_stale_prior_page_falls_back_to_reverse_query(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    from kacore.adapters.notion_mcp import NotionMCPError

    doc = _doc("d1")
    prior = NotionEntityRecord(
        entity_type="document",
        entity_key="d1",
        page_id="page-stale",
        content_hash=doc.content_hash,
    )
    caller = RoutedToolCaller(
        handlers={
            "notion_update_page_properties": [
                NotionMCPError("404 page not found"),  # 账本 page 已被手删
                {},  # 反查命中后的 update 成功
            ],
            "notion_query_database": {
                "results": [{"id": "page-found"}],
                "has_more": False,
            },
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        doc, path="default", collection_names=["default"], prior=prior
    )

    assert result.page_id == "page-found"
    assert result.action == ACTION_UPDATED


@pytest.mark.asyncio
async def test_upsert_create_degrades_to_minimal_with_docid(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    from kacore.adapters.notion_mcp import NotionMCPError

    caller = RoutedToolCaller(
        handlers={
            "notion_create_database_item": [
                NotionMCPError("validation_error: property Tags not found"),
                {"id": "page-degraded"},
            ]
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        _doc("d4"), path="default", collection_names=["default"], prior=None
    )

    assert result.page_id == "page-degraded"
    assert result.degraded is True
    # 降级最小集必须保留 DocID（幂等键），否则重复页面问题复发
    minimal = caller.args_of("notion_create_database_item", 1)["properties"]
    assert set(minimal) == {"Name", "DocID"}


@pytest.mark.asyncio
async def test_upsert_content_change_rewrites_blocks(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    doc = _doc("d1")
    await store.add_document(doc)
    await store.replace_chunks("d1", [DocumentChunk("c1", "d1", 0, "new text", "h2")])
    prior = NotionEntityRecord(
        entity_type="document",
        entity_key="d1",
        page_id="page-1",
        content_hash="old-hash",  # 原件已变
    )
    caller = RoutedToolCaller(
        handlers={
            "notion_retrieve_block_children": {
                "results": [{"id": "blk-1"}, {"id": "blk-2"}],
                "has_more": False,
            }
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.upsert_document(
        doc, path="default", collection_names=["default"], prior=prior
    )

    assert result.action == ACTION_UPDATED
    tools = caller.tools_called()
    # 重写序列：update 属性 → 列旧块 → 逐删 → 追加新块
    assert tools == [
        "notion_update_page_properties",
        "notion_retrieve_block_children",
        "notion_delete_block",
        "notion_delete_block",
        "notion_append_block_children",
    ]


@pytest.mark.asyncio
async def test_push_large_file_prefix_and_callout(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    payload_size = int(5.1 * 1024 * 1024)
    doc = _doc("d2", size=payload_size)
    caller = RoutedToolCaller(
        handlers={"notion_create_database_item": {"id": "page-large"}}
    )
    target = _target(caller, store, notion_config)

    remote_ref = await target.push(doc, b"x" * payload_size)

    assert remote_ref == "skipped:page-large"
    blocks = caller.args_of("notion_append_block_children")["children"]
    assert blocks[0]["type"] == "callout"
    assert "已跳过文件二进制镜像" in blocks[0]["callout"]["rich_text"][0]["text"]["content"]


@pytest.mark.asyncio
async def test_delete_archives_via_delete_block(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller()
    target = _target(caller, store, notion_config)

    assert await target.delete("page-9") is True
    assert caller.tools_called() == ["notion_delete_block"]
    assert caller.args_of("notion_delete_block")["block_id"] == "page-9"


@pytest.mark.asyncio
async def test_delete_treats_not_found_as_idempotent_but_raises_real_errors(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    from kacore.adapters.notion_mcp import NotionMCPError

    caller = RoutedToolCaller(
        handlers={
            "notion_delete_block": [
                NotionMCPError(
                    "Could not find block",
                    code="object_not_found",
                    status=404,
                ),
                NotionMCPError("Notion request timed out"),
            ]
        }
    )
    target = _target(caller, store, notion_config)

    assert await target.delete("missing-page") is False
    with pytest.raises(NotionMCPError, match="timed out"):
        await target.delete("retry-page")


@pytest.mark.asyncio
async def test_archive_document_cleans_known_and_duplicate_docid_pages(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller(
        handlers={
            "notion_query_database": {
                "results": [
                    {"id": "known-page"},
                    {"id": "duplicate-page"},
                    {"id": "duplicate-page"},
                ],
                "has_more": False,
            }
        }
    )
    target = _target(caller, store, notion_config)

    archived = await target.archive_document("doc-1", "known-page")

    assert archived == 2
    query = caller.args_of("notion_query_database")
    assert query["database_id"] == "db-articles"
    assert query["filter"] == {
        "property": "DocID",
        "rich_text": {"equals": "doc-1"},
    }
    deleted_ids = [
        args["block_id"]
        for name, args in caller.calls
        if name == "notion_delete_block"
    ]
    assert deleted_ids == ["known-page", "duplicate-page"]


# ── QA 记录 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_qa_entry_created_with_citations_and_body(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller(
        handlers={"notion_create_database_item": {"id": "qa-page-1"}}
    )
    target = _target(caller, store, notion_config)

    result = await target.create_qa_entry(
        title="RAG 与图谱结合的研究进展？",
        content="研究结论正文。\n\n[1] Some Paper",
        tags=["research"],
        citation_page_ids=["page-a", "page-b"],
        source="research",
        note_id="outbox:ob1",
    )

    assert result.page_id == "qa-page-1"
    assert result.action == ACTION_CREATED
    create_args = caller.args_of("notion_create_database_item")
    assert create_args["database_id"] == "db-qa"
    props = create_args["properties"]
    assert props["Question"]["title"][0]["text"]["content"].startswith("RAG")
    assert props["NoteID"]["rich_text"][0]["text"]["content"] == "outbox:ob1"
    assert props["Citations"]["relation"] == [{"id": "page-a"}, {"id": "page-b"}]
    assert props["Source"]["select"]["name"] == "research"
    body = caller.args_of("notion_append_block_children")["children"]
    assert body[0]["paragraph"]["rich_text"][0]["text"]["content"] == "研究结论正文。"


@pytest.mark.asyncio
async def test_qa_entry_retry_reuses_page_and_rewrites_body(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    # NoteID 已存在（上轮建页成功但正文没写成）→ 复用该页、清块重写正文，不重复建行。
    caller = RoutedToolCaller(
        handlers={
            "notion_query_database": {
                "results": [{"id": "qa-existing"}],
                "has_more": False,
            },
            "notion_retrieve_block_children": {"results": [], "has_more": False},
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.create_qa_entry(
        title="Q",
        content="body",
        tags=[],
        citation_page_ids=[],
        source="chat",
        note_id="outbox:ob1",
    )

    assert result.action == ACTION_UPDATED
    assert result.page_id == "qa-existing"
    assert result.content_synced is True
    # 不重复建行；复用页面走 clear→append 幂等重写正文
    assert "notion_create_database_item" not in caller.tools_called()
    assert "notion_append_block_children" in caller.tools_called()
    assert caller.args_of("notion_append_block_children")["block_id"] == "qa-existing"


@pytest.mark.asyncio
async def test_qa_entry_body_append_failure_reports_not_synced(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    from kacore.adapters.notion_mcp import NotionMCPError

    # 建页成功但正文追加失败 → content_synced=False（上层据此保留 outbox 正文）。
    caller = RoutedToolCaller(
        handlers={
            "notion_create_database_item": {"id": "qa-1"},
            "notion_append_block_children": NotionMCPError("append timeout"),
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.create_qa_entry(
        title="Q",
        content="正文全文",
        tags=[],
        citation_page_ids=[],
        source="research",
        note_id="outbox:ob9",
    )

    assert result.page_id == "qa-1"
    assert result.content_synced is False


@pytest.mark.asyncio
async def test_qa_entry_relation_failure_degrades(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    from kacore.adapters.notion_mcp import NotionMCPError

    caller = RoutedToolCaller(
        handlers={
            "notion_create_database_item": [
                NotionMCPError("Citations is not a property"),
                {"id": "qa-degraded"},
            ]
        }
    )
    target = _target(caller, store, notion_config)

    result = await target.create_qa_entry(
        title="Q",
        content="body",
        tags=[],
        citation_page_ids=["page-a"],
        citation_labels=["doc-a"],
        source="ask",
        note_id="outbox:ob2",
    )

    assert result.degraded is True
    retry_props = caller.args_of("notion_create_database_item", 1)["properties"]
    assert "Citations" not in retry_props
    # 降级时已解析引用（DocID）补进正文尾部，不随 relation 一起丢失
    body_blocks = caller.args_of("notion_append_block_children")["children"]
    body_text = "".join(
        b["paragraph"]["rich_text"][0]["text"]["content"] for b in body_blocks
    )
    assert "doc-a" in body_text


# ── 两表建库与对账 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_creates_both_databases_with_relation(
    store: InMemorySourceDocumentStore,
) -> None:
    config = NotionSyncConfig(enabled=True, parent_page_id="parent-page")
    caller = RoutedToolCaller(
        handlers={"notion_create_database": [{"id": "db-a"}, {"id": "db-q"}]}
    )
    target = _target(caller, store, config)

    result = await target.initialize_databases()

    assert result["status"] == "success"
    assert result["database_id"] == "db-a"
    assert result["qa_database_id"] == "db-q"
    assert result["created"] is True
    articles_props = caller.args_of("notion_create_database", 0)["properties"]
    assert set(articles_props) == set(schema.articles_db_properties())
    qa_props = caller.args_of("notion_create_database", 1)["properties"]
    assert qa_props["Citations"]["relation"]["database_id"] == "db-a"
    # 配置随建库回填，后续 push 直接可用
    assert target.config.database_id == "db-a"
    assert target.config.qa_database_id == "db-q"


@pytest.mark.asyncio
async def test_initialize_reconciles_missing_columns_on_existing_db(
    store: InMemorySourceDocumentStore,
) -> None:
    config = NotionSyncConfig(
        enabled=True, database_id="db-a", parent_page_id="parent-page"
    )
    caller = RoutedToolCaller(
        handlers={
            "notion_retrieve_database": {
                "id": "db-a",
                # 旧库只有历史四列 → 需补齐新列
                "properties": {"Name": {}, "Collection": {}, "Tags": {}, "DocID": {}},
            },
            "notion_create_database": [{"id": "db-q"}],
        }
    )
    target = _target(caller, store, config)

    result = await target.initialize_databases()

    assert result["status"] == "success"
    added = caller.args_of("notion_update_database")["properties"]
    assert "Collections" in added and "Lifecycle" in added
    assert "Name" not in added  # 已存在的列不动（幂等）


# ── schema 纯函数 ───────────────────────────────────────────────


def test_expand_ancestor_names_covers_subtree_filtering() -> None:
    cols = [
        Collection(name="根", coll_key="k-root"),
        Collection(name="子", coll_key="k-sub", parent_key="k-root"),
        Collection(name="孙", coll_key="k-leaf", parent_key="k-sub"),
        Collection(name="旁支", coll_key="k-other"),
    ]
    # 文章挂在「孙」：祖先链全部进 multi_select → 在 Notion 筛「根」即可命中
    assert schema.expand_ancestor_names(["k-leaf"], cols) == ["子", "孙", "根"]
    paths = schema.build_collection_paths(cols)
    assert paths["k-leaf"] == "根 / 子 / 孙"


def test_expand_ancestor_names_survives_cycles() -> None:
    cols = [
        Collection(name="A", coll_key="ka", parent_key="kb"),
        Collection(name="B", coll_key="kb", parent_key="ka"),  # 脏数据环
    ]
    assert schema.expand_ancestor_names(["ka"], cols) == ["A", "B"]
    assert set(schema.build_collection_paths(cols)) == {"ka", "kb"}


def test_metadata_hash_reacts_to_collection_rename() -> None:
    doc = _doc("d1")
    h1 = schema.document_metadata_hash(doc, path="根 / 子", collection_names=["根", "子"])
    h2 = schema.document_metadata_hash(doc, path="根 / 新名", collection_names=["根", "新名"])
    h3 = schema.document_metadata_hash(doc, path="根 / 子", collection_names=["根", "子"])
    assert h1 != h2
    assert h1 == h3


def test_metadata_hash_reacts_to_updated_at() -> None:
    from datetime import datetime, timezone

    doc = _doc("d1")
    doc.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    h1 = schema.document_metadata_hash(doc, path="c", collection_names=["c"])
    doc.updated_at = datetime(2026, 2, 2, tzinfo=timezone.utc)
    h2 = schema.document_metadata_hash(doc, path="c", collection_names=["c"])
    # 仅 updated_at 变化也应改变指纹，使 Notion Updated 列不滞后
    assert h1 != h2


def test_text_to_paragraph_blocks_caps_and_splits() -> None:
    long_text = "\n\n".join(f"段落 {i} " + "x" * 50 for i in range(60))
    blocks = schema.text_to_paragraph_blocks(long_text)
    assert len(blocks) == schema.MAX_BODY_BLOCKS
    assert "已截断" in blocks[-1]["paragraph"]["rich_text"][0]["text"]["content"]

    oversize = "y" * 4000
    split_blocks = schema.text_to_paragraph_blocks(oversize)
    assert len(split_blocks) == 3  # 1800 + 1800 + 400
    assert schema.text_to_paragraph_blocks("") == []


# ── Strict 选项清理 ─────────────────────────────────────────────


def _retrieve_with_options() -> dict[str, Any]:
    """伪造 retrieve_database：Collections/Collection Path 各含一个失效选项。"""
    return {
        "properties": {
            "Collections": {
                "type": "multi_select",
                "multi_select": {
                    "options": [
                        {"id": "o1", "name": "keep", "color": "blue"},
                        {"id": "o2", "name": "stale", "color": "red"},
                    ]
                },
            },
            "Collection Path": {
                "type": "select",
                "select": {
                    "options": [
                        {"id": "p1", "name": "keep", "color": "blue"},
                        {"id": "p2", "name": "gone", "color": "gray"},
                    ]
                },
            },
        }
    }


@pytest.mark.asyncio
async def test_prune_collection_options_removes_stale(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller(
        handlers={"notion_retrieve_database": _retrieve_with_options()}
    )
    target = _target(caller, store, notion_config)

    pruned = await target.prune_collection_options(
        live_collection_names={"keep"}, live_path_names={"keep"}
    )

    assert pruned == {"collections": 1, "collection_path": 1}
    # 两次 update_database，各只保留活跃选项（带 id）→ Notion 据此删除被省略的失效项。
    assert caller.tools_called().count("notion_update_database") == 2
    coll = caller.args_of("notion_update_database", 0)["properties"]["Collections"]
    assert [o["name"] for o in coll["multi_select"]["options"]] == ["keep"]
    assert coll["multi_select"]["options"][0]["id"] == "o1"
    path = caller.args_of("notion_update_database", 1)["properties"]["Collection Path"]
    assert [o["name"] for o in path["select"]["options"]] == ["keep"]


@pytest.mark.asyncio
async def test_prune_collection_options_noop_when_all_live(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller(
        handlers={"notion_retrieve_database": _retrieve_with_options()}
    )
    target = _target(caller, store, notion_config)

    pruned = await target.prune_collection_options(
        live_collection_names={"keep", "stale"},
        live_path_names={"keep", "gone"},
    )

    assert pruned == {"collections": 0, "collection_path": 0}
    assert "notion_update_database" not in caller.tools_called()


@pytest.mark.asyncio
async def test_prune_collection_options_swallows_update_error(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    caller = RoutedToolCaller(
        handlers={
            "notion_retrieve_database": _retrieve_with_options(),
            "notion_update_database": NotionMCPError("boom"),
        }
    )
    target = _target(caller, store, notion_config)

    # 单属性写失败记 warning 跳过，绝不抛出中断整轮推送。
    pruned = await target.prune_collection_options(
        live_collection_names={"keep"}, live_path_names={"keep"}
    )
    assert pruned == {"collections": 0, "collection_path": 0}
