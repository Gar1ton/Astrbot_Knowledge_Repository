from __future__ import annotations

# ruff: noqa: E402
import asyncio
import inspect
import json
import logging
import re
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

from typing import TYPE_CHECKING, Any

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools, register

from core.event_handler import EventHandler
from core.plugin_initializer import PluginInitializer

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest

_PLUGIN_VERSION = "v0.28.3"
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

        requested_mode = (mode or "default").strip() or "default"
        requested_breadth = (breadth or "normal").strip() or "normal"
        resolved_collection = collection or None
        scope_probe: dict[str, Any] | None = None
        strict_collection_modes = {"deep_thinking", "high_precision", "graph_only"}
        if requested_mode in strict_collection_modes and not resolved_collection:
            scope_probe = await svc.probe(query)
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

        if requested_mode == "deep_thinking":
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
                        "Deep Thinking 已在后台完整执行；不要重复调用 research_execute，"
                        "完成后插件会主动向用户发送答案。"
                    ),
                },
                ensure_ascii=False,
            )

        result = await svc.execute(
            query, resolved_collection, mode=requested_mode, breadth=requested_breadth
        )
        return json.dumps(result, ensure_ascii=False)

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
        mode_label = "Deep Thinking" if mode == "deep_thinking" else mode
        if mode == "deep_thinking":
            return (
                f"🔬 已开始 {mode_label}：范围「{scope}」，breadth={breadth}。"
                "这个任务可能需要几分钟，我会完成后直接发结果。"
            )
        return f"🔎 已开始检索：范围「{scope}」，mode={mode_label}，breadth={breadth}。"

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
            "high_precision": "LightRAG high_precision",
            "graph_only": "LightRAG graph_only",
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
            logger.warning("Deep Thinking research_execute failed: %s", exc, exc_info=True)
            await self._send_plain_message(event, f"⚠️ Deep Thinking 执行失败：{exc}")
            return

        await self._send_plain_message_chunks(event, self._format_research_result(result))

    @staticmethod
    def _format_research_result(result: dict[str, Any]) -> str:
        answer = self._paragraphize_research_text(
            str(result.get("answer") or "未找到相关内容。").strip()
        )
        scope = str(result.get("scope") or "全局")
        mode = str(result.get("mode") or "deep_thinking")
        citations = [str(item) for item in (result.get("citations") or []) if item]

        parts = [
            "✅ Deep Thinking 完成",
            f"范围：{scope}；模式：{mode}",
            "",
            answer,
        ]
        if citations:
            parts.extend(["", "引用：", *[f"- {item}" for item in citations]])
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

    @staticmethod
    def _split_message_text(text: str, *, limit: int = _RESEARCH_MESSAGE_CHUNK_LIMIT) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        if len(cleaned) <= limit:
            return [cleaned]

        parts = KnowledgeRepositoryPlugin._split_text_by_blocks(cleaned, max_chars=limit - 24)
        if len(parts) == 1:
            return parts
        total = len(parts)
        return [f"（{idx}/{total}）\n{part}" for idx, part in enumerate(parts, start=1)]

    @staticmethod
    def _paragraphize_research_text(
        text: str, *, max_chars: int = _RESEARCH_PARAGRAPH_LIMIT
    ) -> str:
        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        if not blocks:
            return ""
        paragraphs: list[str] = []
        for block in blocks:
            if len(block) <= max_chars or "\n" in block:
                paragraphs.append(block)
                continue
            paragraphs.extend(
                KnowledgeRepositoryPlugin._split_text_by_sentences(block, max_chars=max_chars)
            )
        return "\n\n".join(paragraphs)

    @staticmethod
    def _split_text_by_blocks(text: str, *, max_chars: int) -> list[str]:
        chunks: list[str] = []
        current = ""
        for block in [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]:
            pieces = (
                [block]
                if len(block) <= max_chars
                else KnowledgeRepositoryPlugin._split_text_by_sentences(block, max_chars=max_chars)
            )
            for piece in pieces:
                candidate = f"{current}\n\n{piece}" if current else piece
                if len(candidate) <= max_chars:
                    current = candidate
                    continue
                if current:
                    chunks.append(current)
                if len(piece) <= max_chars:
                    current = piece
                else:
                    chunks.extend(
                        piece[i : i + max_chars] for i in range(0, len(piece), max_chars)
                    )
                    current = ""
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _split_text_by_sentences(text: str, *, max_chars: int) -> list[str]:
        sentences = re.findall(r".+?(?:[。！？!?\.](?=\s|$)|$)", text, flags=re.S)
        if not sentences:
            sentences = [text]
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}" if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(sentence) <= max_chars:
                current = sentence
            else:
                chunks.extend(
                    sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)
                )
                current = ""
        if current:
            chunks.append(current)
        return chunks

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
