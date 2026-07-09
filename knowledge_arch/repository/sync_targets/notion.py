"""Notion 镜像同步目标实现（repository 层）。

经 NotionMCPAdapter（真实 notion_ 前缀工具）把文章元数据与 QA 记录**单向推送**到
Notion 两表（Articles 单库 + QA 库）。核心语义：

- 幂等 upsert：账本 page_id 命中 → update；miss → 按幂等键（DocID/NoteID）反查
  远端回填 → update，仍无才 create + 追加正文块。杜绝历史「每次 push 都新建页面」。
- 渐进降级：属性写入失败时剔除到 Name+DocID 最小集重试一次（DocID 必留，
  保后续幂等），返回 degraded 供上层记账。
- 正文块只在 create 或 content_hash 变化时写（重写 = 列块 → 逐删 → 追加）。
- 频控由 adapter 统一执行，本层不 sleep。

属性构造/指纹等纯函数在 notion_schema.py；增量 diff 与账本读写在
pipelines/notion_sync_pipeline.py（本层不读账本，prior 由上层传入）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from knowledge_arch.adapters.notion_mcp import NotionMCPAdapter, NotionMCPError
from knowledge_arch.domain.models import QuotaUsage, SyncTargetKind
from knowledge_arch.repository.sync_targets import notion_schema as schema
from knowledge_arch.repository.sync_targets.base import SyncTarget

if TYPE_CHECKING:
    from knowledge_arch.config import NotionSyncConfig
    from knowledge_arch.domain.models import NotionEntityRecord, SourceDocument
    from knowledge_arch.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("NotionSyncTarget")

# upsert 动作语义（上层据此记账/汇总）
ACTION_CREATED = "created"
ACTION_UPDATED = "updated"


@dataclass
class NotionUpsertResult:
    """一次幂等 upsert 的结果。

    - action ∈ {created, updated}：updated 含「复用远端同幂等键页面重写」
      （QA 重试或跨进程去重命中）。
    - degraded=True 表示属性经降级重试才写入成功（message 携带原因）。
    - skipped_binary=True 表示大文件跳过了二进制镜像（仅元数据 + callout）。
    - content_synced=False 表示正文块本轮尝试写入但失败——上层据此**不推进**
      账本 content_hash，使下一轮判定为「正文待重写」而非跳过（防缺正文页被
      误标 synced）。默认 True 覆盖「无需重写正文」的常态。
    """

    page_id: str
    action: str
    degraded: bool = False
    skipped_binary: bool = False
    content_synced: bool = True
    message: str = ""


class NotionSyncTarget(SyncTarget):
    """基于 MCP 调用的 Notion 单向推送目标（Articles + QA 两表）。"""

    def __init__(
        self,
        config: NotionSyncConfig,
        source_store: SourceDocumentStore,
        context: Any = None,
        *,
        adapter: NotionMCPAdapter | None = None,
    ) -> None:
        self._config = config
        self._source_store = source_store
        self._adapter = adapter or NotionMCPAdapter(
            context,
            server_name=config.mcp_server_name,
            rate_limit_rps=config.rate_limit_rps,
        )

    @property
    def kind(self) -> SyncTargetKind:
        return SyncTargetKind.NOTION

    @property
    def config(self) -> NotionSyncConfig:
        """当前生效配置（initialize_databases 后含回填的 database id）。"""
        return self._config

    # ── SyncTarget 契约 ─────────────────────────────────────────

    async def push(self, document: SourceDocument, payload: bytes) -> str:
        """SyncTarget 通用文档推送：委派幂等 upsert。

        无账本/集合树上下文时的独立调用路径（SyncPipeline "all"），path 与
        Collections 退化为冗余 primary 集合名。保持历史前缀协议：
        degraded:/skipped:/degraded_skipped: 供 SyncPipeline 记账解析。
        """
        result = await self.upsert_document(
            document,
            path=document.collection,
            collection_names=[document.collection] if document.collection else [],
            prior=None,
        )
        if result.degraded and result.skipped_binary:
            return f"degraded_skipped:{result.page_id}"
        if result.skipped_binary:
            return f"skipped:{result.page_id}"
        if result.degraded:
            return f"degraded:{result.page_id}"
        return result.page_id

    async def delete(self, remote_ref: str) -> bool:
        """归档远端页面（页面即 block，经 notion_delete_block）。"""
        if not self._config.enabled:
            return False
        try:
            return await self._adapter.delete_block(remote_ref)
        except NotionMCPError as e:
            logger.warning("Notion 页面归档失败（%s）：%s", remote_ref, e)
            return False

    async def check_quota(self, pending_bytes: int = 0) -> QuotaUsage:
        # Notion 数据库不按字节计额度，默认返回 limit_bytes=0, used_bytes=0
        return QuotaUsage(
            target=SyncTargetKind.NOTION,
            used_bytes=0,
            limit_bytes=0,
            pending_bytes=pending_bytes,
        )

    # ── 建库（两表 + 缺列对账）──────────────────────────────────

    async def initialize_databases(
        self,
        parent_page_id: str | None = None,
        database_title: str | None = None,
    ) -> dict[str, Any]:
        """确保 Articles 与 QA 两库存在且列齐全，返回两个 database_id。

        顺序：先确保 Articles（已配 id 则 retrieve 对账补缺列，未配则新建），
        再确保 QA（新建即带指向 Articles 的 Citations relation）。任一补列/
        relation 失败仅记 warning + degraded，不阻断（对应列走降级路径）。
        """
        if not self._config.enabled:
            return {"status": "error", "message": "Notion sync is disabled in configuration."}

        parent = parent_page_id or self._config.parent_page_id
        title = database_title or self._config.database_title
        warnings: list[str] = []
        degraded = False

        # 1) Articles 库
        articles_id = self._config.database_id
        created_articles = False
        if articles_id:
            try:
                await self._ensure_database_properties(
                    articles_id, schema.articles_db_properties()
                )
            except NotionMCPError as e:
                degraded = True
                warnings.append(f"Articles 库缺列补齐失败：{e}")
        else:
            if not parent:
                return {"status": "error", "message": "Notion parent_page_id is required."}
            articles_id = await self._adapter.create_database(
                parent_page_id=parent,
                title=title,
                properties=schema.articles_db_properties(),
            )
            created_articles = True

        # 2) QA 库（Citations relation 指向 Articles）
        qa_id = self._config.qa_database_id
        created_qa = False
        if qa_id:
            try:
                await self._ensure_database_properties(
                    qa_id, schema.qa_db_properties(articles_id)
                )
            except NotionMCPError as e:
                degraded = True
                warnings.append(f"QA 库缺列补齐失败：{e}")
        else:
            if not parent:
                return {"status": "error", "message": "Notion parent_page_id is required."}
            qa_title = f"{title} · QA"
            try:
                qa_id = await self._adapter.create_database(
                    parent_page_id=parent,
                    title=qa_title,
                    properties=schema.qa_db_properties(articles_id),
                )
            except NotionMCPError as e:
                # relation 配置被拒时退化为无 relation 建库（Citations 走正文文本）
                degraded = True
                warnings.append(f"QA 库带 Citations relation 建库失败，已降级重试：{e}")
                qa_id = await self._adapter.create_database(
                    parent_page_id=parent,
                    title=qa_title,
                    properties=schema.qa_db_properties(""),
                )
            created_qa = True

        self._config = replace(
            self._config,
            database_id=articles_id,
            qa_database_id=qa_id,
            parent_page_id=parent or self._config.parent_page_id,
            database_title=title,
        )
        return {
            "status": "success",
            "database_id": articles_id,
            "qa_database_id": qa_id,
            "parent_page_id": self._config.parent_page_id,
            "database_title": title,
            "created": created_articles or created_qa,
            "created_articles": created_articles,
            "created_qa": created_qa,
            "degraded": degraded,
            "warnings": warnings,
            "message": "Notion databases ready.",
        }

    async def _ensure_database_properties(
        self, database_id: str, expected: dict[str, Any]
    ) -> None:
        """retrieve 对账：缺列则 update_database 补齐（已存在的列不动，幂等）。"""
        data = await self._adapter.retrieve_database(database_id)
        existing = data.get("properties")
        existing_names = set(existing.keys()) if isinstance(existing, dict) else set()
        missing = {k: v for k, v in expected.items() if k not in existing_names}
        if missing:
            await self._adapter.update_database(database_id, missing)

    # ── 文章幂等 upsert ─────────────────────────────────────────

    async def upsert_document(
        self,
        document: SourceDocument,
        *,
        path: str,
        collection_names: list[str],
        prior: NotionEntityRecord | None = None,
        force_body: bool = False,
    ) -> NotionUpsertResult:
        """把一篇文章幂等推送到 Articles 库。

        幂等序列：prior.page_id 直接 update（404/失败落 miss 分支）→ 按 DocID
        反查回填 → 仍无才 create。正文块在 create、content_hash 变化或
        force_body=True 时写入/重写。是否需要推送（指纹相等 skip）由上层判定。
        """
        if not self._config.enabled:
            raise ValueError("Notion sync is disabled in configuration.")
        if not self._config.database_id:
            raise ValueError("Notion Database ID is required.")

        properties = schema.article_page_properties(
            document, path=path, collection_names=collection_names
        )
        degraded = False
        message = ""
        action = ACTION_UPDATED

        page_id = prior.page_id if prior is not None else ""
        if page_id:
            try:
                await self._adapter.update_page_properties(page_id, properties)
            except NotionMCPError as e:
                logger.warning(
                    "Notion 按账本 page_id 更新失败（%s），转按 DocID 反查：%s",
                    page_id,
                    e,
                )
                page_id = ""

        if not page_id:
            page_id = await self._find_page_by_key(
                self._config.database_id, schema.PROP_DOC_ID, document.doc_id
            )
            if page_id:
                degraded, message = await self._update_with_degradation(
                    page_id, properties, document
                )
            else:
                action = ACTION_CREATED
                page_id, degraded, message = await self._create_with_degradation(
                    self._config.database_id, properties, document
                )

        is_large = document.size_bytes > self._config.max_upload_bytes
        rewrite_blocks = force_body or action == ACTION_CREATED or (
            prior is not None and prior.content_hash != document.content_hash
        )
        content_synced = True
        if rewrite_blocks:
            try:
                await self._write_document_body(
                    page_id, document, is_large=is_large, is_new=action == ACTION_CREATED
                )
            except NotionMCPError as e:
                degraded = True
                content_synced = False  # 正文没写成 → 上层不推进 content_hash，下轮重试
                message = message or f"正文块写入失败：{e}"
                logger.warning("Notion 正文块写入失败（%s）：%s", document.doc_id, e)

        return NotionUpsertResult(
            page_id=page_id,
            action=action,
            degraded=degraded,
            skipped_binary=is_large,
            content_synced=content_synced,
            message=message,
        )

    async def _update_with_degradation(
        self, page_id: str, properties: dict[str, Any], document: SourceDocument
    ) -> tuple[bool, str]:
        """update 属性；失败降级为 Name+DocID 最小集重试一次。返回 (degraded, message)。"""
        try:
            await self._adapter.update_page_properties(page_id, properties)
            return False, ""
        except NotionMCPError as e:
            minimal = self._minimal_properties(document)
            await self._adapter.update_page_properties(page_id, minimal)
            return True, f"属性降级为最小集：{e}"

    async def _create_with_degradation(
        self, database_id: str, properties: dict[str, Any], document: SourceDocument
    ) -> tuple[str, bool, str]:
        """create 页面；失败降级为 Name+DocID 最小集重试一次。返回 (page_id, degraded, message)。"""
        try:
            page_id = await self._adapter.create_database_item(database_id, properties)
            return page_id, False, ""
        except NotionMCPError as e:
            logger.warning("Notion 全属性建页失败，降级为最小集重试：%s", e)
            minimal = self._minimal_properties(document)
            page_id = await self._adapter.create_database_item(database_id, minimal)
            return page_id, True, f"属性降级为最小集：{e}"

    @staticmethod
    def _minimal_properties(document: SourceDocument) -> dict[str, Any]:
        """降级最小属性集：Name 必填 + DocID 必留（否则丢失幂等键，重复页面复发）。"""
        return {
            schema.PROP_NAME: {"title": [{"text": {"content": document.title}}]},
            schema.PROP_DOC_ID: {
                "rich_text": [{"text": {"content": document.doc_id}}]
            },
        }

    async def _write_document_body(
        self,
        page_id: str,
        document: SourceDocument,
        *,
        is_large: bool,
        is_new: bool,
    ) -> None:
        """写文章页正文：大文件 callout / 切片预览；非新建页先清旧块再追加。"""
        if not is_new:
            await self._clear_page_blocks(page_id)
        if is_large:
            children: list[dict[str, Any]] = [schema.large_file_callout_block()]
        else:
            try:
                chunks = await self._source_store.list_chunks(document.doc_id)
            except Exception as e:
                logger.error("读取文档切片失败（%s）：%s", document.doc_id, e)
                chunks = []
            children = schema.chunk_preview_blocks(chunks)
        if children:
            await self._adapter.append_blocks(page_id, children)

    async def _clear_page_blocks(self, page_id: str) -> None:
        blocks = await self._adapter.list_block_children(page_id)
        for block in blocks:
            block_id = block.get("id")
            if block_id:
                await self._adapter.delete_block(str(block_id))

    # ── QA 记录（append-only）───────────────────────────────────

    async def create_qa_entry(
        self,
        *,
        title: str,
        content: str,
        tags: list[str],
        citation_page_ids: list[str],
        citation_labels: list[str] | None = None,
        source: str,
        note_id: str,
    ) -> NotionUpsertResult:
        """在 QA 库写入一条问答记录（按 NoteID 幂等）。

        关键：**建页与正文分两步**，中间任一步失败都不能丢正文——若 NoteID 已存在
        （上一轮建页成功但正文没写成，或跨进程去重），走「清块 → 重写正文」的幂等
        rewrite 路径而非直接跳过，保证 body 最终落地、且不重复。content_synced 随
        正文写入结果返回，供上层决定是否清 outbox 存根。

        Citations relation 写入被拒时剔除 relation 降级重试（degraded=True），并把
        已解析的引用 DocID（citation_labels）补进正文尾部，避免降级时引用信息丢失。
        """
        if not self._config.enabled:
            raise ValueError("Notion sync is disabled in configuration.")
        if not self._config.qa_database_id:
            raise ValueError("Notion QA database ID is required (run initialize first).")

        properties = schema.qa_page_properties(
            title=title,
            note_id=note_id,
            tags=tags,
            citation_page_ids=citation_page_ids,
            source=source,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        degraded = False
        message = ""

        existing = await self._find_page_by_key(
            self._config.qa_database_id, schema.PROP_NOTE_ID, note_id
        )
        reused = bool(existing)
        if reused:
            page_id = existing
        else:
            try:
                page_id = await self._adapter.create_database_item(
                    self._config.qa_database_id, properties
                )
            except NotionMCPError as e:
                properties.pop(schema.PROP_CITATIONS, None)
                logger.warning("QA 建行失败，剔除 Citations relation 降级重试：%s", e)
                page_id = await self._adapter.create_database_item(
                    self._config.qa_database_id, properties
                )
                degraded = True
                message = f"Citations relation 降级：{e}"

        # 降级时把已解析引用补进正文尾部（relation 丢了但引用信息不丢）。
        body = content
        if degraded and citation_labels:
            body = f"{content}\n\n引用文献（DocID，未建立链接）：{'、'.join(citation_labels)}"

        content_synced = True
        try:
            blocks = schema.text_to_paragraph_blocks(body)
            if reused:
                # 复用既有页面（上轮 body 可能残缺/为空）→ 清块后重写，幂等无重复。
                await self._clear_page_blocks(page_id)
            if blocks:
                await self._adapter.append_blocks(page_id, blocks)
        except NotionMCPError as e:
            content_synced = False
            message = message or f"QA 正文写入失败：{e}"
            logger.warning("QA 正文写入失败（NoteID=%s）：%s", note_id, e)

        return NotionUpsertResult(
            page_id=page_id,
            action=ACTION_UPDATED if reused else ACTION_CREATED,
            degraded=degraded,
            content_synced=content_synced,
            message=message,
        )

    # ── 幂等键反查 ──────────────────────────────────────────────

    async def _find_page_by_key(
        self, database_id: str, property_name: str, value: str
    ) -> str:
        """按 rich_text 幂等键 equals 反查页面 id；未命中返回空串。"""
        if not value:
            return ""
        pages = await self._adapter.query_database(
            database_id,
            filter={"property": property_name, "rich_text": {"equals": value}},
            page_size=1,
        )
        for page in pages:
            page_id = page.get("id")
            if page_id:
                return str(page_id)
        return ""


__all__ = [
    "NotionSyncTarget",
    "NotionUpsertResult",
    "ACTION_CREATED",
    "ACTION_UPDATED",
]
