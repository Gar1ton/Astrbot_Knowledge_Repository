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
    # 内容管理（add/collection/tag/notion/graph）已下沉 WebUI，聊天端不再暴露；
    # 此处仅保留 /ka 运营命令薄壳与消息 hook。

    # @register_command("ka help")
    async def on_ka_help(self) -> str:
        """/ka help"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_help()

    # @register_command("ka status")
    async def on_ka_status(self) -> str:
        """/ka status"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_status()

    # @register_command("ka agent")
    async def on_ka_agent(self, action: str) -> str:
        """/ka agent <on|off>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_agent(action)

    # @register_command("ka research")
    async def on_ka_research(self, action: str) -> str:
        """/ka research <on|off>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_research(action)

    # @register_command("ka persona")
    async def on_ka_persona(self, action: str) -> str:
        """/ka persona <on|off>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_persona(action)

    # @register_command("ka zotero pull")
    async def on_ka_zotero_pull(self) -> str:
        """/ka zotero pull"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_zotero_pull()

    # @register_command("ka webui")
    async def on_ka_webui(self, action: str) -> str:
        """/ka webui <on|off>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_webui(action)

    # @register_command("ka r2")
    async def on_ka_r2(self, action: str) -> str:
        """/ka r2 <push|pull|force push|force pull>"""
        if self._handler is None:
            return "Error: EventHandler not initialized."
        return await self._handler.on_ka_r2(action)

    # @filter.llm_tool("knowledge_research")
    # 运行态在 main.py 真壳用 @filter.llm_tool 注册，委派 initializer.research_skill.handle()。


__all__ = ["KnowledgeRepositoryPlugin"]
