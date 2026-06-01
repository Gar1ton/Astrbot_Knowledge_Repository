"""薄壳层（Thin Shell，见 ../ARCHITECTURE.md §2）。

AstrBot 框架入口：只做两件事 —— ① 向框架注册命令/回调；② 把每个回调「一行委派」给
event_handler / manager。这里不写任何业务逻辑。换框架时只重写本文件，业务层一行不动。

注意：AstrBot SDK 在此开发环境未安装，故框架注册以注释示意；接入运行态时取消注释并按
metadata.yaml 的字段填写注册元数据（用 core/utils/version.py 读取版本号，避免硬编码）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.event_handler import EventHandler
from core.plugin_initializer import PluginInitializer


class KnowledgeRepositoryPlugin:
    """框架入口薄壳：持有组合根与事件分发器，自身无业务。"""

    def __init__(self, context: Any, raw_config: dict[str, Any] | None = None) -> None:
        self._context = context
        self._raw_config = raw_config or {}
        self._initializer: PluginInitializer | None = None
        self._handler: EventHandler | None = None

    # ── 生命周期 ────────────────────────────────────────────────
    async def initialize(self, data_dir: Path) -> None:
        """框架启动时调用：构造组合根并触发装配。本方法不写业务。"""
        self._initializer = PluginInitializer(self._context, self._raw_config, data_dir)
        await self._initializer.initialize()
        self._handler = EventHandler(self._initializer)

    async def terminate(self) -> None:
        """框架关闭时调用：委派组合根反序拆除资源。"""
        if self._initializer is not None:
            await self._initializer.teardown()

    # ── 框架命令回调：每个「取参 → 委派」，无业务 ────────────────
    # @register_command("kr add")
    async def on_add(
        self,
        file_path: str,
        collection: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """/kr add <file_path> [--collection <col>] [--tag <tags>]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_add(file_path, collection, tags)

    # @register_command("kr sync r2")
    async def on_sync_r2(self) -> str:
        """/kr sync r2"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_sync_r2()

    # @register_command("kr sync notion")
    async def on_sync_notion(self) -> str:
        """/kr sync notion"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_sync_notion()

    # @register_command("kr notion init")
    async def on_notion_init(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> str:
        """/kr notion init [parent_page_id] [database_title]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_notion_init(parent_page_id, database_title)

    # @register_command("kr sync notion --pull")
    async def on_sync_notion_pull(self) -> str:
        """/kr sync notion --pull"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_sync_notion_pull()

    # @register_command("kr sync status")
    async def on_sync_status(self) -> str:
        """/kr sync status"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_sync_status()

    # @register_command("kr quota")
    async def on_quota(self) -> str:
        """/kr quota"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_quota()

    # @register_command("kr collection")
    async def on_collection(
        self,
        action: str,
        name: str | None = None,
        description: str = "",
    ) -> str:
        """/kr collection <action> [name] [description]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_collection(action, name, description)

    # @register_command("kr tag")
    async def on_tag(
        self,
        action: str,
        doc_id: str,
        tags_str: str | None = None,
    ) -> str:
        """/kr tag <action> <doc_id> [tags_str]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_tag(action, doc_id, tags_str)

    # @register_command("kr graph build")
    async def on_graph_build(self, collection: str | None = None) -> str:
        """/kr graph build [--collection <col>]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_graph_build(collection)

    # @register_command("kr graph query")
    async def on_graph_query(self, query: str, top_k: int = 5) -> str:
        """/kr graph query <q> [--top_k <top_k>]"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_graph_query(query, top_k)

    # @register_command("kr agent")
    async def on_agent(self, action: str) -> str:
        """/kr agent <on|off>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_agent(action)

    # @register_event_listener("message")
    async def on_message(self, event: Any) -> Any:
        """普通消息捕获 Hook 骨架 (Phase 5)."""
        if self._handler is None:
            return None
        return await self._handler.on_message(event)


__all__ = ["KnowledgeRepositoryPlugin"]
