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

_PLUGIN_VERSION = "v0.28.1"


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

    # ── LLM Hook（agent 上下文注入）──────────────────────────────

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

    # ── 对话式 research（两工具，主 LLM 当指挥）───────────────────
    # 工作流：先 research_scope_probe 了解范围 → 范围明确(ambiguity=low)就直接 research_execute
    # 并在回答里说明用了什么范围；模糊(high)就用自然语言把范围+模式告诉用户、问是否执行，
    # 据用户确认/修正再调用 research_execute。两工具均只读，绝不修改任何同步配置。
    # 注意：@filter.llm_tool 的返回语义（return 字符串回喂 LLM）依 AstrBot SDK，接入需实测。

    @filter.llm_tool(name="research_scope_probe")
    async def research_scope_probe(self, event: AstrMessageEvent, query: str):
        '''探查知识库里与问题相关的范围。返回命中的论文(author-year-title)、集合、标签，
        以及范围是否明确(ambiguity: low/medium/high)、建议召回模式与可用模式。

        用户问到已收藏文献/研究内容时先调用本工具：ambiguity=low 可直接 research_execute；
        medium/high 应先用自然语言把范围与模式告诉用户、询问是否执行。本工具只读。

        Args:
            query(string): 用户的完整问题（结合上下文改写后的检索意图），原文传入。
        '''
        svc = self._initializer.research_service if self._initializer else None
        if svc is None or not self._initializer.research_enabled:
            return "research 未开启或未装配，请提示用户先发送 /ka research on。"
        import json

        return json.dumps(await svc.probe(query), ensure_ascii=False)

    @filter.llm_tool(name="research_execute")
    async def research_execute(
        self,
        event: AstrMessageEvent,
        query: str,
        collection: str = "",
        mode: str = "default",
        breadth: str = "normal",
    ):
        '''在确认范围后执行知识库召回并作答，返回答案 + 确定性引用列表(Author - Year - Title)。

        通常在 research_scope_probe 之后、范围已明确或用户已确认时调用。把答案与引用列表
        原样呈现给用户（引用列表勿改写）。本工具只读，绝不修改任何同步配置。

        Args:
            query(string): 用户问题（结合上下文的检索意图），原文传入。
            collection(string): 召回范围集合名；留空=全局检索。
            mode(string): default=标准召回；deep_thinking=综合分析；high_precision=图谱召回。
            breadth(string): narrow/normal/wide——问题宽泛时用 wide 放大候选池再重排（默认 normal）。
        '''
        svc = self._initializer.research_service if self._initializer else None
        if svc is None or not self._initializer.research_enabled:
            return "research 未开启或未装配，请提示用户先发送 /ka research on。"
        import json

        result = await svc.execute(
            query, collection or None, mode=mode, breadth=breadth
        )
        return json.dumps(result, ensure_ascii=False)

    # ── 生命周期 ─────────────────────────────────────────────────

    async def terminate(self) -> None:
        if self._initializer:
            await self._initializer.teardown()
