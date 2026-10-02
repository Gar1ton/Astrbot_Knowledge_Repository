"""Notion 正文笔记标记（repository 层）：完整读取、增量检查、只勾选不清除。

旧程序 toggle / 大文件 callout 保留并排除；不检查评论，不改变任何删除决策。
扫描水位按 database/data source 隔离，任何读取或写入失败都不推进水位。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from kacore.adapters.notion_mcp import NotionMCPError
from kacore.repository.sync_targets.notion_schema import PROP_DOC_ID, PROP_HAS_NOTES

if TYPE_CHECKING:
    from kacore.adapters.notion_mcp import NotionMCPAdapter
    from kacore.repository.source_store.base import SourceDocumentStore

_LEGACY_PREVIEW = "本地切片摘要 (Chunks Preview)"
_LEGACY_LARGE_FILE = "⚠️ [Notion 免费版限制] 该文件大小超过 5MiB，"
_MAX_BLOCKS = 5000
_MAX_DEPTH = 20


def _text(block: dict[str, Any]) -> str:
    data = block.get(str(block.get("type", "")), {})
    if not isinstance(data, dict):
        raise NotionMCPError("Notion 正文块结构无效。")
    return "".join(
        str(t.get("plain_text") or t.get("text", {}).get("content", ""))
        for t in data.get("rich_text", [])
        if isinstance(t, dict)
    ).strip()


class NotionNotesScanner:
    """MCP 读取正文并设置 checkbox；无 LLM/Embedding，失败不修改已有标记。"""

    def __init__(self, store: SourceDocumentStore, adapter: NotionMCPAdapter) -> None:
        self._store = store
        self._adapter = adapter

    async def scan(self, database_id: str) -> dict[str, int]:
        source_id = await self._adapter.resolve_data_source(database_id)
        scope = f"notes:{database_id}:{source_id}"
        previous = await self._store.get_notion_scan_cursor(scope)
        started = datetime.now(timezone.utc)
        filters: list[dict[str, Any]] = [
            {"property": PROP_DOC_ID, "rich_text": {"is_not_empty": True}},
            {"property": PROP_HAS_NOTES, "checkbox": {"equals": False}},
            {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_before": started.isoformat()},
            },
        ]
        if previous:
            # 两秒重叠覆盖 Notion 时间戳精度；已勾选过滤保证不会反复写入。
            since = datetime.fromisoformat(previous) - timedelta(seconds=2)
            filters.append(
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"on_or_after": since.isoformat()},
                }
            )
        pages = await self._adapter.query_database(database_id, filter={"and": filters})
        stats = {"scanned": 0, "marked": 0}
        for page in pages:
            # 防御 fake/异常服务端过滤失效：只处理本库带 DocID 的文章。
            properties = page.get("properties")
            if not isinstance(properties, dict):
                raise NotionMCPError("笔记检查需要完整页面属性，请使用 response_mode=full。")
            doc_property = properties.get(PROP_DOC_ID, {})
            if not doc_property.get("rich_text"):
                continue
            note_property = properties.get(PROP_HAS_NOTES)
            if not isinstance(note_property, dict) or not isinstance(
                note_property.get("checkbox"), bool
            ):
                raise NotionMCPError("Articles 缺少“已做笔记”checkbox，请先执行同步初始化。")
            if page.get("in_trash") or note_property["checkbox"]:
                continue
            page_id = page.get("id")
            if not isinstance(page_id, str) or not page_id:
                raise NotionMCPError("笔记检查页面缺少 id。")
            stats["scanned"] += 1
            if await self.has_notes(page_id):
                await self._adapter.update_page_properties(
                    page_id, {PROP_HAS_NOTES: {"checkbox": True}}
                )
                stats["marked"] += 1
        await self._store.set_notion_scan_cursor(scope, started.isoformat())
        return stats

    async def has_notes(self, page_id: str) -> bool:
        """按块结构判断正文；空白/分隔线忽略，嵌套空容器继续读取。"""
        remaining = [_MAX_BLOCKS]

        async def visit(parent: str, depth: int) -> bool:
            if depth > _MAX_DEPTH:
                raise NotionMCPError("笔记检查超过嵌套上限，保留原标记。")
            blocks = await self._adapter.list_block_children(parent)
            remaining[0] -= len(blocks)
            if remaining[0] < 0:
                raise NotionMCPError("笔记检查超过块数上限，保留原标记。")
            for block in blocks:
                kind = block.get("type")
                if not isinstance(kind, str) or not kind:
                    raise NotionMCPError("Notion 正文块缺少 type，无法检查笔记。")
                text = _text(block)
                if kind == "toggle" and text == _LEGACY_PREVIEW:
                    continue
                if kind == "callout" and text.startswith(_LEGACY_LARGE_FILE):
                    continue
                if text:
                    return True
                if block.get("has_children"):
                    block_id = block.get("id")
                    if not isinstance(block_id, str) or not block_id:
                        raise NotionMCPError("嵌套正文块缺少 id。")
                    if await visit(block_id, depth + 1):
                        return True
                elif kind not in {
                    "paragraph",
                    "heading_1",
                    "heading_2",
                    "heading_3",
                    "quote",
                    "bulleted_list_item",
                    "numbered_list_item",
                    "toggle",
                    "divider",
                    "to_do",
                    "code",
                    "callout",
                }:
                    # 图片/附件/子页面等结构即用户内容。
                    return True
            return False

        return await visit(page_id, 0)
