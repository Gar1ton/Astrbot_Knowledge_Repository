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

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.adapters.zotero import paths as zpaths
from core.adapters.zotero.sqlite_reader import ZoteroSnapshot, ZoteroSqliteReader
from core.adapters.zotero.web_api import (
    ZoteroWebApiClient,
    ZoteroWebApiError,
    ZoteroWebApiReader,
    current_key_identity,
)
from core.config import (
    ZOTERO_ACCESS_SERVER,
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
from core.zotero_sync_job import (
    ZOTERO_STAGE_APPLYING_REMOVALS,
    ZOTERO_STAGE_FINALIZING,
    ZOTERO_STAGE_MIRRORING,
    ZOTERO_STAGE_READING,
    ZOTERO_STAGE_SYNCING_DOCS,
)

if TYPE_CHECKING:
    from core.config import Config, ZoteroSyncConfig
    from core.managers.ingest_manager import IngestManager
    from core.repository.source_store.base import SourceDocumentStore
    from core.zotero_sync_job import ZoteroSyncJob

logger = logging.getLogger("astrbot_plugin_knowledge_repository")

# 同步来源默认归属集合（item 未挂任何 Zotero 集合时的 KB home）。
DEFAULT_ZOTERO_COLLECTION = "Zotero"


def _zotero_coll_key(library_id: str, collection_key: str) -> str:
    """统一 collections 树中 Zotero 集合的稳定 coll_key（跨 library 唯一）。"""
    return f"{library_id}:{collection_key}"


def _unfiled_coll_key(library_id: str) -> str:
    """某 library 下「未归入任何 Zotero 集合」条目的合成 home 集合 coll_key。"""
    return f"{library_id}:__unfiled__"

# 可选副作用回调类型（组合根注入；单测可不注入）。
IndexCb = Callable[[str, str], Awaitable[None]]
RemoveIndexCb = Callable[[str], Awaitable[None]]
LightRagCb = Callable[[str, str], Awaitable[None]]
# web 模式惰性单篇下载器：(attachment_key, filename) -> 本地路径 | None（失败/无缓存目录）。
WebFileFetcher = Callable[[str, str], "Path | None"]


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
        web_client_factory: Callable[[str], ZoteroWebApiClient] = ZoteroWebApiClient,
        web_reader_factory: Callable[..., ZoteroWebApiReader] = ZoteroWebApiReader,
        zotero_api_key_provider: Callable[[], str] | None = None,
        web_cache_dir: Path | None = None,
        index_document: IndexCb | None = None,
        remove_index: RemoveIndexCb | None = None,
        lightrag_cleanup: LightRagCb | None = None,
        lightrag_mark_pending: LightRagCb | None = None,
    ) -> None:
        self._store = source_store
        self._ingest = ingest_manager
        self._config = config
        self._reader_factory = reader_factory
        self._web_client_factory = web_client_factory
        self._web_reader_factory = web_reader_factory
        self._zotero_api_key_provider = zotero_api_key_provider
        self._web_cache_dir = web_cache_dir
        self._index_document = index_document
        self._remove_index = remove_index
        self._lightrag_cleanup = lightrag_cleanup
        self._lightrag_mark_pending = lightrag_mark_pending

    # ── 公开入口 ──────────────────────────────────────────────

    def is_available(self) -> dict[str, object]:
        """探测 Zotero 数据目录是否可用（供前端状态卡 / 同步前置校验）。"""
        cfg = self._config.get_zotero_sync_config()
        if cfg.access_mode == ZOTERO_ACCESS_SERVER:
            key = self._zotero_api_key(cfg)
            if not key:
                return {
                    "available": False,
                    "access_mode": cfg.access_mode,
                    "reason": "Zotero Web API key is not configured",
                }
            try:
                identity = current_key_identity(self._web_client_factory(key).get_current_key())
                return {
                    "available": True,
                    "access_mode": cfg.access_mode,
                    "server_user_id": identity["user_id"],
                    "server_username": identity["username"],
                    "server_access": identity["access"],
                }
            except ZoteroWebApiError as exc:
                return {
                    "available": False,
                    "access_mode": cfg.access_mode,
                    "reason": str(exc),
                }

        data_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        if data_dir is None:
            return {
                "available": False,
                "access_mode": cfg.access_mode,
                "reason": "未找到 zotero.sqlite（请在设置中配置数据目录）",
            }
        result: dict[str, object] = {
            "available": True,
            "access_mode": cfg.access_mode,
            "data_dir": str(data_dir),
        }
        if cfg.storage_mode == ZOTERO_STORAGE_LINKED:
            result["linked_probe"] = zpaths.probe_linked_root(cfg.linked_root)
        return result

    def probe_local_read(self) -> dict[str, object]:
        """本地干跑探针：只读快照、不 mirror/不写库，返回可读条目与附件计数（供前端调试）。

        仅本地模式有效；server 模式直接返回 reason（探针不联网，避免误触发下载）。
        """
        cfg = self._config.get_zotero_sync_config()
        if cfg.access_mode == ZOTERO_ACCESS_SERVER:
            return {"available": False, "reason": "探针仅用于本地模式"}
        data_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        if data_dir is None:
            return {"available": False, "reason": "未找到 zotero.sqlite（请在设置中配置数据目录）"}
        try:
            snapshot = self._reader_factory(data_dir).read_snapshot()
        except Exception as exc:  # noqa: BLE001 — 干读失败原因透传给前端
            return {"available": False, "data_dir": str(data_dir), "reason": str(exc)}
        pdf_count = sum(
            1
            for att in snapshot.attachments
            if att.content_type == "application/pdf" or att.filename.lower().endswith(".pdf")
        )
        return {
            "available": True,
            "data_dir": str(data_dir),
            "item_count": len(snapshot.items),
            "collection_count": len(snapshot.collections),
            "attachment_count": len(snapshot.attachments),
            "pdf_attachment_count": pdf_count,
        }

    async def pull(
        self, *, incremental: bool = True, progress: ZoteroSyncJob | None = None
    ) -> ZoteroSyncResult:
        """执行一次整库 Pull。incremental=True 时仅处理新增/变更附件。

        `progress` 为可选的进度任务对象（`ZoteroSyncJob`）：传入时在各阶段/逐文档循环里更新，
        供前端轮询进度条；不传则纯执行（保持现有单测不受影响）。
        """
        cfg = self._config.get_zotero_sync_config()
        result = ZoteroSyncResult(
            sync_mode=cfg.sync_mode,
            storage_mode=cfg.storage_mode,
            started_at=datetime.now(timezone.utc),
        )
        if progress is not None:
            progress.incremental = incremental
            progress.sync_mode = cfg.sync_mode
            progress.storage_mode = cfg.storage_mode
            progress.access_mode = cfg.access_mode
            progress.set_stage(ZOTERO_STAGE_READING)
        logger.info(
            "Zotero pull start: access=%s sync_mode=%s storage=%s incremental=%s",
            cfg.access_mode,
            cfg.sync_mode,
            cfg.storage_mode,
            incremental,
        )

        snapshot, web_fetch = await asyncio.to_thread(self._read_snapshot, cfg, result)
        if snapshot is None:
            if progress is not None:
                for err in result.errors:
                    progress.note_error(err)
            result.finished_at = datetime.now(timezone.utc)
            logger.error("Zotero pull aborted (snapshot unavailable): %s", result.errors)
            return result

        if progress is not None:
            progress.items_total = len(snapshot.items)
            progress.set_stage(ZOTERO_STAGE_MIRRORING)
        await self._mirror_tables(snapshot)
        result.items_mirrored = len(snapshot.items)
        result.collections_mirrored = len(snapshot.collections)

        if progress is not None:
            progress.docs_total = sum(
                1 for att in snapshot.attachments if _is_pdf(att.content_type, att.filename)
            )
            progress.set_stage(ZOTERO_STAGE_SYNCING_DOCS)
        await self._sync_documents(
            cfg,
            snapshot,
            incremental=incremental,
            result=result,
            progress=progress,
            web_fetch=web_fetch,
        )

        if progress is not None:
            progress.set_stage(ZOTERO_STAGE_APPLYING_REMOVALS)
        await self._apply_removals(cfg, snapshot, result=result)

        if progress is not None:
            progress.set_stage(ZOTERO_STAGE_FINALIZING)
            progress.new_count = len(result.new_document_ids)
            progress.changed_count = len(result.changed_document_ids)
            progress.removed_count = len(result.removed_document_ids)
            progress.detached_count = len(result.detached_document_ids)

        if cfg.sync_mode == ZOTERO_SYNC_STRICT and (
            result.new_document_ids or result.changed_document_ids or result.detached_document_ids
        ):
            result.needs_milvus_rebuild = True

        result.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Zotero pull done: new=%d changed=%d skipped=%d removed=%d detached=%d errors=%d",
            len(result.new_document_ids),
            len(result.changed_document_ids),
            result.skipped_unchanged,
            len(result.removed_document_ids),
            len(result.detached_document_ids),
            len(result.errors),
        )
        return result

    def _read_snapshot(
        self, cfg: ZoteroSyncConfig, result: ZoteroSyncResult
    ) -> tuple[ZoteroSnapshot | None, WebFileFetcher | None]:
        """读取快照（纯元数据，不下载文件）。server 模式额外返回惰性下载器供逐文档阶段按需取件。"""
        if cfg.access_mode == ZOTERO_ACCESS_SERVER:
            key = self._zotero_api_key(cfg)
            if not key:
                result.errors.append("Zotero Web API key is not configured")
                return None, None
            try:
                client = self._web_client_factory(key)
                identity = current_key_identity(client.get_current_key())
                reader = self._web_reader_factory(
                    client,
                    user_id=identity["user_id"],
                    username=identity["username"],
                    download_dir=self._web_cache_dir,
                )
                return reader.read_snapshot(), reader.fetch_attachment_file
            except ZoteroWebApiError as exc:
                result.errors.append(f"Zotero Web API: {exc}")
                return None, None

        data_dir = zpaths.resolve_data_dir(cfg.zotero_data_dir)
        if data_dir is None:
            result.errors.append("zotero.sqlite not found")
            return None, None
        # 本地模式：resolved_path 已由 sqlite reader 指向本地文件，无需惰性下载器。
        return self._reader_factory(data_dir).read_snapshot(), None

    def _zotero_api_key(self, cfg: ZoteroSyncConfig) -> str:
        if self._zotero_api_key_provider is not None:
            key = self._zotero_api_key_provider().strip()
            if key:
                return key
        return cfg.cloud_api_key.strip()

    # ── 镜像表 ────────────────────────────────────────────────

    async def _mirror_tables(self, snapshot: ZoteroSnapshot) -> None:
        await self._store.upsert_zotero_library(snapshot.library)
        for coll in snapshot.collections:
            await self._store.upsert_zotero_collection(coll)
        # 把 Zotero 集合树派生进统一 collections（树形 + 只读），供 UI/ask/lightrag 共用。
        await self._sync_zotero_tree_into_collections(snapshot)
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
        progress: ZoteroSyncJob | None = None,
        web_fetch: WebFileFetcher | None = None,
    ) -> None:
        lib = snapshot.library.library_id
        item_by_key = {i.item_key: i for i in snapshot.items}
        coll_name_by_key = {c.collection_key: c.name for c in snapshot.collections}
        # item_key → 首个集合名（KB 单值 primary，用于 R2 key/Notion/milvus tag 兜底）。
        primary_coll: dict[str, str] = {}
        # item_key → 全部所属集合的统一 coll_key 列表（多归属真相源）。
        item_coll_keys: dict[str, list[str]] = {}
        for coll_key, item_key in snapshot.collection_items:
            primary_coll.setdefault(item_key, coll_name_by_key.get(coll_key, ""))
            item_coll_keys.setdefault(item_key, []).append(_zotero_coll_key(lib, coll_key))

        link_only = cfg.storage_mode == ZOTERO_STORAGE_LINKED
        link_root_override = (
            Path(cfg.linked_root).expanduser() if (link_only and cfg.linked_root) else None
        )

        for att in snapshot.attachments:
            if not _is_pdf(att.content_type, att.filename):
                continue

            item_key = att.parent_item_key or att.attachment_key
            item = item_by_key.get(item_key)
            version = item.version if item else 0
            document_id = make_document_id(lib, item_key, att.attachment_key)

            # 多归属真相源：item 的全部所属集合 coll_key；未挂集合则归入合成 unfiled home。
            coll_keys = list(dict.fromkeys(item_coll_keys.get(item_key, [])))
            if not coll_keys:
                coll_keys = [_unfiled_coll_key(lib)]

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
                # 增量未变更：直接跳过，且**绝不下载**（web 模式不再每次重下整库的关键）。
                # 即便跳过清洗，也刷新多归属（覆盖迁移期临时归属，保证树形归属正确）。
                await self._store.set_document_collections(document_id, coll_keys)
                result.skipped_unchanged += 1
                if progress is not None:
                    progress.skipped_unchanged += 1
                continue

            # 确认需要摄入后才解析/下载原件：web 模式在此惰性单篇下载（串行，逐篇推进进度条）。
            src = await self._resolve_source_path(att, link_root_override, web_fetch)
            if src is None or not src.exists():
                continue  # linked_url / 文件缺失 / 下载失败：仅镜像元数据，不清洗。

            collection = primary_coll.get(item_key) or DEFAULT_ZOTERO_COLLECTION
            await self._ensure_unfiled_home(lib, collection, coll_keys)
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
                if progress is not None:
                    progress.docs_failed += 1
                    progress.note_error(f"{document_id}: {exc}")
                logger.error("Zotero ingest failed for %s: %s", document_id, exc, exc_info=True)
                continue

            # 覆盖为 Zotero 真实多归属（process_attachment 仅按 primary 写了单归属）。
            await self._store.set_document_collections(document_id, coll_keys)

            if was_detached:
                result.reattached_document_ids.append(document_id)
            elif existing is None:
                result.new_document_ids.append(document_id)
            else:
                result.changed_document_ids.append(document_id)
            if progress is not None:
                progress.docs_processed += 1

            await self._index_and_mark(
                cfg, document_id, collection, result=result, progress=progress
            )

    async def _resolve_source_path(
        self,
        att,
        link_root_override: Path | None,
        web_fetch: WebFileFetcher | None = None,
    ) -> Path | None:
        if att.resolved_path:
            return Path(att.resolved_path)
        # web 模式：惰性下载该附件原件（阻塞 I/O 丢进线程，避免堵塞事件循环）。
        if web_fetch is not None and _is_pdf(att.content_type, att.filename):
            return await asyncio.to_thread(web_fetch, att.attachment_key, att.filename)
        # linked 覆盖根：用 linked_root + filename 兜底。
        if link_root_override and att.filename:
            cand = link_root_override / att.filename
            return cand
        return None

    async def _index_and_mark(
        self,
        cfg: ZoteroSyncConfig,
        document_id: str,
        collection: str,
        *,
        result: ZoteroSyncResult | None = None,
        progress: ZoteroSyncJob | None = None,
    ) -> None:
        if self._index_document is not None:
            try:
                await self._index_document(document_id, collection)
            except Exception as exc:
                # 索引副作用失败必须上报（如 VectorStore 未配置）：文档已镜像/摄入但未入向量库，
                # 不可静默吞掉，否则用户侧表现为「同步了却检索不到 = 失灵」。
                msg = f"index_document failed for {document_id}: {exc}"
                logger.error(msg, exc_info=True)
                if result is not None:
                    result.errors.append(msg)
                if progress is not None:
                    progress.note_error(msg)
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

    async def _sync_zotero_tree_into_collections(self, snapshot: ZoteroSnapshot) -> None:
        """把 Zotero 集合树派生进统一 collections 表（树形 + 只读）。

        统一表是 zotero_collections 镜像表的「投影」：coll_key=lib:zkey、parent_key=lib:父zkey，
        origin=ZOTERO/read_only=1。同步后清理本 library 中不在快照内的 zotero 集合
        （含 Zotero 侧删除的集合，以及 018 迁移产生的无命名空间临时行），保持树形与上游一致。
        """
        lib = snapshot.library.library_id
        snapshot_keys: set[str] = set()
        for coll in snapshot.collections:
            ck = _zotero_coll_key(lib, coll.collection_key)
            parent = (
                _zotero_coll_key(lib, coll.parent_collection_key)
                if coll.parent_collection_key
                else ""
            )
            await self._store.upsert_collection(
                Collection(
                    name=coll.name,
                    coll_key=ck,
                    parent_key=parent,
                    origin=DocumentOrigin.ZOTERO,
                    read_only=True,
                    zotero_collection_key=coll.collection_key,
                    library_id=lib,
                )
            )
            snapshot_keys.add(ck)
        # 清理陈旧 zotero 集合：本库内不在快照的 + 无命名空间的迁移临时行（coll_key 无冒号）。
        for c in await self._store.list_collections():
            if c.origin != DocumentOrigin.ZOTERO or c.coll_key in snapshot_keys:
                continue
            if c.library_id == lib or ":" not in c.coll_key:
                await self._store.delete_collection_by_key(c.coll_key)

    async def _ensure_unfiled_home(
        self, library_id: str, name: str, coll_keys: list[str]
    ) -> None:
        """确保 item 归属的集合在统一表中存在；未挂任何 Zotero 集合时建合成 unfiled home。"""
        if coll_keys == [_unfiled_coll_key(library_id)]:
            await self._store.upsert_collection(
                Collection(
                    name=name or DEFAULT_ZOTERO_COLLECTION,
                    coll_key=_unfiled_coll_key(library_id),
                    origin=DocumentOrigin.ZOTERO,
                    read_only=True,
                    library_id=library_id,
                )
            )


def _is_pdf(content_type: str, filename: str) -> bool:
    return (content_type or "").lower() == "application/pdf" or filename.lower().endswith(".pdf")


async def _safe(awaitable: Awaitable[None]) -> None:
    try:
        await awaitable
    except Exception as exc:  # 副作用失败不阻断同步主流程。
        logger.warning("zotero sync side-effect failed: %s", exc)


__all__ = ["ZoteroSyncPipeline", "ZoteroSyncResult", "DEFAULT_ZOTERO_COLLECTION"]
