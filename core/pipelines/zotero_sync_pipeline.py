"""Zotero 单向 Pull 同步编排（pipelines 层）。

把只读 zotero.sqlite 快照镜像进插件，并按 storage_mode × sync_mode 维护文档制品与生命态。
向量/LightRAG 等重副作用经可选注入回调委派给组合根（与 api 解耦，便于单测只验 SQLite/磁盘/生命态）。

sync_mode 语义（用户确认）：
    strict_mirror —— 强制覆盖；Zotero 删除的文档→detached（保留 LRAG，移除 Milvus）；
                     变化触发 Milvus rebuild；本轮 LRAG 构建禁用。
    conservative（默认）—— 覆盖；Zotero 删除的文档→硬删除；collection 只增不减；LRAG 轻量重建。
    archive —— 只增不删；Zotero 删除的文档保留（Milvus 仍会召回）；最不触发 rebuild。

storage_mode：managed_copy（复制原件进制品包）/ linked（原件留 Zotero，仅派生制品入插件）。
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.adapters.zotero import paths as zpaths
from core.adapters.zotero.sqlite_reader import ZoteroSnapshot, ZoteroSqliteReader
from core.config import (
    ZOTERO_STORAGE_LINKED,
    ZOTERO_SYNC_ARCHIVE,
    ZOTERO_SYNC_STRICT,
)
from core.domain.models import (
    Collection,
    DocumentLifecycle,
    DocumentOrigin,
)
from core.managers.ingest_manager import make_document_id

if TYPE_CHECKING:
    from core.config import Config, ZoteroSyncConfig
    from core.managers.ingest_manager import IngestManager
    from core.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("astrbot_plugin_knowledge_repository")

# 同步来源默认归属集合（item 未挂任何 Zotero 集合时的 KB home）。
DEFAULT_ZOTERO_COLLECTION = "Zotero"

# 可选副作用回调类型（组合根注入；单测可不注入）。
IndexCb = Callable[[str, str], Awaitable[None]]
RemoveIndexCb = Callable[[str], Awaitable[None]]
LightRagCb = Callable[[str, str], Awaitable[None]]


@dataclass
class ZoteroSyncResult:
    """一次 Pull 的结构化结果（供 sync_log / 前端展示与上层副作用编排）。"""

    sync_mode: str
    storage_mode: str
    started_at: datetime
    finished_at: datetime | None = None
    items_mirrored: int = 0
    collections_mirrored: int = 0
    new_document_ids: list[str] = field(default_factory=list)
    changed_document_ids: list[str] = field(default_factory=list)
    removed_document_ids: list[str] = field(default_factory=list)
    detached_document_ids: list[str] = field(default_factory=list)
    reattached_document_ids: list[str] = field(default_factory=list)
    skipped_unchanged: int = 0
    needs_milvus_rebuild: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "sync_mode": self.sync_mode,
            "storage_mode": self.storage_mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "items_mirrored": self.items_mirrored,
            "collections_mirrored": self.collections_mirrored,
            "new": list(self.new_document_ids),
            "changed": list(self.changed_document_ids),
            "removed": list(self.removed_document_ids),
            "detached": list(self.detached_document_ids),
            "reattached": list(self.reattached_document_ids),
            "skipped_unchanged": self.skipped_unchanged,
            "needs_milvus_rebuild": self.needs_milvus_rebuild,
            "errors": list(self.errors),
        }


class ZoteroSyncPipeline:
    """编排 Zotero 单向 Pull：镜像表 + 制品包 + 生命态 + 可选向量/LRAG 副作用。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        ingest_manager: IngestManager,
        config: Config,
        reader_factory: Callable[[Path], ZoteroSqliteReader] = ZoteroSqliteReader,
        index_document: IndexCb | None = None,
        remove_index: RemoveIndexCb | None = None,
        lightrag_cleanup: LightRagCb | None = None,
        lightrag_mark_pending: LightRagCb | None = None,
    ) -> None:
        self._store = source_store
        self._ingest = ingest_manager
        self._config = config
        self._reader_factory = reader_factory
        self._index_document = index_document
        self._remove_index = remove_index
        self._lightrag_cleanup = lightrag_cleanup
        self._lightrag_mark_pending = lightrag_mark_pending

    # ── 公开入口 ──────────────────────────────────────────────

    def is_available(self) -> dict[str, object]:
        """探测 Zotero 数据目录是否可用（供前端状态卡 / 同步前置校验）。"""
        cfg = self._config.get_zotero_sync_config()
        data_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        if data_dir is None:
            return {"available": False, "reason": "未找到 zotero.sqlite（请在设置中配置数据目录）"}
        result: dict[str, object] = {"available": True, "data_dir": str(data_dir)}
        if cfg.storage_mode == ZOTERO_STORAGE_LINKED:
            result["linked_probe"] = zpaths.probe_linked_root(cfg.linked_root)
        return result

    async def pull(self, *, incremental: bool = True) -> ZoteroSyncResult:
        """执行一次整库 Pull。incremental=True 时仅处理新增/变更附件。"""
        cfg = self._config.get_zotero_sync_config()
        result = ZoteroSyncResult(
            sync_mode=cfg.sync_mode,
            storage_mode=cfg.storage_mode,
            started_at=datetime.now(timezone.utc),
        )
        data_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        if data_dir is None:
            result.errors.append("zotero.sqlite not found")
            result.finished_at = datetime.now(timezone.utc)
            return result

        snapshot = self._reader_factory(data_dir).read_snapshot()
        await self._mirror_tables(snapshot)
        result.items_mirrored = len(snapshot.items)
        result.collections_mirrored = len(snapshot.collections)

        await self._sync_documents(cfg, snapshot, incremental=incremental, result=result)
        await self._apply_removals(cfg, snapshot, result=result)

        if cfg.sync_mode == ZOTERO_SYNC_STRICT and (
            result.new_document_ids or result.changed_document_ids or result.detached_document_ids
        ):
            result.needs_milvus_rebuild = True

        result.finished_at = datetime.now(timezone.utc)
        logger.info("Zotero pull done: %s", result.to_dict())
        return result

    # ── 镜像表 ────────────────────────────────────────────────

    async def _mirror_tables(self, snapshot: ZoteroSnapshot) -> None:
        await self._store.upsert_zotero_library(snapshot.library)
        for coll in snapshot.collections:
            await self._store.upsert_zotero_collection(coll)
        for item in snapshot.items:
            await self._store.upsert_zotero_item(item)
        for att in snapshot.attachments:
            await self._store.upsert_zotero_attachment(att)
        for rel in snapshot.relations:
            await self._store.upsert_zotero_relation(rel, snapshot.library.library_id)
        # collection_items：按 item 聚合后整体替换其集合归属。
        by_item: dict[str, list[str]] = {}
        for coll_key, item_key in snapshot.collection_items:
            by_item.setdefault(item_key, []).append(coll_key)
        for item_key, coll_keys in by_item.items():
            await self._store.set_item_collections(
                snapshot.library.library_id, item_key, coll_keys
            )
        # item_tags
        for item_key, tags in snapshot.item_tags.items():
            await self._store.replace_item_tags(snapshot.library.library_id, item_key, tags)

    # ── 文档处理 ──────────────────────────────────────────────

    async def _sync_documents(
        self,
        cfg: ZoteroSyncConfig,
        snapshot: ZoteroSnapshot,
        *,
        incremental: bool,
        result: ZoteroSyncResult,
    ) -> None:
        lib = snapshot.library.library_id
        item_by_key = {i.item_key: i for i in snapshot.items}
        # item_key → 主集合名（首个），用于 KB 单值 collection 归属。
        coll_name_by_key = {c.collection_key: c.name for c in snapshot.collections}
        primary_coll: dict[str, str] = {}
        for coll_key, item_key in snapshot.collection_items:
            primary_coll.setdefault(item_key, coll_name_by_key.get(coll_key, ""))

        link_only = cfg.storage_mode == ZOTERO_STORAGE_LINKED
        link_root_override = (
            Path(cfg.linked_root).expanduser() if (link_only and cfg.linked_root) else None
        )

        for att in snapshot.attachments:
            if not _is_pdf(att.content_type, att.filename):
                continue
            src = self._resolve_source_path(att, link_root_override)
            if src is None or not src.exists():
                continue  # linked_url / 文件缺失：仅镜像元数据，不清洗。

            item_key = att.parent_item_key or att.attachment_key
            item = item_by_key.get(item_key)
            version = item.version if item else 0
            document_id = make_document_id(lib, item_key, att.attachment_key)

            existing = await self._store.get_document(document_id)
            was_detached = (
                existing is not None
                and existing.lifecycle_state == DocumentLifecycle.DETACHED
            )
            unchanged = (
                existing is not None
                and not was_detached
                and existing.zotero_version == version
            )
            if incremental and unchanged:
                result.skipped_unchanged += 1
                continue

            collection = primary_coll.get(item_key) or DEFAULT_ZOTERO_COLLECTION
            await self._ensure_kb_collection(collection)
            tags = [t.tag for t in snapshot.item_tags.get(item_key, [])]
            title = (item.title if item and item.title else att.filename) or document_id

            try:
                await self._ingest.process_attachment(
                    document_id=document_id,
                    library_id=lib,
                    item_key=item_key,
                    attachment_key=att.attachment_key,
                    origin=DocumentOrigin.ZOTERO,
                    read_only=True,
                    title=title,
                    content_type=att.content_type or "application/pdf",
                    src_path=src,
                    collection=collection,
                    tags=tags,
                    zotero_version=version,
                    last_synced_at=datetime.now(timezone.utc),
                    link_original=link_only,
                )
            except Exception as exc:  # 单文档失败不阻断整库。
                result.errors.append(f"{document_id}: {exc}")
                continue

            if was_detached:
                result.reattached_document_ids.append(document_id)
            elif existing is None:
                result.new_document_ids.append(document_id)
            else:
                result.changed_document_ids.append(document_id)

            await self._index_and_mark(cfg, document_id, collection)

    def _resolve_source_path(self, att, link_root_override: Path | None) -> Path | None:
        if att.resolved_path:
            return Path(att.resolved_path)
        # linked 覆盖根：用 linked_root + filename 兜底。
        if link_root_override and att.filename:
            cand = link_root_override / att.filename
            return cand
        return None

    async def _index_and_mark(
        self, cfg: ZoteroSyncConfig, document_id: str, collection: str
    ) -> None:
        if self._index_document is not None:
            try:
                await self._index_document(document_id, collection)
            except Exception as exc:
                logger.warning("index_document failed for %s: %s", document_id, exc)
        # strict 模式禁用 LRAG；conservative/archive 标记 LRAG 待建。
        if cfg.sync_mode != ZOTERO_SYNC_STRICT and self._lightrag_mark_pending is not None:
            try:
                await self._lightrag_mark_pending(document_id, collection)
            except Exception as exc:
                logger.warning("lightrag_mark_pending failed for %s: %s", document_id, exc)

    # ── 删除 / 脱管 ───────────────────────────────────────────

    async def _apply_removals(
        self, cfg: ZoteroSyncConfig, snapshot: ZoteroSnapshot, *, result: ZoteroSyncResult
    ) -> None:
        if cfg.sync_mode == ZOTERO_SYNC_ARCHIVE:
            return  # 归档堆栈：只增不删。

        lib = snapshot.library.library_id
        current_ids = self._current_document_ids(lib, snapshot)
        existing_docs = await self._store.list_documents()
        for doc in existing_docs:
            if doc.origin != DocumentOrigin.ZOTERO or doc.library_id != lib:
                continue
            if doc.doc_id in current_ids:
                continue
            if cfg.sync_mode == ZOTERO_SYNC_STRICT:
                # 脱管：保留 LRAG workspace + 制品包，移除 Milvus，标 detached。
                if doc.lifecycle_state != DocumentLifecycle.DETACHED:
                    doc.lifecycle_state = DocumentLifecycle.DETACHED
                    await self._store.update_document(doc)
                    if self._remove_index is not None:
                        await _safe(self._remove_index(doc.doc_id))
                    result.detached_document_ids.append(doc.doc_id)
            else:  # conservative：硬删除（含 Milvus + LRAG 清理）。
                if self._remove_index is not None:
                    await _safe(self._remove_index(doc.doc_id))
                if self._lightrag_cleanup is not None:
                    await _safe(self._lightrag_cleanup(doc.doc_id, doc.collection))
                await self._store.delete_document(doc.doc_id)
                result.removed_document_ids.append(doc.doc_id)

    def _current_document_ids(self, lib: str, snapshot: ZoteroSnapshot) -> set[str]:
        ids: set[str] = set()
        for att in snapshot.attachments:
            if not _is_pdf(att.content_type, att.filename):
                continue
            item_key = att.parent_item_key or att.attachment_key
            ids.add(make_document_id(lib, item_key, att.attachment_key))
        return ids

    # ── 助手 ──────────────────────────────────────────────────

    async def _ensure_kb_collection(self, name: str) -> None:
        existing = {c.name for c in await self._store.list_collections()}
        if name not in existing:
            await self._store.upsert_collection(
                Collection(name=name, origin=DocumentOrigin.ZOTERO, read_only=True)
            )


def _is_pdf(content_type: str, filename: str) -> bool:
    return (content_type or "").lower() == "application/pdf" or filename.lower().endswith(".pdf")


async def _safe(awaitable: Awaitable[None]) -> None:
    try:
        await awaitable
    except Exception as exc:  # 副作用失败不阻断同步主流程。
        logger.warning("zotero sync side-effect failed: %s", exc)


__all__ = ["ZoteroSyncPipeline", "ZoteroSyncResult", "DEFAULT_ZOTERO_COLLECTION"]
