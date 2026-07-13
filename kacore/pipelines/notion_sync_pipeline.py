"""Notion 单向推送编排（pipelines 层）。

职责：把本地文章（含 tag / 文件树编码）与 QA 记录**增量推送**到 Notion 两表。
增量真相源是 notion_entity_map（指纹比对，非事件/标脏）；账本读写、集合树展开、
outbox 补推、孤儿对账都在本层，NotionSyncTarget 只做无状态的单实体幂等 upsert。

为什么不用标脏钩子：本地实体量级（文档 10²–10³、集合 10¹、QA 10²）在 push 时刻
全量算指纹是毫秒级，避免侵入 CategoryManager / 集合树编辑 / notes CRUD 10+ 处写入口。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from kacore.domain.models import (
    NOTION_ENTITY_DOCUMENT,
    NOTION_OUTBOX_PUSHED,
    NOTION_PUSH_DEGRADED,
    NOTION_PUSH_FAILED,
    NOTION_PUSH_PENDING,
    NOTION_PUSH_SYNCED,
    NotionEntityRecord,
    SyncRecord,
    SyncStatus,
    SyncTargetKind,
)
from kacore.repository.sync_targets import notion_schema as schema
from kacore.repository.sync_targets.notion import ACTION_CREATED

if TYPE_CHECKING:
    from kacore.config import NotionSyncConfig
    from kacore.domain.models import Collection, NotionOutboxItem, SourceDocument
    from kacore.repository.source_store.base import SourceDocumentStore
    from kacore.repository.sync_targets.notion import NotionSyncTarget

logger = logging.getLogger("NotionSyncPipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NotionSyncPipeline:
    """Notion 两表增量推送编排。单实例，push_all 期间以 Lock 防并发重入。"""

    def __init__(
        self,
        source_store: SourceDocumentStore,
        notion_target: NotionSyncTarget,
    ) -> None:
        self._store = source_store
        self._target = notion_target
        self._lock = asyncio.Lock()

    @property
    def _config(self) -> NotionSyncConfig:
        # target.config 在 initialize_databases 后含回填的 database id，读它保证最新。
        return self._target.config

    # ── 建库 ────────────────────────────────────────────────────

    async def initialize_databases(
        self, parent_page_id: str | None = None, database_title: str | None = None
    ) -> dict[str, Any]:
        return await self._target.initialize_databases(parent_page_id, database_title)

    # ── 全量增量推送 ────────────────────────────────────────────

    async def push_all(self, force: bool = False) -> dict[str, Any]:
        """把全部文章 + 待推 QA 增量推送到 Notion。

        流程：文档 diff/upsert（含冗余写 sync_records）→ outbox(pending/failed) 补推 →
        孤儿账本行对账清理。单实体失败记 FAILED 不中断；并发重入直接返回 already_running。
        """
        if not self._config.enabled:
            return {"status": "disabled", "message": "Notion 同步未启用。"}
        if not self._config.database_id:
            return {"status": "error", "message": "Notion 数据库未初始化，请先执行初始化建库。"}
        if self._lock.locked():
            return {"status": "already_running", "message": "已有 Notion 推送任务在执行。"}

        async with self._lock:
            collections = await self._store.list_collections()
            paths = schema.build_collection_paths(collections)
            docs = await self._store.list_documents()

            doc_stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
            warnings: list[str] = []
            for doc in docs:
                try:
                    action = await self._push_document(
                        doc, collections, paths, force=force
                    )
                    doc_stats[action] += 1
                except Exception as e:  # noqa: BLE001 — 单文档失败不阻断整轮
                    doc_stats["failed"] += 1
                    warnings.append(f"文档 {doc.doc_id} 推送失败：{e}")
                    logger.warning("Notion 文档推送失败（%s）：%s", doc.doc_id, e)
                    await self._record_failure(NOTION_ENTITY_DOCUMENT, doc.doc_id, str(e))

            qa_stats = await self._push_pending_outbox(collections, paths, warnings)
            await self._cleanup_orphans({d.doc_id for d in docs})

            status = "success"
            if doc_stats["failed"] or qa_stats["failed"]:
                status = "partial_failure" if (
                    doc_stats["created"] + doc_stats["updated"] + qa_stats["pushed"]
                ) else "error"
            return {
                "status": status,
                "documents": doc_stats,
                "qa": qa_stats,
                "warnings": warnings,
            }

    async def _push_document(
        self,
        doc: SourceDocument,
        collections: list[Collection],
        paths: dict[str, str],
        *,
        force: bool,
    ) -> str:
        """幂等推送一篇文章，回写账本 + 冗余 sync_records。返回 created/updated/skipped。"""
        collection_names = _doc_collection_names(doc, collections)
        path = schema.primary_collection_path(doc, collections, paths)
        metadata_hash = schema.document_metadata_hash(
            doc, path=path, collection_names=collection_names
        )
        prior = await self._store.get_notion_entity(NOTION_ENTITY_DOCUMENT, doc.doc_id)
        if (
            not force
            and prior is not None
            and prior.status == NOTION_PUSH_SYNCED
            and prior.metadata_hash == metadata_hash
        ):
            return "skipped"

        result = await self._target.upsert_document(
            doc,
            path=path,
            collection_names=collection_names,
            prior=prior,
            force_body=force,
        )
        # 正文没写成时不推进 content_hash（保留旧值/置空），使下一轮 rewrite 判定
        # 为「待重写」而非跳过——否则缺正文页会被误标 synced 并永久固化。
        if result.content_synced:
            recorded_content_hash = doc.content_hash
            status = NOTION_PUSH_DEGRADED if result.degraded else NOTION_PUSH_SYNCED
        else:
            recorded_content_hash = prior.content_hash if prior is not None else ""
            status = NOTION_PUSH_DEGRADED
        await self._store.upsert_notion_entity(
            NotionEntityRecord(
                entity_type=NOTION_ENTITY_DOCUMENT,
                entity_key=doc.doc_id,
                page_id=result.page_id,
                metadata_hash=metadata_hash,
                content_hash=recorded_content_hash,
                status=status,
                synced_at=_now(),
                message=result.message,
            )
        )
        # 冗余写 sync_records，保 /api/sync/status 与既有测试兼容。
        sync_status = SyncStatus.SYNCED
        if result.skipped_binary:
            sync_status = SyncStatus.SKIPPED
        elif not result.content_synced:
            sync_status = SyncStatus.FAILED
        await self._store.upsert_sync_record(
            SyncRecord(
                doc_id=doc.doc_id,
                target=SyncTargetKind.NOTION,
                remote_ref=result.page_id,
                content_hash=recorded_content_hash,
                status=sync_status,
                synced_at=_now(),
                message=result.message,
            )
        )
        return "created" if result.action == ACTION_CREATED else "updated"

    # ── QA 推送 ─────────────────────────────────────────────────

    async def push_qa_record(
        self,
        *,
        note_id: str,
        title: str,
        content: str,
        tags: list[str],
        citations: list[str],
        source: str,
    ) -> dict[str, Any]:
        """把一条问答记录推到 QA 库；citations 为引用文章 doc_id 列表。

        无法解析为 Notion 页面的引用降级为正文尾部文本列表（relation 只链已同步文章）。
        """
        if not self._config.enabled:
            return {"status": "disabled", "message": "Notion 同步未启用。"}
        if not self._config.qa_database_id:
            return {"status": "error", "message": "Notion QA 库未初始化，请先执行初始化建库。"}

        collections = await self._store.list_collections()
        paths = schema.build_collection_paths(collections)
        page_ids, resolved_labels, unresolved = await self._resolve_citations(
            citations, collections, paths
        )
        body = content
        if unresolved:
            listed = "、".join(unresolved)
            body = f"{content}\n\n未同步引用（本地 DocID）：{listed}"

        result = await self._target.create_qa_entry(
            title=_qa_title(title, content),
            content=body,
            tags=tags,
            citation_page_ids=page_ids,
            citation_labels=resolved_labels,
            source=source,
            note_id=note_id,
        )
        return {
            "status": "success" if result.content_synced else "partial",
            "page_id": result.page_id,
            "action": result.action,
            "degraded": result.degraded,
            "content_synced": result.content_synced,
            "unresolved_citations": unresolved,
            "message": result.message,
        }

    async def push_outbox_item(self, item_id: str) -> dict[str, Any]:
        """推送单条 outbox QA：成功清正文留存根，失败保留全文记 failed。"""
        item = await self._store.get_notion_outbox(item_id)
        if item is None:
            return {"status": "error", "message": f"暂存条目不存在：{item_id}"}
        try:
            result = await self.push_qa_record(
                note_id=f"outbox:{item.id}",
                title=item.title,
                content=item.content,
                tags=item.tags,
                citations=item.citations,
                source=item.source,
            )
        except Exception as e:  # noqa: BLE001 — 推送失败保留全文等补推
            await self._mark_outbox_failed(item, str(e))
            return {"status": "error", "message": str(e)}

        if result.get("status") != "success":
            await self._mark_outbox_failed(item, str(result.get("message", "")))
            return result

        item.status = NOTION_OUTBOX_PUSHED
        item.page_id = str(result.get("page_id", ""))
        item.content = ""  # 中转即焚：推成后仅留存根
        item.message = str(result.get("message", ""))
        item.pushed_at = _now()
        await self._store.update_notion_outbox(item)
        return result

    async def _push_pending_outbox(
        self,
        collections: list[Collection],
        paths: dict[str, str],
        warnings: list[str],
    ) -> dict[str, Any]:
        stats = {"pushed": 0, "skipped": 0, "failed": 0}
        pending = await self._store.list_notion_outbox(NOTION_PUSH_PENDING)
        failed = await self._store.list_notion_outbox(NOTION_PUSH_FAILED)
        for item in [*pending, *failed]:
            result = await self.push_outbox_item(item.id)
            if result.get("status") == "success":
                stats["pushed"] += 1
            else:
                stats["failed"] += 1
                warnings.append(f"QA {item.id} 补推失败：{result.get('message')}")
        return stats

    async def _mark_outbox_failed(self, item: NotionOutboxItem, message: str) -> None:
        item.status = NOTION_PUSH_FAILED
        item.message = message
        await self._store.update_notion_outbox(item)

    # ── 引用解析 / 孤儿清理 ─────────────────────────────────────

    async def _resolve_citations(
        self,
        doc_ids: list[str],
        collections: list[Collection],
        paths: dict[str, str],
    ) -> tuple[list[str], list[str], list[str]]:
        """引用 doc_id → Notion page_id：账本命中直接用，未同步文章按需先 upsert。

        返回 (page_ids, resolved_labels, unresolved)：page_ids[i] 与
        resolved_labels[i]（对应 doc_id）一一对应，供降级时把引用补进正文。
        """
        page_ids: list[str] = []
        resolved_labels: list[str] = []
        unresolved: list[str] = []
        for raw in doc_ids:
            doc_id = raw.strip()
            if not doc_id:
                continue
            rec = await self._store.get_notion_entity(NOTION_ENTITY_DOCUMENT, doc_id)
            if rec is not None and rec.page_id:
                page_ids.append(rec.page_id)
                resolved_labels.append(doc_id)
                continue
            doc = await self._store.get_document(doc_id)
            if doc is None:
                unresolved.append(doc_id)
                continue
            try:
                await self._push_document(doc, collections, paths, force=False)
                rec = await self._store.get_notion_entity(NOTION_ENTITY_DOCUMENT, doc_id)
                if rec is not None and rec.page_id:
                    page_ids.append(rec.page_id)
                    resolved_labels.append(doc_id)
                else:
                    unresolved.append(doc_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("按需推送引用文章失败（%s）：%s", doc_id, e)
                unresolved.append(doc_id)
        return page_ids, resolved_labels, unresolved

    async def _cleanup_orphans(self, live_doc_ids: set[str]) -> None:
        """本地已删文档的账本行清理（只清本地映射，不触碰远端页面）。"""
        for rec in await self._store.list_notion_entities(NOTION_ENTITY_DOCUMENT):
            if rec.entity_key not in live_doc_ids:
                await self._store.delete_notion_entity(
                    NOTION_ENTITY_DOCUMENT, rec.entity_key
                )

    async def _record_failure(
        self, entity_type: str, entity_key: str, message: str
    ) -> None:
        prior = await self._store.get_notion_entity(entity_type, entity_key)
        await self._store.upsert_notion_entity(
            NotionEntityRecord(
                entity_type=entity_type,
                entity_key=entity_key,
                page_id=prior.page_id if prior else "",
                metadata_hash=prior.metadata_hash if prior else "",
                content_hash=prior.content_hash if prior else "",
                status=NOTION_PUSH_FAILED,
                synced_at=_now(),
                message=message,
            )
        )


def _doc_collection_names(doc: SourceDocument, collections: list[Collection]) -> list[str]:
    """文章归属集合名 + 各自祖先名；无归属键时回退冗余 primary 集合名。"""
    names = schema.expand_ancestor_names(doc.collection_keys, collections)
    if not names and doc.collection:
        return [doc.collection]
    return names


def _qa_title(title: str, content: str) -> str:
    """QA 标题：显式 title 优先，否则取正文首行前 60 字符。"""
    candidate = (title or "").strip()
    if not candidate:
        candidate = (content or "").strip().splitlines()[0] if content.strip() else ""
    return candidate[:60] or "Untitled Note"


__all__ = ["NotionSyncPipeline"]
