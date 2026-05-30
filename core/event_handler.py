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
from typing import TYPE_CHECKING

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


__all__ = ["EventHandler"]
