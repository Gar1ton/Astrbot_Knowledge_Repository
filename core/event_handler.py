"""事件分发（见 event_handler.README.md 与 ../ARCHITECTURE.md §1）。

把框架事件/命令翻译并路由到对应 manager / api，自身不写业务。依赖组合根产出的子系统句柄
（构造器注入），不自造依赖、不直接操作仓储。

v0.3.0 生产实现：实现 /kr add, /kr sync r2, /kr quota, /kr collection, /kr tag 等命令路由。
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.domain.models import SyncStatus, SyncTargetKind

if TYPE_CHECKING:
    from core.plugin_initializer import PluginInitializer

logger = logging.getLogger("EventHandler")


class EventHandler:
    """框架事件分发器：持有已装配的子系统，逐命令一行委派。"""

    def __init__(self, initializer: PluginInitializer) -> None:
        self._initializer = initializer

    def _fmt_size(self, b: int) -> str:
        if b < 1024:
            return f"{b} B"
        if b < 1048576:
            return f"{b / 1024:.1f} KB"
        if b < 1073741824:
            return f"{b / 1048576:.1f} MB"
        return f"{b / 1073741824:.2f} GB"

    # ── 命令路由 ──────────────────────────────────────────────────

    async def on_add(
        self,
        file_path: str,
        collection: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """/kr add <file_path> [--collection <col>] [--tag <tags>]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        title = path.name
        size_bytes = path.stat().st_size

        try:
            with open(path, "rb") as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = "application/octet-stream"

        col = collection or "default"

        try:
            doc_id = await self._initializer.api.register_document(
                title=title,
                file_path=str(path.resolve()),
                content_type=content_type,
                size_bytes=size_bytes,
                content_hash=content_hash,
                collection=col,
                tags=tags,
            )
            return f"Success: Document ingested with ID: {doc_id}"
        except Exception as e:
            return f"Error: Ingestion failed: {e}"

    async def on_sync_r2(self) -> str:
        """/kr sync r2"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            res = await self._initializer.api.sync_documents("r2")
            if res.get("status") == "success":
                synced = res.get("synced_count", 0)
                failed = res.get("failed_count", 0)
                msg = f"Sync successful! Synced: {synced}, Failed: {failed}."
                if "warning" in res:
                    msg += f"\nWarning: {res['warning']}"
                return msg
            elif res.get("status") == "blocked":
                return f"Sync BLOCKED: {res.get('message')}"
            else:
                return f"Sync failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Sync execution failed: {e}"

    async def on_quota(self) -> str:
        """/kr quota"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            usages = await self._initializer.api.list_quota()
            if not usages:
                return "No sync targets configured."
            lines = ["--- Quota Dashboard ---"]
            for u in usages:
                ratio = u.ratio * 100
                used_str = self._fmt_size(u.used_bytes)
                limit_str = self._fmt_size(u.limit_bytes)
                lines.append(
                    f"[{u.target.value}] Used: {used_str} / Limit: {limit_str} ({ratio:.1f}%)"
                )
                if u.detail:
                    lines.append(f"  Detail: {u.detail}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: Failed to fetch quota: {e}"

    async def on_collection(
        self,
        action: str,
        name: str | None = None,
        description: str = "",
    ) -> str:
        """/kr collection <action> [name] [description]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            if action == "list":
                cols = await self._initializer.api.list_collections()
                if not cols:
                    return "No collections found."
                return "\n".join([f"- {c.name}: {c.description}" for c in cols])
            elif action == "create":
                if not name:
                    return "Error: Collection name required."
                await self._initializer.api.create_collection(name, description)
                return f"Collection '{name}' created/updated."
            elif action == "delete":
                if not name:
                    return "Error: Collection name required."
                success = await self._initializer.api.delete_collection(name)
                if success:
                    return f"Collection '{name}' deleted."
                return f"Collection '{name}' not found."
            else:
                return "Invalid collection action. Use 'list', 'create', or 'delete'."
        except Exception as e:
            return f"Error: Collection command failed: {e}"

    async def on_tag(
        self,
        action: str,
        doc_id: str,
        tags_str: str | None = None,
    ) -> str:
        """/kr tag <action> <doc_id> [tags_str]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            if action == "set":
                if not tags_str:
                    return "Error: Tags list required (comma-separated)."
                tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                success = await self._initializer.api.classify_document(doc_id, tags=tags)
                if success:
                    return f"Tags set successfully for document {doc_id}."
                return f"Document {doc_id} not found."
            elif action == "show":
                doc = await self._initializer.api.get_document(doc_id)
                if not doc:
                    return f"Document {doc_id} not found."
                return f"Document '{doc.title}' tags: {', '.join(doc.tags) if doc.tags else 'None'}"
            else:
                return "Invalid tag action. Use 'set' or 'show'."
        except Exception as e:
            return f"Error: Tag command failed: {e}"

    async def on_sync_notion(self) -> str:
        """/kr sync notion"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            # 增量检查，对待推送文档数大于 10 篇给出时延预计警示
            assert self._initializer.source_store is not None
            docs = await self._initializer.source_store.list_documents()
            pending_count = 0
            for doc in docs:
                rec = await self._initializer.source_store.get_sync_record(
                    doc.doc_id, SyncTargetKind.NOTION
                )
                if (
                    rec is None
                    or rec.status != SyncStatus.SYNCED
                    or rec.content_hash != doc.content_hash
                ):
                    pending_count += 1

            warning_msg = ""
            if pending_count > 10:
                notion_cfg = self._initializer.config.get_notion_sync_config()
                est_sec = int(pending_count / max(1, notion_cfg.rate_limit_rps))
                warning_msg = (
                    f"⚠️ [频控提示] 当前有 {pending_count} 篇文档待同步。由于 Notion 3 req/s 频控，"
                    f"预计将耗时约 {est_sec} 秒，后台正在平滑同步中，请耐心等待..."
                )
                logger.warning(warning_msg)

            res = await self._initializer.api.sync_documents("notion")
            if res.get("status") == "success":
                synced = res.get("synced_count", 0)
                failed = res.get("failed_count", 0)
                msg = f"Notion Sync successful! Synced: {synced}, Failed: {failed}."
                if warning_msg:
                    msg = warning_msg + "\n\n" + msg
                return msg
            elif res.get("status") == "blocked":
                return f"Notion Sync BLOCKED: {res.get('message')}"
            else:
                return f"Notion Sync failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Notion Sync execution failed: {e}"

    async def on_notion_init(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> str:
        """/kr notion init [parent_page_id] [database_title]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            res = await self._initializer.api.initialize_notion_database(
                parent_page_id=parent_page_id,
                database_title=database_title,
            )
            if res.get("status") == "success":
                action = "created" if res.get("created") else "already configured"
                return f"Notion database {action}: {res.get('database_id')}"
            return f"Notion init failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Notion init failed: {e}"

    async def on_sync_notion_pull(self) -> str:
        """/kr sync notion --pull"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            res = await self._initializer.api.pull_notion_metadata()
            if res.get("status") == "success":
                updated = res.get("updated_count", 0)
                skipped = res.get("skipped_count", 0)
                msg = f"Notion Pull successful! Updated: {updated}, Skipped: {skipped}."
                warnings = res.get("warnings") or []
                if warnings:
                    msg += "\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings[:5])
                return msg
            return f"Notion Pull failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Notion Pull execution failed: {e}"

    async def on_sync_status(self) -> str:
        """/kr sync status"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            records = await self._initializer.api.get_sync_status()
            if not records:
                return "No synchronization records found."
            lines = ["--- Synchronization Status ---"]
            for r in records:
                time_str = r["synced_at"][:19] if r["synced_at"] else "Never"
                lines.append(
                    f"DocID: {r['doc_id']} | Target: {r['target']} | "
                    f"Status: {r['status']} | SyncedAt: {time_str}"
                )
                if r["message"] and r["message"] != "同步成功":
                    lines.append(f"  Message: {r['message']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: Failed to fetch sync status: {e}"

    async def on_graph_build(self, collection: str | None = None) -> str:
        """/kr graph build [--collection <col>]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            res = await self._initializer.api.build_graph(collection)
            if res.get("status") == "success":
                return f"Success: {res.get('message')}"
            return f"Error: Graph build failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Graph build failed: {e}"

    async def on_graph_query(self, query: str, top_k: int = 5) -> str:
        """/kr graph query <q> [--top_k <top_k>]"""
        if self._initializer.api is None:
            return "Error: API facade not initialized."

        try:
            res = await self._initializer.api.query_graph(query, top_k=top_k)
            if res.get("status") == "success":
                lines = [f"=== Graph Query Results for '{query}' ==="]
                if res.get("entities"):
                    lines.append("\n[Entities]")
                    for ent in res["entities"][:5]:
                        lines.append(
                            f"- [{ent['entity_type']}] {ent['name']}: "
                            f"{ent['description']} (Degree: {ent['degree']})"
                        )
                if res.get("relations"):
                    lines.append("\n[Relations]")
                    for rel in res["relations"][:5]:
                        lines.append(
                            f"- {rel['src_entity_id']} --({rel['relation']})--> "
                            f"{rel['dst_entity_id']}: {rel['description']}"
                        )
                if res.get("chunks"):
                    lines.append("\n[Text Chunks]")
                    for i, ch in enumerate(res["chunks"]):
                        lines.append(f"Chunk {i+1} (DocID: {ch['doc_id']}): {ch['text'][:150]}...")

                if res.get("context"):
                    lines.append("\n[Academic Context Header Preview]")
                    preview_len = 300
                    lines.append(
                        res["context"][:preview_len] + "\n..."
                        if len(res["context"]) > preview_len
                        else res["context"]
                    )
                return "\n".join(lines)
            return f"Error: Graph query failed: {res.get('message')}"
        except Exception as e:
            return f"Error: Graph query failed: {e}"

    async def on_agent(self, action: str) -> str:
        """/kr agent <on|off>"""
        if action not in ("on", "off"):
            return "Invalid action. Use '/kr agent on' or '/kr agent off'."

        enabled = action == "on"
        self._initializer.agent_enabled = enabled
        return f"Ask Agent has been turned {action.upper()}."

    async def on_message(self, event: Any) -> Any:
        """捕获 AstrBot 普通消息事件的非侵入式旁路 Hook。

        若 /kr agent 为 off，采取旁路 Dry-Run 机制，仅用于验证物理通道 the stable；
        若 /kr agent 为 on，触发高性能召回，并通过多版本兼容注入技术将 Grounded Context
        传回 AstrBot 的 system prompt。
        """
        logger.info("AstrBot message captured by Knowledge Repository Hook.")

        # 1. 安全提取事件中的文本
        message_text = ""
        if hasattr(event, "message_str"):
            message_text = getattr(event, "message_str")
        elif hasattr(event, "message") and hasattr(event.message, "text"):
            message_text = event.message.text
        elif hasattr(event, "text"):
            message_text = getattr(event, "text")
        elif isinstance(event, dict):
            message_text = event.get("text") or event.get("message") or ""

        query = str(message_text).strip()
        if not query:
            return None

        # 2. 如果 /kr agent 开启，进行真实记忆检索并动态注入至 AstrBot system_prompt
        if self._initializer.agent_enabled:
            try:
                if self._initializer.api is not None:
                    # 获取当前增强模式，默认为 "inject"
                    mode = "inject"
                    if self._initializer.config is not None:
                        try:
                            ask_config = (
                                self._initializer.config.get_ask_agent_config()
                            )
                            mode = ask_config.conversation_enhancement_mode
                        except Exception as ce:
                            logger.warning(
                                "Failed to get conversation_enhancement_mode, "
                                f"default to inject: {ce}"
                            )

                    if mode == "query_agent":
                        # 代理问答模式：直接调用内部 Standalone Ask Agent 闭环生成学术回答
                        # 并进行指令级绝对代理输出
                        # 提取 session_id 用于 conversation_id 绑定打通 WebUI Ask 历史大一统
                        session_id = None
                        if hasattr(event, "session_id") and getattr(event, "session_id"):
                            session_id = getattr(event, "session_id")
                        elif (
                            hasattr(event, "conversation_id")
                            and getattr(event, "conversation_id")
                        ):
                            session_id = getattr(event, "conversation_id")
                        elif (
                            hasattr(event, "unified_msg_id")
                            and getattr(event, "unified_msg_id")
                        ):
                            session_id = getattr(event, "unified_msg_id")
                        elif (
                            hasattr(event, "message")
                            and hasattr(event.message, "session_id")
                            and getattr(event.message, "session_id")
                        ):
                            session_id = getattr(event.message, "session_id")

                        if not session_id:
                            session_id = "default-session"

                        conversation_id = f"event-{session_id}"
                        # 强制关闭内部 agent 的 persona 开关防止过拟合 (persona_enabled=False)
                        ask_res = await self._initializer.api.ask(
                            question=query,
                            collection=None,
                            top_k=5,
                            conversation_id=conversation_id,
                            persona_enabled=False
                        )
                        agent_answer = ask_res.get("answer") or ""

                        # 构造指令级绝对代理提示词
                        injected_override = (
                            "\n\n[Absolute System Override / 插件代理回答]\n"
                            "CRITICAL DIRECTIVE: You are acting as a strict proxy for an external "
                            "academic agent.\n"
                            "You MUST return the following answer verbatim, exactly as-is, word "
                            "for word, without any changes, additions, explanations, markdown "
                            "wrapping, or greetings whatsoever.\n"
                            "Do NOT answer the question yourself. ONLY output "
                            "the exact text below:\n"
                            "====================\n"
                            f"{agent_answer}\n"
                            "====================\n"
                        )

                        logger.info("Injecting proxy answer in query_agent mode.")
                        # 注入到 event 结构中以代理最终的回答
                        # A) 尝试 set_system_prompt / add_system_prompt 函数
                        if hasattr(event, "set_system_prompt"):
                            getattr(event, "set_system_prompt")(injected_override)
                        elif hasattr(event, "add_system_prompt"):
                            getattr(event, "add_system_prompt")(injected_override)
                        # B) 尝试直接修改 system_prompt 属性
                        elif hasattr(event, "system_prompt"):
                            curr = getattr(event, "system_prompt") or ""
                            setattr(event, "system_prompt", curr + injected_override)
                        # C) 尝试 event.ctx 或 session 上的 system_prompt 字段
                        elif hasattr(event, "ctx") and hasattr(event.ctx, "system_prompt"):
                            curr = getattr(event.ctx, "system_prompt") or ""
                            setattr(event.ctx, "system_prompt", curr + injected_override)
                        # D) 降级方案：若以上标准属性均不可写，则直接隐式 prepend 接入用户消息本身
                        elif hasattr(event, "message_str"):
                            curr = getattr(event, "message_str") or ""
                            enhanced = (
                                f"[System Constraints]: {injected_override}\n"
                                f"[User Msg]: {curr}"
                            )
                            setattr(event, "message_str", enhanced)

                    else:
                        # 召回注入模式 (inject)
                        cols = await self._initializer.api.list_collections()
                        all_cols = [c.name for c in cols] if cols else ["default"]

                        if self._initializer.retrieval_orchestrator is not None:
                            # 检索各集合下最相关的文本分块并去重，限制在 top 3
                            chunks = []
                            seen_ids = set()
                            for col in all_cols:
                                results = (
                                    await self._initializer.retrieval_orchestrator.retrieve(
                                        collection=col,
                                        query=query,
                                        top_k=3
                                    )
                                )
                                for ch in results:
                                    if ch.chunk_id not in seen_ids:
                                        seen_ids.add(ch.chunk_id)
                                        chunks.append(ch)
                                    if len(chunks) >= 3:
                                        break
                                if len(chunks) >= 3:
                                    break

                            if chunks:
                                context_lines = []
                                for i, chunk in enumerate(chunks):
                                    doc = await self._initializer.api.get_document(chunk.doc_id)
                                    title = doc.title if doc else chunk.doc_id
                                    context_lines.append(
                                        f"[{i+1}] 来源: 《{title}》 | 内容: {chunk.text}"
                                    )
                                
                                grounded_context = "\n".join(context_lines)
                                injected_system_prompt = (
                                    "\n\n[Knowledge Base Context / 插件记忆召回]\n"
                                    "请优先结合以下从知识库召回的相关文献分块"
                                    "回答用户的问题，并以 [n] 格式标注引用来源：\n"
                                    f"{grounded_context}\n"
                                )

                                # 动态注入以引导其最终对话回答
                                logger.info(
                                    "Injecting knowledge context into "
                                    f"system prompt: {len(chunks)} chunks."
                                )
                                
                                # A) 尝试 set_system_prompt / add_system_prompt 函数
                                if hasattr(event, "set_system_prompt"):
                                    getattr(event, "set_system_prompt")(
                                        injected_system_prompt
                                    )
                                elif hasattr(event, "add_system_prompt"):
                                    getattr(event, "add_system_prompt")(
                                        injected_system_prompt
                                    )
                                # B) 尝试直接修改 system_prompt 属性
                                elif hasattr(event, "system_prompt"):
                                    curr = getattr(event, "system_prompt") or ""
                                    setattr(
                                        event,
                                        "system_prompt",
                                        curr + injected_system_prompt
                                    )
                                # C) 尝试 event.ctx 或 session 上的 system_prompt 字段
                                elif (
                                    hasattr(event, "ctx")
                                    and hasattr(event.ctx, "system_prompt")
                                ):
                                    curr = getattr(event.ctx, "system_prompt") or ""
                                    setattr(
                                        event.ctx,
                                        "system_prompt",
                                        curr + injected_system_prompt
                                    )
                                # D) 降级方案：若以上标准属性均不可写，
                                # 则直接隐式 prepend 接入用户消息本身
                                elif hasattr(event, "message_str"):
                                    curr = getattr(event, "message_str") or ""
                                    enhanced = (
                                        f"[System Constraints]: {injected_system_prompt}\n"
                                        f"[User Msg]: {curr}"
                                    )
                                    setattr(event, "message_str", enhanced)
            except Exception as exc:
                logger.error(f"Failed to inject retrieved knowledge into message: {exc}")
        else:
            # 旁路完全不进行任何检索与干预，实现 100% 零开销 pass-through
            logger.debug("Slot Hook bypassed (agent disabled).")

        # 3. 严格逻辑透传（Pass-through）：返回 None，确保原有消息回答链条 100% 完好
        return None


__all__ = ["EventHandler"]
