"""正文笔记标记的保护契约：只勾选、排除旧程序块、完整分页、失败重试。"""

from __future__ import annotations

from typing import Any

import pytest

from kacore.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError
from kacore.config import NotionSyncConfig
from kacore.domain.models import SourceDocument
from kacore.pipelines.notion_sync_pipeline import NotionSyncPipeline
from kacore.repository.source_store.memory import InMemorySourceDocumentStore
from kacore.repository.sync_targets.notion import NotionSyncTarget
from kacore.repository.sync_targets.notion_notes import NotionNotesScanner
from kacore.repository.sync_targets.notion_schema import PROP_HAS_NOTES


def block(kind: str, text: str = "", **extra: Any) -> dict[str, Any]:
    return {"id": "b1", "type": kind, kind: {"rich_text": [{"text": {"content": text}}]}, **extra}


class NotesTools:
    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        self.blocks = blocks
        self.page = {
            "id": "p1",
            "properties": {
                "DocID": {"rich_text": [{"text": {"content": "d1"}}]},
                PROP_HAS_NOTES: {"checkbox": False},
            },
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_read = False

    async def __call__(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, args))
        if tool == "notion_retrieve_database":
            return {"data_sources": [{"id": "ds"}]}
        if tool == "notion_query_data_source":
            pages = [] if self.page["properties"][PROP_HAS_NOTES]["checkbox"] else [self.page]
            return {"results": pages, "has_more": False}
        if tool == "notion_retrieve_block_children":
            if self.fail_read:
                raise NotionMCPError("read failed")
            return {"results": self.blocks, "has_more": False}
        if tool == "notion_update_page_properties":
            self.page["properties"].update(args["properties"])
            return {"id": "p1"}
        raise AssertionError(f"unexpected mutation: {tool}")


def scanner(tools: NotesTools) -> tuple[NotionNotesScanner, InMemorySourceDocumentStore]:
    store = InMemorySourceDocumentStore()
    adapter = NotionMCPAdapter(None, tool_caller=tools, rate_limit_rps=0)
    return NotionNotesScanner(store, adapter), store


@pytest.mark.parametrize(
    "blocks, expected",
    [
        ([], False),
        ([block("paragraph", " \n ")], False),
        ([block("divider")], False),
        ([block("paragraph", "自己的笔记")], True),
        ([block("image")], True),
        ([block("file")], True),
        ([block("child_page")], True),
        ([block("toggle", "本地切片摘要 (Chunks Preview)", has_children=True)], False),
        ([block("callout", "⚠️ [Notion 免费版限制] 该文件大小超过 5MiB，已跳过文件")], False),
        ([block("toggle", "本地切片摘要 (Chunks Preview)"), block("paragraph", "笔记")], True),
    ],
)
async def test_note_rules_preserve_all_content(
    blocks: list[dict[str, Any]], expected: bool
) -> None:
    tools = NotesTools(blocks)
    checker, _ = scanner(tools)
    assert await checker.has_notes("p1") is expected
    assert all(name == "notion_retrieve_block_children" for name, _ in tools.calls)


async def test_nested_empty_container_reads_user_content() -> None:
    async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        assert tool == "notion_retrieve_block_children"
        values = (
            [block("paragraph", "nested note")]
            if args["block_id"] == "b1"
            else [block("toggle", "", has_children=True)]
        )
        return {"results": values, "has_more": False}

    adapter = NotionMCPAdapter(None, tool_caller=call, rate_limit_rps=0)
    assert await NotionNotesScanner(InMemorySourceDocumentStore(), adapter).has_notes("p1")


async def test_scan_marks_once_and_never_unchecks_after_body_cleared() -> None:
    tools = NotesTools([block("paragraph", "note")])
    checker, store = scanner(tools)
    result = await checker.scan("db")
    assert result == {"scanned": 1, "marked": 1}
    assert await store.get_notion_scan_cursor("notes:db:ds")
    tools.blocks = []
    tools.calls.clear()
    assert await checker.scan("db") == {"scanned": 0, "marked": 0}
    assert [name for name, _ in tools.calls] == ["notion_query_data_source"]
    query = tools.calls[0][1]
    assert query["response_mode"] == "full"
    assert any("on_or_after" in f.get("last_edited_time", {}) for f in query["filter"]["and"])
    assert tools.page["properties"][PROP_HAS_NOTES]["checkbox"] is True


async def test_manual_checkbox_is_preserved_without_body_read() -> None:
    tools = NotesTools([])
    tools.page["properties"][PROP_HAS_NOTES]["checkbox"] = True
    checker, _ = scanner(tools)
    await checker.scan("db")
    assert not any(t == "notion_retrieve_block_children" for t, _ in tools.calls)


