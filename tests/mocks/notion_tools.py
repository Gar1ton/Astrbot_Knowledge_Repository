"""Notion MCP v2 工具清单测试注入口，不连接宿主或远端。"""

from __future__ import annotations


async def notion_tools() -> list[str]:
    return [
        "notion_retrieve_database", "notion_retrieve_data_source", "notion_query_data_source",
        "notion_update_data_source", "notion_create_data_source_item", "notion_create_database",
        "notion_update_page_properties", "notion_retrieve_block_children",
        "notion_append_block_children", "notion_delete_block",
    ]
