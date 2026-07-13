"""单元测试：NotionMCPAdapter（真实工具名、显式错误、频控、分页、解包）。

重点回归历史缺陷：旧适配层用无前缀工具名 + 离线 stub 假 uuid 导致真实环境
静默空转——本套用例断言工具名带 notion_ 前缀、未连接必须显式抛错。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

import kacore.adapters.notion_mcp as notion_mcp
from kacore.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError

# ── 测试基建 ────────────────────────────────────────────────────


@dataclass
class FakeToolCaller:
    """记录调用并按脚本返回的 tool_caller fake。"""

    responses: list[Any] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool_name, arguments))
        if not self.responses:
            return {"id": "auto-id"}
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _adapter(caller: FakeToolCaller, **kwargs: Any) -> NotionMCPAdapter:
    kwargs.setdefault("rate_limit_rps", 1000)  # 单测默认不受频控拖慢
    return NotionMCPAdapter(None, "notion", tool_caller=caller, **kwargs)


@dataclass
class _TextContent:
    text: str


@dataclass
class _FakeCallToolResult:
    content: list[Any]
    isError: bool = False


# ── 工具名与参数契约 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_calls_use_prefixed_names_and_json_format() -> None:
    caller = FakeToolCaller(
        responses=[
            {"id": "db-1"},
            {"id": "db-1", "properties": {}},
            {},
            {"results": [], "has_more": False},
            {"id": "page-1"},
            {},
            {},
            {"results": [], "has_more": False},
            {},
        ]
    )
    adapter = _adapter(caller)

    await adapter.create_database("parent-1", "Lib", {"Name": {"title": {}}})
    await adapter.retrieve_database("db-1")
    await adapter.update_database("db-1", {"Tags": {"multi_select": {}}})
    await adapter.query_database("db-1")
    await adapter.create_database_item("db-1", {"Name": {"title": []}})
    await adapter.update_page_properties("page-1", {"Name": {"title": []}})
    await adapter.append_blocks("page-1", [{"type": "paragraph"}])
    await adapter.list_block_children("page-1")
    await adapter.delete_block("block-1")

    expected_tools = [
        "notion_create_database",
        "notion_retrieve_database",
        "notion_update_database",
        "notion_query_database",
        "notion_create_database_item",
        "notion_update_page_properties",
        "notion_append_block_children",
        "notion_retrieve_block_children",
        "notion_delete_block",
    ]
    assert [name for name, _ in caller.calls] == expected_tools
    # 每次调用都显式携带 format=json（防御宿主开启 markdown 转换）
    assert all(args.get("format") == "json" for _, args in caller.calls)


@pytest.mark.asyncio
async def test_create_database_payload_shape() -> None:
    caller = FakeToolCaller(responses=[{"id": "db-9"}])
    adapter = _adapter(caller)

    database_id = await adapter.create_database(
        "parent-9", "Knowledge", {"Name": {"title": {}}}
    )

    assert database_id == "db-9"
    _, args = caller.calls[0]
    assert args["parent"] == {"type": "page_id", "page_id": "parent-9"}
    assert args["title"][0]["text"]["content"] == "Knowledge"


@pytest.mark.asyncio
async def test_create_database_item_returns_page_id_without_children() -> None:
    caller = FakeToolCaller(responses=[{"id": "page-7"}])
    adapter = _adapter(caller)

    page_id = await adapter.create_database_item("db-1", {"Name": {"title": []}})

    assert page_id == "page-7"
    _, args = caller.calls[0]
    assert "children" not in args  # 该 server 不支持随建页带正文


# ── 分页 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_database_paging_and_filter_passthrough() -> None:
    caller = FakeToolCaller(
        responses=[
            {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "cur-2"},
            {"results": [{"id": "p2"}], "has_more": False, "next_cursor": None},
        ]
    )
    adapter = _adapter(caller)
    doc_filter = {"property": "DocID", "rich_text": {"equals": "d1"}}

    results = await adapter.query_database("db-1", filter=doc_filter)

    assert [r["id"] for r in results] == ["p1", "p2"]
    assert caller.calls[0][1]["filter"] == doc_filter
    assert caller.calls[1][1]["start_cursor"] == "cur-2"


@pytest.mark.asyncio
async def test_query_database_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_mcp, "_MAX_QUERY_PAGES", 3)
    caller = FakeToolCaller(
        responses=[
            {"results": [{"id": f"p{i}"}], "has_more": True, "next_cursor": "same"}
            for i in range(10)
        ]
    )
    adapter = _adapter(caller)

    results = await adapter.query_database("db-1")

    assert len(results) == 3  # 页数上限截断，防无界循环
    assert len(caller.calls) == 3


# ── 错误语义（不再假成功） ──────────────────────────────────────


@pytest.mark.asyncio
async def test_is_error_result_raises() -> None:
    caller = FakeToolCaller(
        responses=[
            _FakeCallToolResult(
                content=[_TextContent("validation_error: DocID missing")],
                isError=True,
            )
        ]
    )
    adapter = _adapter(caller)

    with pytest.raises(NotionMCPError, match="DocID missing"):
        await adapter.create_database_item("db-1", {})


@pytest.mark.asyncio
async def test_missing_server_raises_instead_of_stub() -> None:
    class Manager:
        mcp_client_dict: dict[str, Any] = {}

    class Context:
        def get_llm_tool_manager(self) -> Manager:
            return Manager()

    adapter = NotionMCPAdapter(Context(), "notion", rate_limit_rps=1000)

    with pytest.raises(NotionMCPError, match="未配置或未连接"):
        await adapter.delete_block("b1")


@pytest.mark.asyncio
async def test_unusable_context_raises() -> None:
    adapter = NotionMCPAdapter(None, "notion", rate_limit_rps=1000)

    with pytest.raises(NotionMCPError, match="get_llm_tool_manager"):
        await adapter.delete_block("b1")


@pytest.mark.asyncio
async def test_missing_id_in_response_raises() -> None:
    caller = FakeToolCaller(responses=[{"object": "page"}])
    adapter = _adapter(caller)

    with pytest.raises(NotionMCPError, match="缺少 id"):
        await adapter.create_database_item("db-1", {})


# ── 真实路径（宿主对象形状） ────────────────────────────────────


@pytest.mark.asyncio
async def test_real_path_uses_call_tool_with_reconnect_and_timedelta() -> None:
    captured: dict[str, Any] = {}

    class Client:
        async def call_tool_with_reconnect(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            read_timeout_seconds: timedelta,
        ) -> _FakeCallToolResult:
            captured["tool_name"] = tool_name
            captured["arguments"] = arguments
            captured["timeout"] = read_timeout_seconds
            return _FakeCallToolResult(
                content=[_TextContent(json.dumps({"id": "page-real"}))]
            )

    class Manager:
        mcp_client_dict = {"notion": Client()}

    class Context:
        def get_llm_tool_manager(self) -> Manager:
            return Manager()

    adapter = NotionMCPAdapter(
        Context(), "notion", read_timeout_sec=17, rate_limit_rps=1000
    )
    page_id = await adapter.create_database_item("db-1", {"Name": {"title": []}})

    assert page_id == "page-real"
    assert captured["tool_name"] == "notion_create_database_item"
    assert captured["arguments"]["format"] == "json"
    assert captured["timeout"] == timedelta(seconds=17)  # 必须是 timedelta，不是 int


# ── 解包与频控 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_json_text_returned_as_is() -> None:
    caller = FakeToolCaller(
        responses=[_FakeCallToolResult(content=[_TextContent("plain ok")])]
    )
    adapter = _adapter(caller)

    result = await adapter.update_page_properties("p1", {})

    assert result == {}  # 非 dict 文本 → update_page_properties 归一为空 dict


@pytest.mark.asyncio
async def test_multi_content_text_concatenated() -> None:
    payload = json.dumps({"id": "page-x"})
    caller = FakeToolCaller(
        responses=[
            _FakeCallToolResult(
                content=[_TextContent(payload[:5]), _TextContent(payload[5:])]
            )
        ]
    )
    adapter = _adapter(caller)

    page_id = await adapter.create_database_item("db-1", {})

    assert page_id == "page-x"


@pytest.mark.asyncio
async def test_throttle_enforces_min_interval() -> None:
    caller = FakeToolCaller(responses=[{}, {}, {}])
    adapter = NotionMCPAdapter(
        None, "notion", tool_caller=caller, rate_limit_rps=10
    )  # min interval 0.1s

    t0 = time.monotonic()
    await adapter.delete_block("b1")
    await adapter.delete_block("b2")
    await adapter.delete_block("b3")
    elapsed = time.monotonic() - t0

    assert elapsed >= 0.19  # 3 次调用至少 2 个间隔（容忍计时抖动）
