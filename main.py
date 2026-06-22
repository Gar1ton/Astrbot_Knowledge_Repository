from __future__ import annotations

# ruff: noqa: E402
import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))


def _purge_stale_local_modules() -> None:
    """Evict ALL cached core/web/migrations modules on every load.

    Two reasons:
    1. Other plugins (e.g. astrbot_plugin_moirai) expose a top-level ``core``
       package — without eviction we'd import their PluginInitializer.
    2. On plugin reload AstrBot re-imports main.py but Python's module cache
       keeps the *old* EventHandler/etc. alive, so new methods added between
       installs are invisible.  Unconditional eviction forces a fresh import
       every time, fixing AttributeError on hot-reload.
    """
    _OWNED_TOPS = frozenset(("core", "web", "migrations"))

    for name in list(sys.modules.keys()):
        if name == __name__:
            continue
        if name.split(".")[0] in _OWNED_TOPS:
            sys.modules.pop(name, None)


_purge_stale_local_modules()

from typing import TYPE_CHECKING

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools, register

from core.event_handler import EventHandler
from core.plugin_initializer import PluginInitializer

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest

_PLUGIN_VERSION = "v0.28.0"


@register(
    "knowledge_repository",
    "uceiz73",
    "AstrBot 知识库：原件管理、分类、Notion/R2 同步备份与知识图谱",
    _PLUGIN_VERSION,
    "https://github.com/Gar1ton/Astrbot_Knowledge_Repository",
)
class KnowledgeRepositoryPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self._initializer: PluginInitializer | None = None
        self._handler: EventHandler | None = None

    async def initialize(self) -> None:
        data_dir: Path = StarTools.get_data_dir("astrbot_plugin_knowledge_repository")
        raw_cfg = self.config if self.config else {}
        self._initializer = PluginInitializer(self.context, raw_cfg, data_dir)
        await self._initializer.initialize()
        self._handler = EventHandler(self._initializer)

    # ── 消息 Hook（RAG 注入）─────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if self._handler:
            answer = await self._handler.on_message(event)
            if answer is not None:
                yield event.plain_result(answer)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if self._handler:
            await self._handler.on_llm_request(event, req)

    # ── 命令组 /ka（纯运营控制面）──────────────────────────────────

    @filter.command_group("ka")
    def ka():
        pass

    @ka.command("help")
    async def ka_help(self, event: AstrMessageEvent):
        '''/ka help — 指令一览'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_help())

    @ka.command("status")
    async def ka_status(self, event: AstrMessageEvent):
        '''/ka status — 服务框架概览'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_status())

    @ka.command("agent")
    async def ka_agent(self, event: AstrMessageEvent, action: str = ""):
        '''/ka agent <on|off> — ka 与 astrbot 回复关联开关'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_agent(action))

    @ka.command("research")
    async def ka_research(self, event: AstrMessageEvent, action: str = ""):
        '''/ka research <on|off> — research skill 开关'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_research(action))

    @ka.command("persona")
    async def ka_persona(self, event: AstrMessageEvent, action: str = ""):
        '''/ka persona <on|off> — astrbot 人格 prompt 开关'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_persona(action))

    @ka.command("webui")
    async def ka_webui(self, event: AstrMessageEvent, action: str = ""):
        '''/ka webui <on|off> — 实时启停 Web 控制台'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_webui(action))

    @ka.command("r2")
    async def ka_r2(self, event: AstrMessageEvent, action: str = "", target: str = ""):
        '''/ka r2 <push|pull|force push|force pull> — R2 备份/恢复'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        combined = (action + " " + target).strip()
        yield event.plain_result(await self._handler.on_ka_r2(combined))

    # ── /ka zotero 子组 ──────────────────────────────────────────

    @ka.group("zotero")
    def ka_zotero():
        pass

    @ka_zotero.command("pull")
    async def ka_zotero_pull(self, event: AstrMessageEvent):
        '''/ka zotero pull — 触发一次 Zotero 增量同步'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_zotero_pull())

    # ── 自然语言 research skill（LLM 工具）────────────────────────

    @filter.llm_tool(name="knowledge_research")
    async def knowledge_research(self, event: AstrMessageEvent, query: str, depth: str = "auto"):
        '''查询本地知识库，回答关于已收藏文献、学术论文的问题。

        当用户询问具体研究内容、要求文献分析、或引用某篇论文时调用。
        本工具仅做只读检索，绝不修改 Zotero/Notion/R2 的任何同步配置（token/url）。

        Args:
            query(string): 用户的完整问题，原文传入。
            depth(string): quick=快速答案；deep=综合分析；auto=由系统判断（默认 auto）。
        '''
        skill = self._initializer.research_skill if self._initializer else None
        if skill is None:
            yield event.plain_result("research skill 未装配。")
            return
        async for chunk in skill.handle(event, query, depth):
            yield event.plain_result(chunk)

    # ── 生命周期 ─────────────────────────────────────────────────

    async def terminate(self) -> None:
        if self._initializer:
            await self._initializer.teardown()
