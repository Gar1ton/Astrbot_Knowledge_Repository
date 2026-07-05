"""Notion MCP 运行态工具调用适配器（防腐层）。

职责：把内部同步请求翻译成宿主 AstrBot 已连接的 Notion MCP Server
（@suekou/mcp-notion-server，工具名带 notion_ 前缀）的真实工具调用，并统一处理
传输（断线重连/超时）、全局频控、结果解包（CallToolResult → dict）与显式报错。

为什么存在：屏蔽宿主 MCP 传输细节，业务层（sync_targets）只面对结构化 dict
与 NotionMCPError；测试经 tool_caller 注入 fake，不 mock 宿主深层对象。
真实调用路径（已核实宿主源码）：context.get_llm_tool_manager()
→ .mcp_client_dict[server_name] → MCPClient.call_tool_with_reconnect(
tool_name, arguments, read_timeout_seconds=timedelta)，返回 mcp CallToolResult。

⚠️ 工具契约锁定 @suekou/mcp-notion-server **v1.2.x**（notion_query_database /
notion_create_database_item 等）。该包 v2 转向 Data Source API、参数与响应有破坏性
变更；宿主 mcp_server.json 用 `npx -y` 未锁版本，升级到 v2 会使本适配层整体失效。
部署须把宿主 args 锁为 `@suekou/mcp-notion-server@1.2.x`（详见 README 已知风险）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

logger = logging.getLogger("NotionMCPAdapter")

# 单次 query/list 的分页上限（100 条/页 → 2 万条足够任何正常库）。
_MAX_QUERY_PAGES = 200

# 测试注入口签名：async (tool_name, arguments) -> CallToolResult | dict | list | str
ToolCaller = Callable[[str, dict[str, Any]], Awaitable[Any]]


class NotionMCPError(RuntimeError):
    """Notion MCP 调用失败：server 未连接、工具执行报错或结果形状不可用。

    message 面向运维可读（含 server/工具名与建议动作）。调用方捕获后应记
    failed/degraded 账并向上反馈，禁止吞掉当成功——本适配层不再提供离线
    stub 假 uuid（历史实现的静默空转即源于此）。
    """


class NotionMCPAdapter:
    """Notion MCP 适配器：真实工具名 + 显式错误 + 全局频控。

    契约：
    - 所有公开方法失败一律抛 NotionMCPError（含超时/未连接/isError）。
    - 频控在 _call_tool 统一执行（min-interval = 1/rate_limit_rps），
      业务层不得再自行 sleep。
    - 所有调用显式携带 format="json"，防御宿主开启 markdown 转换。
    """

    def __init__(
        self,
        context: Any,
        server_name: str = "notion",
        *,
        tool_caller: ToolCaller | None = None,
        read_timeout_sec: int = 30,
        rate_limit_rps: float = 3.0,
    ) -> None:
        self._context = context
        self._server_name = server_name
        self._tool_caller = tool_caller
        self._read_timeout_sec = read_timeout_sec
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._last_call_monotonic = 0.0
        self._throttle_lock = asyncio.Lock()

    # ── 传输与解包 ──────────────────────────────────────────────

    async def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._throttle_lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call_monotonic)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_monotonic = time.monotonic()

    async def _call_real(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        get_manager = getattr(self._context, "get_llm_tool_manager", None)
        if not callable(get_manager):
            raise NotionMCPError(
                "宿主 context 不可用（缺少 get_llm_tool_manager），无法访问 MCP 工具。"
            )
        manager = get_manager()
        clients = getattr(manager, "mcp_client_dict", None)
        client = None
        if clients is not None:
            try:
                client = clients.get(self._server_name)
            except Exception:
                client = None
        if client is None:
            raise NotionMCPError(
                f"MCP server '{self._server_name}' 未配置或未连接："
                "请在 AstrBot 面板确认该 MCP 服务已启用并连接成功。"
            )
        try:
            return await client.call_tool_with_reconnect(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=self._read_timeout_sec),
            )
        except NotionMCPError:
            raise
        except Exception as e:
            raise NotionMCPError(
                f"MCP 工具 {tool_name} 调用失败（server='{self._server_name}'）：{e}"
            ) from e

    def _unwrap(self, result: Any, tool_name: str) -> Any:
        """CallToolResult/字符串 → dict|list；isError → NotionMCPError。

        测试 tool_caller 可直接返回 dict/list（视为已解包）。非 JSON 文本
        原样返回（个别工具可能返回纯文本）。
        """
        if result is None:
            raise NotionMCPError(f"MCP 工具 {tool_name} 返回空结果。")
        if isinstance(result, (dict, list)):
            return result
        content = getattr(result, "content", None)
        if content is not None:
            text = "".join(
                getattr(item, "text", "") for item in content if hasattr(item, "text")
            )
            if getattr(result, "isError", False):
                raise NotionMCPError(
                    f"MCP 工具 {tool_name} 执行报错：{text[:500] or '（无错误详情）'}"
                )
            result = text
        if isinstance(result, str):
            try:
                return json.loads(result)
            except Exception:
                return result
        return result

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        args = {**arguments, "format": "json"}
        await self._throttle()
        if self._tool_caller is not None:
            raw = await self._tool_caller(tool_name, args)
        else:
            raw = await self._call_real(tool_name, args)
        return self._unwrap(raw, tool_name)

    @staticmethod
    def _require_id(data: Any, tool_name: str) -> str:
        if isinstance(data, dict):
            value = data.get("id") or data.get("page_id") or data.get("database_id")
            if value:
                return str(value)
        raise NotionMCPError(f"MCP 工具 {tool_name} 返回结果缺少 id 字段。")

    async def _paged_results(
        self, tool_name: str, base_arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """按 Notion 分页协议（has_more/next_cursor）聚合 results，带页数上限。"""
        all_results: list[dict[str, Any]] = []
        start_cursor: str | None = None
        for _ in range(_MAX_QUERY_PAGES):
            arguments = dict(base_arguments)
            if start_cursor:
                arguments["start_cursor"] = start_cursor
            data = await self._call_tool(tool_name, arguments)
            if isinstance(data, list):
                all_results.extend(r for r in data if isinstance(r, dict))
                return all_results
            if not isinstance(data, dict):
                raise NotionMCPError(f"MCP 工具 {tool_name} 返回结果形状异常。")
            results = data.get("results")
            if isinstance(results, list):
                all_results.extend(r for r in results if isinstance(r, dict))
            start_cursor = data.get("next_cursor")
            if not (data.get("has_more") and start_cursor):
                return all_results
        logger.warning(
            "Notion %s hit page cap (%d); returning partial results.",
            tool_name,
            _MAX_QUERY_PAGES,
        )
        return all_results

    # ── Database 操作 ───────────────────────────────────────────

    async def create_database(
        self, parent_page_id: str, title: str, properties: dict[str, Any]
    ) -> str:
        """在指定 parent page 下创建 database，返回 database_id。"""
        data = await self._call_tool(
            "notion_create_database",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": properties,
            },
        )
        return self._require_id(data, "notion_create_database")

    async def retrieve_database(self, database_id: str) -> dict[str, Any]:
        """读取 database 元信息（含 properties schema，供建库对账）。"""
        data = await self._call_tool(
            "notion_retrieve_database", {"database_id": database_id}
        )
        if not isinstance(data, dict):
            raise NotionMCPError("notion_retrieve_database 返回结果形状异常。")
        return data

    async def update_database(
        self, database_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        """向已有 database 增补/修改属性列（缺列对账用）。"""
        data = await self._call_tool(
            "notion_update_database",
            {"database_id": database_id, "properties": properties},
        )
        return data if isinstance(data, dict) else {}

    async def query_database(
        self,
        database_id: str,
        *,
        filter: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """查询 database 页面列表，自动分页聚合；filter 透传 Notion 过滤器。"""
        arguments: dict[str, Any] = {"database_id": database_id, "page_size": page_size}
        if filter is not None:
            arguments["filter"] = filter
        return await self._paged_results("notion_query_database", arguments)

    async def create_database_item(
        self, database_id: str, properties: dict[str, Any]
    ) -> str:
        """在 database 中新建一行（页面），返回 page_id。

        注意：该 MCP server 的 create_database_item 不支持 children，
        正文块须随后经 append_blocks(page_id, ...) 追加。
        """
        data = await self._call_tool(
            "notion_create_database_item",
            {"database_id": database_id, "properties": properties},
        )
        return self._require_id(data, "notion_create_database_item")

    # ── Page / Block 操作 ───────────────────────────────────────

    async def update_page_properties(
        self, page_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        """更新页面（database 行）的属性。"""
        data = await self._call_tool(
            "notion_update_page_properties",
            {"page_id": page_id, "properties": properties},
        )
        return data if isinstance(data, dict) else {}

    async def append_blocks(
        self, block_id: str, children: list[dict[str, Any]]
    ) -> None:
        """向页面/块追加子块（页面正文写入的唯一通道）。"""
        await self._call_tool(
            "notion_append_block_children",
            {"block_id": block_id, "children": children},
        )

    async def list_block_children(self, block_id: str) -> list[dict[str, Any]]:
        """列出块的子块（正文重写前盘点用），自动分页聚合。"""
        return await self._paged_results(
            "notion_retrieve_block_children", {"block_id": block_id, "page_size": 100}
        )

    async def delete_block(self, block_id: str) -> bool:
        """删除（归档）一个块；页面也是块，归档页面同样走此工具。"""
        await self._call_tool("notion_delete_block", {"block_id": block_id})
        return True


__all__ = ["NotionMCPAdapter", "NotionMCPError", "ToolCaller"]
