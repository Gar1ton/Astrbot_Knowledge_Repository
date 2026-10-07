"""Notion MCP 运行态工具调用适配器（防腐层）。

职责：把内部同步请求翻译成宿主 AstrBot 已连接的 Notion MCP Server
（@suekou/mcp-notion-server，工具名带 notion_ 前缀）的真实工具调用，并统一处理
传输（断线重连/超时）、全局频控、结果解包（CallToolResult → dict）与显式报错。

为什么存在：屏蔽宿主 MCP 传输细节，业务层（sync_targets）只面对结构化 dict
与 NotionMCPError；测试经 tool_caller 注入 fake，不 mock 宿主深层对象。
真实调用路径（已核实宿主源码）：context.get_llm_tool_manager()
→ .mcp_client_dict[server_name] → MCPClient.call_tool_with_reconnect(
tool_name, arguments, read_timeout_seconds=timedelta)，返回 mcp CallToolResult。

工具契约锁定 @suekou/mcp-notion-server **2.0.2** / Notion API 2026-03-11。
database 是容器，query/schema/item 操作解析到明确的 data_source_id；多源库必须指定目标。
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
ToolLister = Callable[[], Awaitable[list[str]]]

NOTION_SYNC_TOOLS = frozenset({
    "notion_retrieve_database", "notion_retrieve_data_source", "notion_query_data_source",
    "notion_update_data_source", "notion_create_data_source_item",
    "notion_update_page_properties", "notion_retrieve_block_children",
    "notion_append_block_children", "notion_delete_block",
})


class NotionMCPError(RuntimeError):
    """Notion MCP 调用失败：server 未连接、工具执行报错或结果形状不可用。

    message 面向运维可读（含 server/工具名与建议动作）。调用方捕获后应记
    failed/degraded 账并向上反馈，禁止吞掉当成功——本适配层不再提供离线
    stub 假 uuid（历史实现的静默空转即源于此）。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    @property
    def is_not_found(self) -> bool:
        """Notion 明确报告远端对象不存在；删除调用可把它视为幂等 miss。"""
        text = str(self).lower()
        return (
            self.code == "object_not_found"
            or self.status == 404
            or "object_not_found" in text
            or "404" in text
        )


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
        tool_lister: ToolLister | None = None,
        read_timeout_sec: int = 30,
        rate_limit_rps: float = 3.0,
    ) -> None:
        self._context = context
        self._server_name = server_name
        self._tool_caller = tool_caller
        self._tool_lister = tool_lister
        self._read_timeout_sec = read_timeout_sec
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._last_call_monotonic = 0.0
        self._throttle_lock = asyncio.Lock()
        self.request_count = 0
        self._data_sources: dict[str, str] = {}
        self._configured_sources: dict[str, str] = {}

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

    def _get_client(self) -> Any:
        """每次按服务名获取宿主客户端，跟随宿主重连/替换。"""
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
        return client

    async def check_capabilities(self, *, initialize: bool = False) -> None:
        """只检查工具清单，不调用写工具；失败不得当作兼容或缓存成功。"""
        self._data_sources.clear()  # 每轮重新验证目标，避免沿用旧连接/旧容器结果。
        try:
            if self._tool_lister is not None:
                names = await self._tool_lister()
            else:
                client = self._get_client()
                response = await asyncio.wait_for(
                    client.list_tools_and_save(), timeout=self._read_timeout_sec
                )
                names = [tool.name for tool in response.tools]
            if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
                raise ValueError("工具清单形状异常")
        except Exception as exc:
            raise NotionMCPError(
                f"无法检查 MCP server '{self._server_name}' 的工具能力：{exc}",
                code="capability_check_failed",
            ) from exc
        required = NOTION_SYNC_TOOLS | ({"notion_create_database"} if initialize else set())
        missing = sorted(required - set(names))
        if missing:
            raise NotionMCPError(
                f"MCP server '{self._server_name}' 接口不兼容，缺少工具：{', '.join(missing)}。"
                "请使用 @suekou/mcp-notion-server@2.0.2 并重连服务；仅补填 ID 不能解决。",
                code="mcp_incompatible",
            )

    async def _call_real(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        client = self._get_client()
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

    @staticmethod
    def _embedded_error(data: Any, tool_name: str) -> NotionMCPError | None:
        """识别 v1.2.x 把异常包进成功 content 的 ``{"error": ...}`` 形状。"""
        if not isinstance(data, dict) or "error" not in data:
            return None
        raw = data.get("error")
        code = str(data.get("error_code") or "")
        status: int | None = None
        message = ""
        if isinstance(raw, dict):
            code = str(raw.get("code") or code)
            raw_status = raw.get("status")
            if isinstance(raw_status, int):
                status = raw_status
            message = str(raw.get("message") or raw.get("body") or raw.get("name") or "")
        elif raw is not None:
            message = str(raw)
        detail = message[:500] or "（无错误详情）"
        return NotionMCPError(
            f"MCP 工具 {tool_name} 执行报错：{detail}",
            code=code,
            status=status,
        )

    def _unwrap(self, result: Any, tool_name: str) -> Any:
        """CallToolResult/字符串 → dict|list；isError → NotionMCPError。

        测试 tool_caller 可直接返回 dict/list（视为已解包）。非 JSON 文本
        原样返回（个别工具可能返回纯文本）。
        """
        if result is None:
            raise NotionMCPError(f"MCP 工具 {tool_name} 返回空结果。")
        if isinstance(result, dict):
            embedded = self._embedded_error(result, tool_name)
            if embedded is not None:
                raise embedded
            return result
        if isinstance(result, list):
            return result
        content = getattr(result, "content", None)
        if content is not None:
            text = "".join(getattr(item, "text", "") for item in content if hasattr(item, "text"))
            if getattr(result, "isError", False):
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                embedded = self._embedded_error(parsed, tool_name)
                if embedded is not None:
                    raise embedded
                raise NotionMCPError(
                    f"MCP 工具 {tool_name} 执行报错：{text[:500] or '（无错误详情）'}"
                )
            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, (dict, list)):
                embedded = self._embedded_error(structured, tool_name)
                if embedded is not None:
                    raise embedded
                return structured
            result = text
        if isinstance(result, str):
            try:
                decoded = json.loads(result)
            except Exception:
                return result
            embedded = self._embedded_error(decoded, tool_name)
            if embedded is not None:
                raise embedded
            return decoded
        return result

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        args = {**arguments, "format": "json"}
        await self._throttle()
        self.request_count += 1
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
            if not isinstance(results, list):
                raise NotionMCPError(f"MCP 工具 {tool_name} 返回结果缺少 results。")
            if any(not isinstance(r, dict) for r in results):
                raise NotionMCPError(f"MCP 工具 {tool_name} 返回无效分页条目。")
            all_results.extend(results)
            start_cursor = data.get("next_cursor")
            if data.get("has_more") and not start_cursor:
                raise NotionMCPError(f"MCP 工具 {tool_name} 分页缺少 next_cursor。")
            if not (data.get("has_more") and start_cursor):
                return all_results
        raise NotionMCPError(f"Notion {tool_name} 超过分页上限，拒绝将部分结果视为完整。")

    def configure_data_sources(self, sources: dict[str, str]) -> None:
        """登记明确的容器→源配置；改变目标时清除解析缓存。"""
        for database_id, source_id in sources.items():
            if self._configured_sources.get(database_id, "") != source_id:
                self._data_sources.pop(database_id, None)
            self._configured_sources[database_id] = source_id

    async def resolve_data_source(self, database_id: str) -> str:
        """验证配置源属于容器；单源自动解析，零源/多源歧义显式失败。"""
        if database_id in self._data_sources:
            return self._data_sources[database_id]
        data = await self.retrieve_database(database_id)
        if "data_sources" not in data:
            raise NotionMCPError(
                "Notion database 响应缺少 data_sources，接口/响应不兼容。"
                "请使用 @suekou/mcp-notion-server@2.0.2 并重连服务；仅补填 ID 不能解决。",
                code="mcp_incompatible",
            )
        sources = data.get("data_sources")
        if not isinstance(sources, list) or any(
            not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"].strip()
            for s in sources
        ):
            raise NotionMCPError("Notion data_sources 字段形状异常。", code="invalid_response")
        ids = [s["id"] for s in sources]
        if not ids:
            raise NotionMCPError("目标 database 没有数据源，请检查目标库。", code="no_data_source")
        configured = self._configured_sources.get(database_id, "")
        if configured:
            if configured not in ids:
                raise NotionMCPError(
                    "配置的 data_source_id 不属于目标 database，请检查配置。",
                    code="data_source_mismatch",
                )
            source_id = configured
        elif len(ids) == 1:
            source_id = ids[0]
        else:
            raise NotionMCPError(
                "目标 database 有多个数据源，请明确配置 data_source_id。",
                code="ambiguous_data_source",
            )
        self._data_sources[database_id] = source_id
        return source_id

    async def retrieve_data_source(self, database_id: str) -> dict[str, Any]:
        """按容器解析目标 data source，读取完整 schema。"""
        source_id = await self.resolve_data_source(database_id)
        data = await self._call_tool("notion_retrieve_data_source", {"data_source_id": source_id})
        if not isinstance(data, dict) or not isinstance(data.get("properties"), dict):
            raise NotionMCPError("notion_retrieve_data_source 返回结果缺少 properties。")
        return data

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
                "initial_data_source": {"properties": properties},
            },
        )
        return self._require_id(data, "notion_create_database")

    async def retrieve_database(self, database_id: str) -> dict[str, Any]:
        """读取 database 容器（含 data_sources，不含属性 schema）。"""
        data = await self._call_tool("notion_retrieve_database", {"database_id": database_id})
        if not isinstance(data, dict):
            raise NotionMCPError("notion_retrieve_database 返回结果形状异常。")
        return data

    async def update_database(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """便利封装：解析容器后向 data source 增补/修改属性列。"""
        source_id = await self.resolve_data_source(database_id)
        data = await self._call_tool(
            "notion_update_data_source",
            {"data_source_id": source_id, "properties": properties},
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
        source_id = await self.resolve_data_source(database_id)
        arguments: dict[str, Any] = {
            "data_source_id": source_id,
            "page_size": page_size,
            "response_mode": "full",
        }
        if filter is not None:
            arguments["filter"] = filter
        return await self._paged_results("notion_query_data_source", arguments)

    async def create_database_item(self, database_id: str, properties: dict[str, Any]) -> str:
        """在 database 中新建一行（页面），返回 page_id。

        注意：该 MCP server 的 create_database_item 不支持 children，
        正文块须随后经 append_blocks(page_id, ...) 追加。
        """
        source_id = await self.resolve_data_source(database_id)
        data = await self._call_tool(
            "notion_create_data_source_item",
            {"data_source_id": source_id, "properties": properties},
        )
        return self._require_id(data, "notion_create_data_source_item")

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
            "notion_retrieve_block_children",
            {"block_id": block_id, "page_size": 100, "response_mode": "full"},
        )

    async def delete_block(self, block_id: str) -> bool:
        """删除（归档）一个块；页面也是块，归档页面同样走此工具。"""
        await self._call_tool("notion_delete_block", {"block_id": block_id})
        return True


__all__ = ["NotionMCPAdapter", "NotionMCPError", "ToolCaller"]