async def test_read_failure_keeps_checkpoint_then_success_retries() -> None:
    tools = NotesTools([block("paragraph", "note")])
    tools.fail_read = True
    checker, store = scanner(tools)
    await store.set_notion_scan_cursor("notes:db:ds", "2026-09-20T00:00:00+00:00")
    with pytest.raises(NotionMCPError, match="read failed"):
        await checker.scan("db")
    assert await store.get_notion_scan_cursor("notes:db:ds") == "2026-09-20T00:00:00+00:00"
    assert tools.page["properties"][PROP_HAS_NOTES]["checkbox"] is False
    tools.fail_read = False
    assert (await checker.scan("db"))["marked"] == 1


async def test_missing_checkbox_or_truncated_page_does_not_advance_checkpoint() -> None:
    tools = NotesTools([])
    del tools.page["properties"][PROP_HAS_NOTES]

    # 服务返回缺少属性的旧页面，绕过 fake 的过滤逻辑。
    async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "notion_query_data_source":
            return {"results": [tools.page], "has_more": False}
        return await tools(tool, args)

    store = InMemorySourceDocumentStore()
    checker = NotionNotesScanner(store, NotionMCPAdapter(None, tool_caller=call, rate_limit_rps=0))
    with pytest.raises(NotionMCPError, match="checkbox"):
        await checker.scan("db")
    assert await store.get_notion_scan_cursor("notes:db:ds") == ""


async def test_pipeline_reports_note_failure_and_actual_request_attempts() -> None:
    tools = NotesTools([])
    tools.fail_read = True
    store = InMemorySourceDocumentStore()
    adapter = NotionMCPAdapter(None, tool_caller=tools, rate_limit_rps=0)
    target = NotionSyncTarget(
        NotionSyncConfig(enabled=True, database_id="db"), store, adapter=adapter
    )
    result = await NotionSyncPipeline(store, target).push_all()
    assert result["status"] == "error"
    assert result["notes"]["failed"] == 1
    assert result["request_count"] == len(tools.calls)
    assert result["model_tokens"] == 0


async def test_new_article_sync_never_resets_notes_checkbox() -> None:
    props = []

    async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "notion_retrieve_database":
            return {"data_sources": [{"id": "ds"}]}
        if tool == "notion_query_data_source":
            return {"results": [], "has_more": False}
        if tool == "notion_create_data_source_item":
            props.append(args["properties"])
            return {"id": "p1"}
        raise AssertionError(tool)

    store = InMemorySourceDocumentStore()
    target = NotionSyncTarget(
        NotionSyncConfig(enabled=True, database_id="db"),
        store,
        adapter=NotionMCPAdapter(None, tool_caller=call, rate_limit_rps=0),
    )
    doc = SourceDocument("d1", "Title", "/d1.pdf", "application/pdf", 100, "hash", "")
    await target.upsert_document(doc, path="", collection_names=[])
    assert PROP_HAS_NOTES not in props[0]


async def test_body_pagination_reads_later_user_note_and_rejects_incomplete_page() -> None:
    responses = [
        {"results": [block("paragraph", " ")], "has_more": True, "next_cursor": "next"},
        {"results": [block("paragraph", "later note")], "has_more": False},
    ]
    calls = []

    async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return responses.pop(0)

    adapter = NotionMCPAdapter(None, tool_caller=call, rate_limit_rps=0)
    checker = NotionNotesScanner(InMemorySourceDocumentStore(), adapter)
    assert await checker.has_notes("page")
    assert calls[1]["start_cursor"] == "next"
    assert calls[1]["response_mode"] == "full"
    responses.append({"results": [], "has_more": True})
    with pytest.raises(NotionMCPError, match="next_cursor"):
        await checker.has_notes("page")


async def test_checkbox_write_failure_does_not_advance_cursor() -> None:
    tools = NotesTools([block("paragraph", "note")])
    store = InMemorySourceDocumentStore()

    async def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "notion_update_page_properties":
            raise NotionMCPError("write failed")
        return await tools(tool, args)

    checker = NotionNotesScanner(store, NotionMCPAdapter(None, tool_caller=call, rate_limit_rps=0))
    with pytest.raises(NotionMCPError, match="write failed"):
        await checker.scan("db")
    assert await store.get_notion_scan_cursor("notes:db:ds") == ""
    assert not tools.page["properties"][PROP_HAS_NOTES]["checkbox"]
