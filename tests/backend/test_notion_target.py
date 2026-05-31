"""单元与契约测试：AstrBotKnowledgeBaseReader 与 NotionSyncTarget。

覆盖限频控制、大文件 (5MiB) 镜像跳过策略、Notion 数据库列缺失渐进降级，以及 KB 读取对象映射。
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import NotionSyncConfig
from core.domain.models import DocumentChunk, SourceDocument
from core.repository.kb_reader.astrbot import AstrBotKnowledgeBaseReader
from core.repository.source_store.memory import InMemorySourceDocumentStore
from core.repository.sync_targets.notion import NotionSyncTarget

# ── AstrBot KB Reader 测试 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_astrbot_kb_reader_list_collections() -> None:
    # 模拟 context.kb_manager.list_collections
    mock_kb_manager = MagicMock()
    mock_kb_manager.list_collections = AsyncMock(return_value=["papers", "manuals"])
    mock_context = MagicMock()
    mock_context.kb_manager = mock_kb_manager

    reader = AstrBotKnowledgeBaseReader(mock_context)
    cols = await reader.list_collections()
    assert cols == ["papers", "manuals"]


@pytest.mark.asyncio
async def test_astrbot_kb_reader_list_chunks_translation() -> None:
    # 模拟 raw chunk 字典形式
    raw_chunk = {
        "chunk_id": "c1",
        "doc_id": "d1",
        "ordinal": 2,
        "text": "sample text",
        "content_hash": "hash_123",
    }
    mock_kb_manager = MagicMock()
    mock_kb_manager.list_chunks = AsyncMock(return_value=[raw_chunk])
    mock_context = MagicMock()
    mock_context.kb_manager = mock_kb_manager

    reader = AstrBotKnowledgeBaseReader(mock_context)
    chunks = await reader.list_chunks("papers")
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, DocumentChunk)
    assert c.chunk_id == "c1"
    assert c.doc_id == "d1"
    assert c.ordinal == 2
    assert c.text == "sample text"
    assert c.content_hash == "hash_123"


@pytest.mark.asyncio
async def test_astrbot_kb_reader_search() -> None:
    # 模拟 raw chunk 对象形式
    class MockRawChunk:

        def __init__(self) -> None:
            self.id = "c2"
            self.doc_id = "d1"
            self.ordinal = 0
            self.text = "search match"
            self.content_hash = "hash_456"

    mock_kb_manager = MagicMock()
    mock_kb_manager.search = AsyncMock(return_value=[MockRawChunk()])
    mock_context = MagicMock()
    mock_context.kb_manager = mock_kb_manager

    reader = AstrBotKnowledgeBaseReader(mock_context)
    results = await reader.search("papers", "query", top_k=5)
    assert len(results) == 1
    assert results[0].chunk_id == "c2"
    assert results[0].text == "search match"


# ── Notion Sync Target 测试 ─────────────────────────────────────


@pytest.fixture
def store() -> InMemorySourceDocumentStore:
    return InMemorySourceDocumentStore()


@pytest.fixture
def notion_config() -> NotionSyncConfig:
    return NotionSyncConfig(
        enabled=True,
        mcp_server_name="notion",
        database_id="test-database-id",
        max_upload_mib=5,
        rate_limit_rps=10,  # 使用较高频控以提速单测，依然具备测试意义
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


@pytest.mark.asyncio
async def test_notion_push_normal_file(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    # 注入文档 Chunks
    await store.add_document(_doc("d1"))
    await store.replace_chunks(
        "d1", [DocumentChunk("c1", "d1", 0, "Chunk text 1", "h1")]
    )

    # 模拟 MCP adapter
    mock_context = MagicMock()
    mock_call_tool = AsyncMock(return_value={"id": "page-12345"})
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    payload = b"small pdf payload data"

    page_id = await target.push(_doc("d1", size=len(payload)), payload)

    # 验证成功的 page_id
    assert page_id == "page-12345"

    # 验证向 MCP 传递了 properties 和 Chunks
    mock_call_tool.assert_called_once()
    args = mock_call_tool.call_args[0]
    assert args[0] == "notion"
    assert args[1] == "create_page"
    arguments = args[2]
    assert arguments["parent"]["database_id"] == "test-database-id"
    assert arguments["properties"]["Name"]["title"][0]["text"]["content"] == "doc_d1.pdf"
    assert "DocID" in arguments["properties"]
    assert "Chunks Preview" in (
        arguments["children"][0]["heading_2"]["rich_text"][0]["text"]["content"]
    )


@pytest.mark.asyncio
async def test_notion_push_large_file_decoupling(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    # 模拟超过 5MiB 的大文档 (5.1 MiB)
    payload_size = int(5.1 * 1024 * 1024)
    doc = _doc("d2", size=payload_size)

    mock_context = MagicMock()
    mock_call_tool = AsyncMock(return_value={"id": "page-large-id"})
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    fake_payload = b"x" * payload_size

    # 执行推送
    page_id = await target.push(doc, fake_payload)

    # 验证推送返回 "skipped:page-large-id"
    assert page_id == "skipped:page-large-id"

    # 验证向 MCP 传递了警示 callout 区块，且无 Chunks Preview
    mock_call_tool.assert_called_once()
    arguments = mock_call_tool.call_args[0][2]
    assert arguments["children"][0]["type"] == "callout"
    assert "已跳过文件二进制镜像" in (
        arguments["children"][0]["callout"]["rich_text"][0]["text"]["content"]
    )


@pytest.mark.asyncio
async def test_notion_rate_limiter(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    # 设置限频为每秒 5 次 (rps=5 -> delay=0.2s)
    notion_config.rate_limit_rps = 5

    mock_context = MagicMock()
    mock_call_tool = AsyncMock(return_value={"id": "page-id"})
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    doc = _doc("d3")
    payload = b"x"

    t0 = time.time()
    await target.push(doc, payload)
    t1 = time.time()

    # 验证经过了至少 0.2s 的频频时延
    assert t1 - t0 >= 0.19  # 考虑系统微秒级精度浮动


@pytest.mark.asyncio
async def test_notion_graceful_degradation(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    # 第一步：模拟全元数据推送报错（比如 Notion Database 没有配置 DocID/Tags 列）
    # 第二步：降级 Name-only 重新调用并成功
    mock_context = MagicMock()
    mock_call_tool = AsyncMock()
    # 模拟第一次抛异常，第二次成功
    mock_call_tool.side_effect = [
        Exception("Notion API Error: property DocID not found"),
        {"id": "page-degraded-id"}
    ]
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    doc = _doc("d4")
    payload = b"x"

    page_id = await target.push(doc, payload)

    # 验证成功返回 page-degraded-id 降级页面
    assert page_id == "degraded:page-degraded-id"
    # 验证一共调用了两次
    assert mock_call_tool.call_count == 2
    # 验证第二次调用时只推送了 Name
    second_call_args = mock_call_tool.call_args_list[1][0][2]
    assert "Name" in second_call_args["properties"]
    assert "DocID" not in second_call_args["properties"]


@pytest.mark.asyncio
async def test_notion_initialize_database(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    notion_config.database_id = ""
    notion_config.parent_page_id = "parent-page"
    notion_config.database_title = "KR Database"
    mock_context = MagicMock()
    mock_call_tool = AsyncMock(return_value={"id": "database-123"})
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    result = await target.initialize_database()

    assert result["status"] == "success"
    assert result["created"] is True
    assert result["database_id"] == "database-123"
    args = mock_call_tool.call_args[0]
    assert args[1] == "create_database"
    assert args[2]["parent"]["page_id"] == "parent-page"
    assert set(args[2]["properties"]) == {"Name", "Collection", "Tags", "DocID"}


@pytest.mark.asyncio
async def test_notion_pull_metadata_updates_only_collection_and_tags(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    await store.add_document(_doc("d5"))
    mock_context = MagicMock()
    mock_context.call_mcp_tool = AsyncMock(return_value={
        "results": [
            {
                "properties": {
                    "DocID": {"rich_text": [{"plain_text": "d5"}]},
                    "Collection": {"select": {"name": "papers"}},
                    "Tags": {"multi_select": [{"name": "rag"}, {"name": "graph"}]},
                    "Name": {"title": [{"plain_text": "renamed.pdf"}]},
                }
            },
            {
                "properties": {
                    "DocID": {"rich_text": [{"plain_text": "missing"}]},
                    "Collection": {"select": {"name": "archive"}},
                    "Tags": {"multi_select": [{"name": "x"}]},
                }
            },
        ]
    })

    target = NotionSyncTarget(notion_config, store, mock_context)
    result = await target.pull_metadata()

    assert result["status"] == "success"
    assert result["updated_count"] == 1
    assert result["skipped_count"] == 1
    assert result["skipped_details"]["schema_missing"] == 1
    doc = await store.get_document("d5")
    assert doc is not None
    assert doc.title == "doc_d5.pdf"
    assert doc.collection == "papers"
    assert doc.tags == ["rag", "graph"]
    args = mock_context.call_mcp_tool.call_args[0]
    assert args[1] == "query_database"
    assert args[2]["database_id"] == "test-database-id"


@pytest.mark.asyncio
async def test_notion_query_database_paging(
    notion_config: NotionSyncConfig, store: InMemorySourceDocumentStore
) -> None:
    mock_context = MagicMock()
    mock_call_tool = AsyncMock()
    mock_call_tool.side_effect = [
        {
            "results": [
                {
                    "properties": {
                        "DocID": {"rich_text": [{"plain_text": "d1"}]},
                        "Collection": {"select": {"name": "papers"}},
                        "Tags": {"multi_select": []},
                        "Name": {"title": [{"plain_text": "doc1.pdf"}]},
                    }
                }
            ],
            "has_more": True,
            "next_cursor": "page-2-cursor"
        },
        {
            "results": [
                {
                    "properties": {
                        "DocID": {"rich_text": [{"plain_text": "d2"}]},
                        "Collection": {"select": {"name": "papers"}},
                        "Tags": {"multi_select": []},
                        "Name": {"title": [{"plain_text": "doc2.pdf"}]},
                    }
                }
            ],
            "has_more": False,
            "next_cursor": None
        }
    ]
    mock_context.call_mcp_tool = mock_call_tool

    target = NotionSyncTarget(notion_config, store, mock_context)
    results = await target._mcp_adapter.query_database(notion_config.database_id)
    
    # 验证拉取了全部两个分页的数据
    assert len(results) == 2
    assert mock_call_tool.call_count == 2
    
    # 验证第二次调用传递了 start_cursor
    second_call_arguments = mock_call_tool.call_args_list[1][0][2]
    assert second_call_arguments["start_cursor"] == "page-2-cursor"
