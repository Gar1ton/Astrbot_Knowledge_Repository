from __future__ import annotations

# ruff: noqa: E402
import asyncio
import inspect
import json
import logging
import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))


def _purge_stale_local_modules() -> None:
    """Evict cached modules owned by this plugin's unique Python package.

    Two reasons:
    1. Defense in depth against another plugin claiming the same top-level
       name. This plugin used to be named ``core``/``web``/``migrations`` and
       collided with astrbot_plugin_moirai's identically-named packages —
       sys.path ordering made ``core.retrieval_modes`` resolve to moirai's
       ``core`` package instead of ours (see CHANGELOG). Renaming to unique
       names removes the actual risk; eviction here is now just a backstop.
    2. On plugin reload AstrBot re-imports main.py but Python's module cache
       keeps the *old* EventHandler/etc. alive, so new methods added between
       installs are invisible.  Unconditional eviction forces a fresh import
       every time, fixing AttributeError on hot-reload.
    """
    # ``web`` 与 ``migrations`` 是通用目录名：生产代码分别按文件路径加载 server/SQL，
    # 不得从共享进程的 sys.modules 清理同名顶层包，否则会误伤其他插件。
    _OWNED_TOPS = frozenset(("kacore",))

    for name in list(sys.modules.keys()):
        if name == __name__:
            continue
        if name.split(".")[0] in _OWNED_TOPS:
            sys.modules.pop(name, None)


_purge_stale_local_modules()

from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

from kacore.event_handler import EventHandler
from kacore.plugin_initializer import PluginInitializer
from kacore.retrieval_modes import (
    MODE_GRAPH_MIXED,
    MODE_GRAPH_ONLY,
    STRICT_COLLECTION_MODES,
    normalize_retrieval_mode,
)
from kacore.utils import text_chunks

# AstrMessageEvent/ProviderRequest 必须是真实的顶层导入而非 TYPE_CHECKING-only：
# AstrBot core 在 @ka.command(...) 装饰期对本文件的字符串注解（PEP 563）调用
# inspect.signature(handler, eval_str=True)，会在模块全局命名空间里对注解求值；
# 放进 TYPE_CHECKING 会导致运行时 NameError，插件直接加载失败。

