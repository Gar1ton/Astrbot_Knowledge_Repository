from __future__ import annotations
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

from core.plugin_initializer import PluginInitializer
from core.event_handler import EventHandler
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api.event import filter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest

_PLUGIN_VERSION = "v0.15.1"


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
    async def on_message(self, event: "AstrMessageEvent"):
        if self._handler:
            answer = await self._handler.on_message(event)
            if answer is not None:
                yield event.plain_result(answer)

    @filter.on_llm_request()
    async def on_llm_request(self, event: "AstrMessageEvent", req: "ProviderRequest") -> None:
        if self._handler:
            await self._handler.on_llm_request(event, req)

    # ── 命令组 /kr ───────────────────────────────────────────────

    @filter.command_group("kr")
    def kr():
        pass

    @kr.command("add")
    async def kr_add(self, event: "AstrMessageEvent", file_path: str, collection: str = "", tags: str = ""):
        '''/kr add <file_path> [collection] [tags(逗号分隔)]'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        yield event.plain_result(
            await self._handler.on_add(file_path, collection or None, tag_list)
        )

    @kr.command("quota")
    async def kr_quota(self, event: "AstrMessageEvent"):
        '''/kr quota — 显示存储配额'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_quota())

    @kr.command("agent")
    async def kr_agent(self, event: "AstrMessageEvent", action: str):
        '''/kr agent <on|off> — 启用/关闭 RAG 注入'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_agent(action))

    @kr.command("collection")
    async def kr_collection(self, event: "AstrMessageEvent", action: str, name: str = "", description: str = ""):
        '''/kr collection <list|create|delete> [name] [description]'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(
            await self._handler.on_collection(action, name or None, description)
        )

    @kr.command("tag")
    async def kr_tag(self, event: "AstrMessageEvent", action: str, doc_id: str, tags_str: str = ""):
        '''/kr tag <set|show> <doc_id> [tags(逗号分隔)]'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(
            await self._handler.on_tag(action, doc_id, tags_str or None)
        )

    # ── /kr sync 子组 ────────────────────────────────────────────

    @kr.group("sync")
    def kr_sync():
        pass

    @kr_sync.command("r2")
    async def kr_sync_r2(self, event: "AstrMessageEvent"):
        '''/kr sync r2 — 同步到 Cloudflare R2'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_sync_r2())

    @kr_sync.command("notion")
    async def kr_sync_notion(self, event: "AstrMessageEvent"):
        '''/kr sync notion — 推送到 Notion'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_sync_notion())

    @kr_sync.command("status")
    async def kr_sync_status(self, event: "AstrMessageEvent"):
        '''/kr sync status — 查看同步状态'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_sync_status())

    # ── /kr notion 子组 ──────────────────────────────────────────

    @kr.group("notion")
    def kr_notion():
        pass

    @kr_notion.command("init")
    async def kr_notion_init(self, event: "AstrMessageEvent", parent_page_id: str = "", database_title: str = ""):
        '''/kr notion init [parent_page_id] [database_title]'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(
            await self._handler.on_notion_init(parent_page_id or None, database_title or None)
        )

    @kr_notion.command("pull")
    async def kr_notion_pull(self, event: "AstrMessageEvent"):
        '''/kr notion pull — 从 Notion 拉取元数据'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_sync_notion_pull())

    # ── /kr graph 子组 ───────────────────────────────────────────

    @kr.group("graph")
    def kr_graph():
        pass

    @kr_graph.command("build")
    async def kr_graph_build(self, event: "AstrMessageEvent", collection: str = ""):
        '''/kr graph build [collection] — 构建知识图谱'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_graph_build(collection or None))

    @kr_graph.command("query")
    async def kr_graph_query(self, event: "AstrMessageEvent", query: str, top_k: int = 5):
        '''/kr graph query <q> [top_k] — 查询知识图谱'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_graph_query(query, top_k))

    # ── 生命周期 ─────────────────────────────────────────────────

    async def terminate(self) -> None:
        if self._initializer:
            await self._initializer.teardown()
