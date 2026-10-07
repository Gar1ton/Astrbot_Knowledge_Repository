"""真实部署故障回归：旧接口不兼容时停止整个批次，而非逐篇失败。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from notion_tools import notion_tools

from kacore.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError
from kacore.api import KnowledgeRepositoryApi
from kacore.config import NotionSyncConfig
from kacore.domain.models import NotionOutboxItem, SourceDocument
from kacore.notion_sync_job import NOTION_STAGE_PREPARING, NotionSyncJob
from kacore.pipelines.notion_sync_pipeline import NotionSyncPipeline
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.sync_targets.notion import NotionSyncTarget


@pytest.mark.parametrize(
    "response, configured, code",
    [
        ({"object": "database", "properties": {}}, "", "mcp_incompatible"),
        ({"object": "database", "properties": {}}, "source", "mcp_incompatible"),
        ({"data_sources": None}, "", "invalid_response"),
        ({"data_sources": {}}, "", "invalid_response"),
        ({"data_sources": [{"id": 42}]}, "", "invalid_response"),
        ({"data_sources": [{}]}, "", "invalid_response"),
        ({"data_sources": []}, "", "no_data_source"),
        ({"data_sources": [{"id": "a"}, {"id": "b"}]}, "", "ambiguous_data_source"),
        ({"data_sources": [{"id": "a"}]}, "b", "data_source_mismatch"),
    ],
)
async def test_resolver_classifies_response(response, configured, code) -> None:
    adapter = NotionMCPAdapter(None, tool_caller=AsyncMock(return_value=response), rate_limit_rps=0)
    adapter.configure_data_sources({"container": configured})
    with pytest.raises(NotionMCPError) as error:
        await adapter.resolve_data_source("container")
    assert error.value.code == code
    if code == "mcp_incompatible":
        assert "2.0.2" in str(error.value)
        assert "不是单源库" not in str(error.value)


async def test_capability_check_detects_old_tools_and_does_not_cache_failure() -> None:
    lister = AsyncMock(side_effect=[["notion_retrieve_database"], await notion_tools()])
    adapter = NotionMCPAdapter(None, tool_lister=lister)
    with pytest.raises(NotionMCPError, match="notion_query_data_source") as error:
        await adapter.check_capabilities()
    assert error.value.code == "mcp_incompatible"
    await adapter.check_capabilities()
    assert lister.await_count == 2


async def test_capability_listing_failure_is_not_version_detection() -> None:
    adapter = NotionMCPAdapter(None, tool_lister=AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(NotionMCPError) as error:
        await adapter.check_capabilities()
    assert error.value.code == "capability_check_failed"


async def test_real_capabilities_follow_client_replacement() -> None:
    first = SimpleNamespace(
        list_tools_and_save=AsyncMock(
            return_value=SimpleNamespace(
                tools=[SimpleNamespace(name="notion_retrieve_database")],
            )
        )
    )
    second = SimpleNamespace(
        list_tools_and_save=AsyncMock(
            return_value=SimpleNamespace(
                tools=[SimpleNamespace(name=n) for n in await notion_tools()],
            )
        )
    )
    manager = SimpleNamespace(mcp_client_dict={"notion": first})
    adapter = NotionMCPAdapter(SimpleNamespace(get_llm_tool_manager=lambda: manager))
    with pytest.raises(NotionMCPError):
        await adapter.check_capabilities()
    manager.mcp_client_dict["notion"] = second
    await adapter.check_capabilities(initialize=True)
    second.list_tools_and_save.assert_awaited_once()


@pytest.mark.parametrize("missing_tools", [True, False])
async def test_106_document_batch_preflight_fails_once(missing_tools: bool) -> None:
    store = InMemorySourceDocumentStore()
    for i in range(106):
        await store.add_document(
            SourceDocument(str(i), "Doc", "/doc.pdf", "pdf", 1, "hash", "default")
        )
    await store.add_notion_outbox(NotionOutboxItem(id="qa", content="保留正文"))
    caller = AsyncMock(return_value={"object": "database", "properties": {}})
    lister = AsyncMock(return_value=[] if missing_tools else await notion_tools())
    adapter = NotionMCPAdapter(None, tool_caller=caller, tool_lister=lister, rate_limit_rps=0)
    target = NotionSyncTarget(
        NotionSyncConfig(enabled=True, database_id="old-id", qa_database_id="qa"),
        store,
        adapter=adapter,
    )
    job = NotionSyncJob()
    result = await NotionSyncPipeline(store, target).push_all(progress=job)
    assert result["status"] == "error"
    assert result["error_code"] == "mcp_incompatible"
    assert job.docs_total == 106 and job.docs_processed == 0 and job.docs_failed == 0
    assert job.stage == NOTION_STAGE_PREPARING
    assert caller.await_count == (0 if missing_tools else 1)
    assert await store.list_notion_entities() == []
    assert await store.list_sync_records() == []
    assert (await store.get_notion_outbox("qa")).content == "保留正文"


async def test_initialization_preflight_stops_before_creation() -> None:
    caller = AsyncMock()
    adapter = NotionMCPAdapter(None, tool_caller=caller, tool_lister=AsyncMock(return_value=[]))
    target = NotionSyncTarget(
        NotionSyncConfig(enabled=True, parent_page_id="parent"),
        InMemorySourceDocumentStore(),
        adapter=adapter,
    )
    with pytest.raises(NotionMCPError) as error:
        await target.initialize_databases()
    assert error.value.code == "mcp_incompatible"
    caller.assert_not_awaited()


async def test_background_job_exposes_one_preflight_error_without_document_failures() -> None:
    store = InMemorySourceDocumentStore()
    for i in range(106):
        await store.add_document(SourceDocument(str(i), "Doc", "/doc.pdf", "pdf", 1, "h", ""))
    adapter = NotionMCPAdapter(
        None,
        tool_caller=AsyncMock(return_value={"object": "database", "properties": {}}),
        tool_lister=notion_tools,
        rate_limit_rps=0,
    )
    target = NotionSyncTarget(
        NotionSyncConfig(enabled=True, database_id="legacy"), store, adapter=adapter
    )
    api = KnowledgeRepositoryApi(source_store=store, kb_reader=InMemoryKnowledgeBaseReader({}))
    api.attach_notion_sync_pipeline(NotionSyncPipeline(store, target))
    await api.sync_notion_push()
    await api._notion_sync_task
    job = api.get_active_notion_sync_job()
    assert job["status"] == "error" and len(job["errors"]) == 1
    assert "2.0.2" in job["recent_error"]
    assert job["docs_total"] == 106 and job["docs_processed"] == 0 and job["docs_failed"] == 0
    assert job["request_count"] == 1 and await store.list_notion_entities() == []