_PLUGIN_VERSION = "v1.1.0"
logger = logging.getLogger(__name__)
_RESEARCH_MESSAGE_CHUNK_LIMIT = 1600
_RESEARCH_PARAGRAPH_LIMIT = 700


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
        self._research_tasks: set[asyncio.Task[None]] = set()
        self._pending_notion_force = False

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

    @ka.command("research_language")
    async def ka_research_language(self, event: AstrMessageEvent, value: str = ""):
        '''/ka research_language <cn|en|cn&en> — research 回答语言（召回恒英文；cn&en=跟随提问）'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_research_language(value))

    @ka.command("persona")
    async def ka_persona(self, event: AstrMessageEvent, action: str = ""):
        '''/ka persona <on|off> — astrbot 人格 prompt 开关'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_persona(action))

    @ka.command("webui")
    async def webui(self, event: AstrMessageEvent, action: str = ""):
        '''/ka webui <on|off> — 实时启停 Web 控制台'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_webui(action))

    @ka.command("r2")
    async def ka_r2(self, event: AstrMessageEvent, action: str = "", target: str = ""):
        '''/ka r2 <push|pull|force push|force pull|status> — R2 备份/恢复/容量'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        combined = (action + " " + target).strip()
        message = await self._handler.on_ka_r2(combined)
        yield event.plain_result(message)
        if "任务已启动" in message and self._initializer is not None:
            task = asyncio.create_task(self._watch_r2_job(event))
            self._track_research_task(task)

    @ka.command("notion")
    async def ka_notion(self, event: AstrMessageEvent, action: str = "", target: str = ""):
        '''/ka notion <push|force push|status> — Notion 单向增量推送/状态'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        combined = (action + " " + target).strip()
        message = await self._handler.on_ka_notion(combined)
        yield event.plain_result(message)
        if "任务已启动" in message and self._initializer is not None:
            self._pending_notion_force = "全量" in message
            task = asyncio.create_task(self._watch_notion_job(event))
            self._track_research_task(task)

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

    @ka_zotero.command("account")
    async def ka_zotero_account(self, event: AstrMessageEvent, action: str = ""):
        '''/ka zotero account <replace|cancel> — 处理 Zotero 换号确认'''
        if not self._handler:
            yield event.plain_result("插件未初始化。")
            return
        yield event.plain_result(await self._handler.on_ka_zotero_account(action))

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

        try:
            return json.dumps(await svc.probe(query), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - llm_tool 入口需兜底，不向框架抛出
            logger.error("research_scope_probe failed: %s", exc, exc_info=True)
            return json.dumps(
                {"status": "error", "message": f"范围探查失败：{exc}"}, ensure_ascii=False
            )

    @filter.llm_tool(name="research_execute")
    async def research_execute(
        self,
        event: AstrMessageEvent,
        query: str,
        collection: str = "",
        mode: str = "default",
        breadth: str = "normal",
    ):
        '''在确认范围后执行知识库召回并作答，返回自带 Harvard 引用的答案正文。

        通常在 research_scope_probe 之后、范围已明确或用户已确认时调用。答案正文里的
        in-text 短引 (Author, Year, p. N) 与尾部「参考文献」表均由插件确定性生成，
        **必须原样呈现、勿改写勿重排、勿另行编造引用**。本工具只读，绝不修改任何同步配置。

        Args:
            query(string): 凝练后的自包含检索指令（调令）——把对话意图整理成一条完整、聚焦、
                可独立理解的问题；deep_thinking 时尤其写清要让内部检索 agent 回答的问题。
            collection(string): 召回范围集合名；留空=全局检索。
            mode(string): default=标准召回（查存/单点事实）；enhanced=增强召回（分析/对比/机制类，
                一次拆解+宽召回+自检纠偏，成本远低于 deep_thinking）；deep_thinking=综合分析
                （仅综述/系统梳理级任务）；graph_mixed=图谱混合检索（语义/词法证据 +
                LightRAG 图谱上下文）；graph_only=纯图谱检索（仅 LightRAG 图谱上下文）。
            breadth(string): narrow/normal/wide——问题宽泛时用 wide 放大候选池再重排
                （默认 normal；仅 default 生效，enhanced/deep_thinking 用自身配置管证据量）。
        '''
        svc = self._initializer.research_service if self._initializer else None
        if svc is None or not self._initializer.research_enabled:
            return "research 未开启或未装配，请提示用户先发送 /ka research on。"

        requested_mode, used_legacy_mode = normalize_retrieval_mode(mode)
        if used_legacy_mode:
            logger.warning(
                "research_execute mode='high_precision' is deprecated; use 'graph_mixed'"
            )
        requested_breadth = (breadth or "normal").strip() or "normal"
        resolved_collection = collection or None
        scope_probe: dict[str, Any] | None = None
        if requested_mode in STRICT_COLLECTION_MODES and not resolved_collection:
            try:
                scope_probe = await svc.probe(query)
            except Exception as exc:  # noqa: BLE001 - llm_tool 入口需兜底，不向框架抛出
                logger.error("research_execute scope probe failed: %s", exc, exc_info=True)
                return json.dumps(
                    {"status": "error", "message": f"范围探查失败：{exc}"}, ensure_ascii=False
                )
            resolved_collection = self._collection_from_probe(scope_probe)
            if resolved_collection is None:
                message = self._strict_mode_scope_required_message(requested_mode, scope_probe)
                notice_sent = await self._send_plain_message(event, message)
                return json.dumps(
                    {
                        "status": "needs_scope",
                        "async": False,
                        "mode": requested_mode,
                        "breadth": requested_breadth,
                        "notice_sent": notice_sent,
                        "reason": f"{requested_mode}_requires_collection",
                        "probe": scope_probe,
                        "instruction": (
                            f"{requested_mode} 必须绑定明确 collection。请向用户确认范围后，"
                            "带 collection 参数再次调用 research_execute；不要改用其它 mode。"
                        ),
                    },
                    ensure_ascii=False,
                )

        scope_label = resolved_collection or "全局"
        start_text = self._research_start_message(
            scope_label, requested_mode, requested_breadth
        )
        notice_sent = await self._send_plain_message(event, start_text)

        task = asyncio.create_task(
            self._run_research_execute_background(
                event=event,
                svc=svc,
                query=query,
                collection=resolved_collection,
                mode=requested_mode,
                breadth=requested_breadth,
            )
        )
        self._track_research_task(task)
        return json.dumps(
            {
                "status": "started",
                "async": True,
                "mode": requested_mode,
                "breadth": requested_breadth,
                "scope": scope_label,
                "notice_sent": notice_sent,
                "instruction": (
                    "research_execute 已在后台完整执行；不要重复调用 research_execute，"
                    "完成后插件会主动向用户发送答案。"
                ),
            },
            ensure_ascii=False,
        )

    @filter.llm_tool(name="notion_push_note")
    async def notion_push_note(
        self,
        event: AstrMessageEvent,
        content: str,
        title: str = "",
        tags: str = "",
        citations: str = "",
        keep_local: str = "false",
    ):
        '''把一段研究结论或笔记推送到 Notion 问答库（QA 表），每次推送新增一条记录。

        用户说「把…记到/推到/同步到 Notion」「保存这次研究结果」时调用。content 必须传
        完整正文原文（例如刚完成的 research 答案全文，不要缩写省略）。citations 传该次
        research 返回体里的 citation_doc_ids（逗号分隔），推送后会在 Notion 里链接到对应
        文章条目。默认直推（本地只留存根）；仅当用户明确要求「也存到本地/保存为本地笔记」时
        传 keep_local="true"。Notion 未启用时返回提示文案，请原样转告用户。
        本工具只新增问答记录，绝不修改文档、集合或同步配置。

        Args:
            content(string): 笔记正文全文（Markdown 纯文本）。
            title(string): 问题/标题；留空则自动取正文首行前 60 字符。
            tags(string): 逗号分隔标签，可空，例如 "research,LLM"。
            citations(string): 逗号分隔的引用 DocID（来自 research 返回体），可空。
            keep_local(string): "true"/"false"，默认 "false"。
        '''
        api = self._initializer.api if self._initializer else None
        if api is None:
            return "插件未初始化，无法推送。"
        try:
            result = await api.push_note_to_notion(
                content,
                title=title,
                tags=[t.strip() for t in tags.split(",") if t.strip()],
                citations=[c.strip() for c in citations.split(",") if c.strip()],
                source="research",
                keep_local=str(keep_local).strip().lower() in ("true", "1", "yes"),
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - llm_tool 入口需兜底，不向框架抛出
            logger.error("notion_push_note failed: %s", exc, exc_info=True)
            return json.dumps(
                {"status": "error", "message": f"推送到 Notion 失败：{exc}"},
                ensure_ascii=False,
            )

    # ── 生命周期 ─────────────────────────────────────────────────

    async def terminate(self) -> None:
        if self._research_tasks:
            for task in list(self._research_tasks):
                task.cancel()
            await asyncio.gather(*self._research_tasks, return_exceptions=True)
            self._research_tasks.clear()
        if self._initializer:
            await self._initializer.teardown()

    # ── research 后台任务与主动回发 ───────────────────────────────

    @staticmethod
    def _research_start_message(scope: str, mode: str, breadth: str) -> str:
        if mode == "deep_thinking":
            return (
                f"🔬 已开始 Deep Thinking：范围「{scope}」，breadth={breadth}。"
                "这个任务可能需要几分钟，我会完成后直接发结果。"
            )
        if mode == "enhanced":
            return (
                f"🔍 已开始增强召回：范围「{scope}」。"
                "拆解检索 + 自检纠偏中，稍后直接发结果。"
            )
        if mode == MODE_GRAPH_MIXED:
            return (
                f"🕸️ 已开始图谱混合检索：范围「{scope}」。"
                "正在汇合语义/词法证据与 LightRAG 图谱上下文，稍后直接发结果。"
            )
        if mode == MODE_GRAPH_ONLY:
            return f"🕸️ 已开始纯图谱检索：范围「{scope}」，稍后直接发结果。"
        return f"🔎 已开始检索：范围「{scope}」，mode={mode}，breadth={breadth}。"

    @staticmethod
    def _collection_from_probe(probe: dict[str, Any]) -> str | None:
        if probe.get("ambiguity") != "low":
            return None
        collections = probe.get("collections")
        if not isinstance(collections, list) or not collections:
            return None
        first = collections[0]
        if not isinstance(first, dict):
            return None
        name = str(first.get("name") or "").strip()
        return name or None

    @staticmethod
    def _strict_mode_scope_required_message(mode: str, probe: dict[str, Any]) -> str:
        collections = probe.get("collections")
        candidates: list[str] = []
        if isinstance(collections, list):
            for item in collections[:3]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                score = item.get("match_score")
                candidates.append(f"{name} ({score})" if score is not None else name)
        suffix = ""
        if candidates:
            suffix = "\n候选范围：" + "、".join(candidates)
        mode_label = {
            "deep_thinking": "Deep Thinking",
            MODE_GRAPH_MIXED: "图谱混合检索",
            MODE_GRAPH_ONLY: "纯图谱检索",
        }.get(mode, mode)
        return (
            f"🔬 {mode_label} 需要先锁定一个具体 collection，不能用「全局」范围运行；"
            "否则就不是用户选择的那条检索链。请先确认范围。"
            f"{suffix}"
        )

    def _track_research_task(self, task: asyncio.Task[None]) -> None:
        self._research_tasks.add(task)

        def _done(done_task: asyncio.Task[None]) -> None:
            self._research_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常泄漏到事件循环
                logger.warning("background research task failed: %s", exc, exc_info=True)

        task.add_done_callback(_done)

    async def _run_research_execute_background(
        self,
        *,
        event: AstrMessageEvent,
        svc: Any,
        query: str,
        collection: str | None,
        mode: str,
        breadth: str,
    ) -> None:
        try:
            result = await svc.execute(query, collection, mode=mode, breadth=breadth)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 主动回发失败信息，避免静默吞异常
            logger.warning("background research_execute failed: %s", exc, exc_info=True)
            await self._send_plain_message(event, f"⚠️ research_execute 执行失败：{exc}")
            return

        await self._send_plain_message_chunks(event, self._format_research_result(result))
        if self._notion_push_enabled():
            await self._send_plain_message(
                event,
                "💡 可以说「把这次研究推送到 Notion」，我会把结论保存到 Notion 问答库。",
            )

    def _notion_push_enabled(self) -> bool:
        """Notion 同步是否已启用（用于 research 完成后的推送引导）。"""
        initializer = self._initializer
        if initializer is None or initializer.api is None:
            return False
        config = getattr(initializer, "_config", None)
        if config is None:
            return False
        try:
            return config.get_notion_sync_config().enabled
        except Exception:  # noqa: BLE001 - 引导提示，读配置失败静默不提示
            return False

    async def _watch_notion_job(self, event: AstrMessageEvent) -> None:
        """后台执行 Notion 推送（由 /ka notion push[/force] 触发）并回发汇总。

        force 由 handler 返回文案中的「全量」标记推导（与 R2 的 watch 模式一致）。
        """
        api = self._initializer.api if self._initializer else None
        if api is None:
            return
        force = getattr(self, "_pending_notion_force", False)
        self._pending_notion_force = False
        try:
            result = await api.sync_documents("notion", force=force)
        except Exception as exc:  # noqa: BLE001 - 后台任务回发失败信息
            logger.warning("notion push failed: %s", exc, exc_info=True)
            await self._send_plain_message(event, f"⚠️ Notion 推送失败：{exc}")
            return
        status = result.get("status")
        if status in ("disabled", "error"):
            await self._send_plain_message(
                event, f"⚠️ Notion 推送未执行：{result.get('message', status)}"
            )
            return
        if status == "already_running":
            await self._send_plain_message(event, "已有 Notion 推送任务在执行。")
            return
        docs = result.get("documents") or {}
        qa = result.get("qa") or {}
        await self._send_plain_message(
            event,
            "✅ Notion 推送完成："
            f"文章 新增 {docs.get('created', 0)}/更新 {docs.get('updated', 0)}"
            f"/跳过 {docs.get('skipped', 0)}/失败 {docs.get('failed', 0)}，"
            f"QA 推送 {qa.get('pushed', 0)}/失败 {qa.get('failed', 0)}。",
        )

    async def _watch_r2_job(self, event: AstrMessageEvent) -> None:
        manager = self._initializer.r2_backup_manager if self._initializer else None
        if manager is None:
            return
        result = await manager.wait_current()
        if result is None:
            return
        if result.get("status") != "success":
            await self._send_plain_message(
                event, f"⚠️ R2 任务失败：{result.get('message', result.get('status'))}"
            )
            return
        snapshot_id = result.get("snapshot_id") or "latest"
        if result.get("restart_required"):
            suffix = "插件将自动重启。" if result.get("auto_restart") else "请重启插件应用恢复。"
            await self._send_plain_message(
                event, f"✅ R2 完整快照 {snapshot_id} 已下载并验证；{suffix}"
            )
            return
        await self._send_plain_message(
            event,
            f"✅ R2 完整备份完成：snapshot={snapshot_id}，"
            f"files={result.get('file_count', 0)}。",
        )

    def _format_research_result(self, result: dict[str, Any]) -> str:
        answer = self._paragraphize_research_text(
            str(result.get("answer") or "未找到相关内容。").strip()
        )
        scope = str(result.get("scope") or "全局")
        mode = str(result.get("mode") or result.get("requested_mode") or "default")
        requested_mode = str(result.get("requested_mode") or mode)
        if requested_mode == "deep_thinking":
            done_label = "Deep Thinking 完成"
        elif requested_mode == "enhanced":
            done_label = "增强召回完成"
        elif requested_mode == MODE_GRAPH_MIXED:
            done_label = "图谱混合检索完成"
        elif requested_mode == MODE_GRAPH_ONLY:
            done_label = "纯图谱检索完成"
        else:
            done_label = "检索完成"
        parts = [
            f"✅ {done_label}",
            f"范围：{scope}；模式：{mode}",
        ]
        # v1.1.0：校验告警前置到正文之前——读完整篇才发现「未通过证据校验」为时已晚。
        # 三个出口（WebUI 气泡 / 本聊天路径 / 存库回放）统一为「告警 → 正文」同序。
        notice = str(result.get("answer_notice") or "").strip()
        if notice:
            parts.extend(["", f"⚠️ {notice}"])
        parts.extend(["", answer])
        # 不再单独渲染「引用：」段：v1.1.0 起 api.ask 已把 Harvard 参考文献表拼进正文尾部，
        # 这里再列一遍就是发两份书目。`citations` 字段本身保留，供 notion_push_note 等调用方使用。
        return "\n".join(parts)

    async def _send_plain_message_chunks(
        self,
        event: AstrMessageEvent,
        text: str,
        *,
        limit: int = _RESEARCH_MESSAGE_CHUNK_LIMIT,
    ) -> bool:
        chunks = self._split_message_text(text, limit=limit)
        ok = True
        for chunk in chunks:
            ok = await self._send_plain_message(event, chunk) and ok
        return ok

    # 文本切分薄委派：实现在 kacore/utils/text_chunks（纯函数，v0.30.0 治本修复中文句读硬切）。
    @staticmethod
    def _split_message_text(text: str, *, limit: int = _RESEARCH_MESSAGE_CHUNK_LIMIT) -> list[str]:
        return text_chunks.split_message_text(text, limit=limit)

    @staticmethod
    def _paragraphize_research_text(
        text: str, *, max_chars: int = _RESEARCH_PARAGRAPH_LIMIT
    ) -> str:
        return text_chunks.paragraphize(text, max_chars=max_chars)

    async def _send_plain_message(self, event: AstrMessageEvent, text: str) -> bool:
        result = event.plain_result(text) if hasattr(event, "plain_result") else text

        event_send = getattr(event, "send", None)
        if callable(event_send):
            try:
                maybe = event_send(result)
                if inspect.isawaitable(maybe):
                    await maybe
                return True
            except Exception as exc:
                logger.warning("event.send failed, trying context.send_message: %s", exc)

        origin = getattr(event, "unified_msg_origin", None)
        context_send = getattr(self.context, "send_message", None)
        if origin and callable(context_send):
            payloads = self._context_message_payloads(text, result)
            for payload in payloads:
                try:
                    maybe = context_send(origin, payload)
                    if inspect.isawaitable(maybe):
                        await maybe
                    return True
                except Exception as exc:
                    logger.warning("context.send_message payload failed: %s", exc)
        logger.warning("no available AstrBot send method for research notice")
        return False

    @staticmethod
    def _context_message_payloads(text: str, fallback: Any) -> list[Any]:
        payloads: list[Any] = []
        try:
            from astrbot.api.message_components import MessageChain

            payloads.append(MessageChain().message(text))
        except Exception:
            pass
        payloads.extend([fallback, text])
        return payloads
