"""事件分发（见 event_handler.README.md 与 ../ARCHITECTURE.md §1）。

把框架事件/命令翻译并路由到对应 manager / api，自身不写业务。依赖组合根产出的子系统句柄
（构造器注入），不自造依赖、不直接操作仓储。

v0.28.0：聊天命令从 /kr 整体重写为 /ka（纯运营控制面 + research）。内容管理（add/collection/
tag/notion/graph）已下沉 WebUI，聊天端不再暴露；此处仅保留 /ka 运营命令与消息/LLM hook。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.plugin_initializer import PluginInitializer

logger = logging.getLogger("EventHandler")

# R2 危险操作的二次确认窗口（秒）：窗口内重发相同命令即视为确认。
_CONFIRM_TTL_SEC = 60.0

# /ka r2 各动作的人类可读描述，用于二次确认提示。
_R2_ACTION_DESC = {
    "force push": "忽略增量记录、全量覆盖上传所有文档到 R2",
    "pull": "从 R2 拉取整库快照并覆盖本地数据库（需重启加载）",
    "force pull": "从 R2 强制恢复整库快照、覆盖本地并自动重启插件",
}

_HELP_TEXT = (
    "📖 /ka 指令一览\n"
    "  /ka help                       — 显示本帮助\n"
    "  /ka status                     — 服务框架概览（模型/服务/开关）\n"
    "  /ka agent on|off               — ka 与 astrbot 回复的关联开关\n"
    "  /ka research on|off            — 自然语言 research skill 开关\n"
    "  /ka research_language cn|en|cn&en — research 回答语言（召回恒英文；cn&en=跟随提问，默认）\n"
    "  /ka persona on|off             — astrbot 人格 prompt（off 不污染 research）\n"
    "  /ka zotero pull                — 触发一次 Zotero 增量同步\n"
    "  /ka zotero account replace|cancel — 确认/取消 Zotero 换号重置\n"
    "  /ka r2 push|pull|force push|force pull — R2 备份/恢复（force 与 pull 需二次确认）\n"
    "  /ka webui on|off               — 实时启停 Web 控制台\n"
    "\n内容管理（文档/集合/标签/Notion/知识图谱）请在 WebUI 操作；"
    "research 为只读检索，不会修改任何同步配置。"
)


def _fmt_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(max(value, 0))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f}{unit}" if unit != "B" else f"{int(amount)}B"
        amount /= 1024
    return f"{value}B"


class EventHandler:
    """框架事件分发器：持有已装配的子系统，逐命令一行委派。"""

    def __init__(self, initializer: PluginInitializer) -> None:
        self._initializer = initializer
        # action_key -> 过期时间戳（time.monotonic）；R2 危险操作的待确认令牌。
        self._pending_confirm: dict[str, float] = {}

    # ── 二次确认令牌 ──────────────────────────────────────────────

    def _arm_confirm(self, key: str) -> None:
        self._pending_confirm[key] = time.monotonic() + _CONFIRM_TTL_SEC

    def _consume_confirm(self, key: str) -> bool:
        """存在且未过期则消费并返回 True；否则返回 False。"""
        expiry = self._pending_confirm.pop(key, None)
        return expiry is not None and time.monotonic() <= expiry

    # ── /ka 命令路由 ──────────────────────────────────────────────

    async def on_ka_help(self) -> str:
        """/ka help"""
        return _HELP_TEXT

    async def on_ka_status(self) -> str:
        """/ka status — 服务框架概览。"""
        api = self._initializer.api
        if api is None:
            return "插件未初始化。"
        try:
            status = await api.get_service_status()
        except Exception as e:
            return f"获取状态失败：{e}"

        models = status.get("models", {})
        services = status.get("services", {})
        web = status.get("web_console", {})

        def _onoff(v: bool) -> str:
            return "on" if v else "off"

        lines = ["🧩 KA 服务框架"]
        lines.append("· 模型")
        lines.append(f"    embedding   : {models.get('embedding', 'N/A')}")
        lines.append(f"    vector_db   : {models.get('vector_db', 'N/A')}")
        lines.append(f"    rerank      : {models.get('rerank', 'N/A')}")
        lines.append(f"    deep_think  : {models.get('deep_thinking_llm', 'N/A')}")
        lines.append(f"    lightrag    : {models.get('lightrag_llm', 'N/A')}")
        lines.append("· 服务")
        lines.append(f"    graph       : {_onoff(services.get('graph', False))}")
        lines.append(f"    r2_sync     : {_onoff(services.get('r2_sync', False))}")
        lines.append(f"    notion_sync : {_onoff(services.get('notion_sync', False))}")
        lines.append(
            f"    zotero_sync : {_onoff(services.get('zotero_sync', False))}"
            f"（auto={_onoff(services.get('zotero_auto_sync', False))}）"
        )
        lines.append("· 运行时开关")
        lines.append(f"    agent       : {_onoff(self._initializer.agent_enabled)}")
        lines.append(f"    research    : {_onoff(self._initializer.research_enabled)}")
        _lang_label = {"zh": "cn", "en": "en", "auto": "cn&en"}.get(
            self._initializer.research_answer_language, "cn&en"
        )
        lines.append(f"    research_lang: {_lang_label}（召回恒英文）")
        lines.append(f"    persona     : {_onoff(self._initializer.persona_enabled)}")
        running = self._initializer.web_console_running
        lines.append(
            f"    webui       : {_onoff(running)}"
            f"（http://{web.get('host', '?')}:{web.get('port', '?')}）"
        )
        return "\n".join(lines)

    async def on_ka_agent(self, action: str) -> str:
        """/ka agent <on|off>"""
        return self._toggle("agent", action, "ka 回复关联")

    async def on_ka_research(self, action: str) -> str:
        """/ka research <on|off>"""
        return self._toggle("research", action, "research skill")

    async def on_ka_persona(self, action: str) -> str:
        """/ka persona <on|off>"""
        return self._toggle("persona", action, "astrbot 人格")

    async def on_ka_research_language(self, value: str) -> str:
        """/ka research_language <cn|en|cn&en> — 召回恒英文，此项只定回答语言。"""
        raw = (value or "").strip().lower()
        lang = {"cn": "zh", "zh": "zh", "en": "en", "cn&en": "auto", "auto": "auto"}.get(raw)
        if lang is None:
            return "用法：/ka research_language <cn|en|cn&en>（cn=中文 en=英文 cn&en=跟随提问，默认 cn&en）"
        try:
            self._initializer.set_research_answer_language(lang)
        except Exception as e:
            return f"切换 research 语言失败：{e}"
        label = {"zh": "中文(cn)", "en": "英文(en)", "auto": "跟随提问(cn&en)"}[lang]
        return f"research 回答语言已设为 {label}（召回恒英文，已持久化，重启保留）。"

    def _toggle(self, name: str, action: str, label: str) -> str:
        action = (action or "").strip().lower()
        if action not in ("on", "off"):
            return f"用法：/ka {name} <on|off>"
        try:
            self._initializer.set_toggle(name, action == "on")
        except Exception as e:
            return f"切换 {label} 失败：{e}"
        return f"{label} 已{'开启' if action == 'on' else '关闭'}（已持久化，重启保留）。"

    async def on_ka_zotero_pull(self) -> str:
        """/ka zotero pull — 触发一次 Zotero 增量同步。"""
        api = self._initializer.api
        if api is None:
            return "插件未初始化。"
        try:
            res = await api.sync_zotero_pull(incremental=True)
        except Exception as e:
            return f"Zotero 同步触发失败：{e}"
        status = res.get("status", "")
        if status == "account_change_required":
            old = res.get("current_account") or {}
            new = res.get("new_account") or {}
            return (
                "⚠️ 检测到 Zotero 账号变化："
                f"{old.get('account_name') or old.get('account_id')} → "
                f"{new.get('account_name') or new.get('account_id')}。\n"
                "继续将清空本地 Zotero 镜像（LOCAL 数据不受影响）并自动拉取新账号。\n"
                "发送 `/ka zotero account replace` 确认，或 "
                "`/ka zotero account cancel` 取消。"
            )
        if status in ("error",) or res.get("message", "").startswith("Zotero 同步未启用"):
            return f"Zotero 同步未启动：{res.get('message', status)}"
        return f"Zotero 同步已在后台启动（status={status or 'running'}）。"

    async def on_ka_zotero_account(self, action: str) -> str:
        action = (action or "").strip().lower()
        mapping = {"replace": "replace_local", "cancel": "cancel"}
        if action not in mapping:
            return "用法：/ka zotero account <replace|cancel>"
        api = self._initializer.api
        if api is None:
            return "插件未初始化。"
        try:
            result = await api.resolve_zotero_account_change("", mapping[action])
        except Exception as exc:
            return f"Zotero 换号处理失败：{exc}"
        if result.get("status") == "cancelled":
            return "已取消 Zotero 账号更换；旧 token 与本地数据保持不变。"
        return "Zotero 本地镜像已重置，新账号同步已自动启动。"

    async def on_ka_webui(self, action: str) -> str:
        """/ka webui <on|off> — 实时启停 Web 控制台。"""
        action = (action or "").strip().lower()
        if action not in ("on", "off"):
            return "用法：/ka webui <on|off>"
        try:
            if action == "on":
                ok = await self._initializer.start_web_console()
                if not ok:
                    return (
                        "Web 控制台启动失败：请先在配置中设置 web_console.password "
                        "并确认端口可用。"
                    )
                return "Web 控制台已启动（已持久化，重启保留）。"
            await self._initializer.stop_web_console()
            return "Web 控制台已关闭（已持久化，重启保留）。"
        except Exception as e:
            return f"切换 Web 控制台失败：{e}"

    async def on_ka_r2(self, action: str) -> str:
        """/ka r2 <push|pull|force push|force pull>

        push 直接执行；force push / pull / force pull 需在 60s 内重发同命令确认。
        """
        api = self._initializer.api
        if api is None:
            return "插件未初始化。"
        action = " ".join((action or "").strip().lower().split())
        if action not in ("push", "pull", "force push", "force pull", "status"):
            return "用法：/ka r2 <push|pull|force push|force pull|status>"

        if action == "status":
            status = await api.get_r2_status()
            if status.get("status") != "ok":
                return f"R2 状态读取失败：{status.get('message', status.get('status'))}"
            snapshot = status.get("snapshot") or {}
            job = status.get("job") or {}
            return (
                "R2 状态："
                f"Bucket={_fmt_bytes(int(status.get('bucket_used_bytes') or 0))}，"
                f"插件={_fmt_bytes(int(status.get('plugin_used_bytes') or 0))}，"
                f"最新快照={snapshot.get('snapshot_id') or '无'}，"
                f"任务={job.get('status') or 'idle'}"
            )

        if action == "push":
            return await self._r2_push(force=False)

        confirm_key = f"r2:{action}"
        if not self._consume_confirm(confirm_key):
            self._arm_confirm(confirm_key)
            return (
                f"⚠️ `/ka r2 {action}` 将{_R2_ACTION_DESC[action]}。"
                f"\n如确认，请在 60 秒内再次发送 `/ka r2 {action}`。"
            )

        if action == "force push":
            return await self._r2_push(force=True)
        # pull / force pull：force pull 在恢复后自动重启（跳过手动重启）。
        return await self._r2_pull(auto_restart=(action == "force pull"))

    async def _r2_push(self, force: bool) -> str:
        api = self._initializer.api
        assert api is not None
        try:
            res = await api.backup_now(force=force, background=True)
        except Exception as e:
            return f"R2 上传失败：{e}"
        status = res.get("status")
        label = "强制全量上传" if force else "增量上传"
        if status == "started":
            return f"R2 {label}任务已启动；完成后会主动回发结果。"
        if status == "busy":
            return "已有 R2 任务正在运行，可用 `/ka r2 status` 查看。"
        if status == "success":
            synced = res.get("synced_count", 0)
            failed = res.get("failed_count", 0)
            msg = f"R2 {label}完成：成功 {synced}，失败 {failed}。"
            if res.get("warning"):
                msg += f"\n提示：{res['warning']}"
            return msg
        if status == "blocked":
            return f"R2 {label}被阻断：{res.get('message')}"
        return f"R2 {label}失败：{res.get('message', status)}"

    async def _r2_pull(self, auto_restart: bool) -> str:
        api = self._initializer.api
        assert api is not None
        try:
            res = await api.restore_from_backup(
                auto_restart=auto_restart,
                background=True,
            )
        except Exception as e:
            return f"R2 恢复失败：{e}"
        if res.get("status") == "started":
            mode = "恢复并自动重启" if auto_restart else "恢复"
            return f"R2 {mode}任务已启动；完成后会主动回发结果。"
        if res.get("status") == "busy":
            return "已有 R2 任务正在运行，可用 `/ka r2 status` 查看。"
        if res.get("status") != "success":
            return f"R2 恢复失败：{res.get('message', res.get('status'))}"
        if not auto_restart:
            return "R2 整库快照已恢复，请重启插件以加载恢复后的数据。"
        try:
            await api.restart_plugin()
        except Exception as e:
            return f"R2 整库快照已恢复，但自动重启失败（请手动重启）：{e}"
        return "R2 整库快照已强制恢复，插件正在自动重启以加载数据。"
    # ── LLM Hook（agent 上下文注入）──────────────────────────────

    async def on_llm_request(self, event: Any, req: Any) -> None:
        """agent 开启时，在 LLM 请求前向 req.system_prompt 注入知识库上下文。

        由 main.py 的 @filter.on_llm_request() 触发，仅在 LLM 即将被调用时执行，
        命令处理（/ka ...）不会触发此 hook。主动检索走 knowledge_research skill。
        """
        if not self._initializer.agent_enabled:
            return

        if self._initializer.api is None or self._initializer.retrieval_orchestrator is None:
            return

        query = ""
        if hasattr(event, "message_str"):
            query = str(getattr(event, "message_str")).strip()
        if not query:
            return

        try:
            cols = await self._initializer.api.list_collections()
            all_cols = [c.name for c in cols[:5]] if cols else ["default"]

            chunks = []
            seen_ids: set[str] = set()
            for col in all_cols:
                results = await self._initializer.retrieval_orchestrator.retrieve(
                    collection=col, query=query, top_k=3
                )
                for ch in results:
                    if ch.chunk_id not in seen_ids:
                        seen_ids.add(ch.chunk_id)
                        chunks.append(ch)
                    if len(chunks) >= 3:
                        break
                if len(chunks) >= 3:
                    break

            if not chunks:
                return

            context_lines = []
            for i, chunk in enumerate(chunks):
                doc = await self._initializer.api.get_document(chunk.doc_id)
                title = doc.title if doc else chunk.doc_id
                context_lines.append(f"[{i + 1}] 来源: 《{title}》 | 内容: {chunk.text}")

            grounded_context = "\n".join(context_lines)
            injected_system_prompt = (
                "\n\n[Knowledge Base Context / 插件记忆召回]\n"
                "请优先结合以下从知识库召回的相关文献分块"
                "回答用户的问题，并以 [n] 格式标注引用来源：\n"
                f"{grounded_context}\n"
            )

            req.system_prompt += injected_system_prompt
            logger.info(
                "Injected %d chunks into req.system_prompt via on_llm_request.", len(chunks)
            )
        except Exception as exc:
            logger.error("on_llm_request inject failed: %s", exc)


__all__ = ["EventHandler"]
