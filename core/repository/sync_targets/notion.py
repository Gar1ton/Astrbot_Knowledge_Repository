"""Notion 镜像同步目标实现（repository 层）。

经 Notion MCP 客户端实现原件元数据至在线数据库的单镜像。
支持 5MiB 免费上传限额判定、3 req/s 频控，以及渐进式降级容错属性写入。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.adapters.notion_mcp import NotionMCPAdapter
from core.domain.models import QuotaUsage, SyncTargetKind
from core.repository.sync_targets.base import SyncTarget

if TYPE_CHECKING:
    from core.config import NotionSyncConfig
    from core.domain.models import SourceDocument
    from core.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("NotionSyncTarget")


class NotionSyncTarget(SyncTarget):
    """基于 MCP 调用的 Notion 在线镜像同步目标。"""

    def __init__(
        self,
        config: NotionSyncConfig,
        source_store: SourceDocumentStore,
        context: Any = None,
    ) -> None:
        self._config = config
        self._source_store = source_store
        self._context = context
        self._mcp_adapter = NotionMCPAdapter(
            context, server_name=config.mcp_server_name
        )

    @property
    def kind(self) -> SyncTargetKind:
        return SyncTargetKind.NOTION

    async def push(self, document: SourceDocument, payload: bytes) -> str:
        if not self._config.enabled:
            raise ValueError("Notion sync is disabled in configuration.")
        if not self._config.database_id:
            raise ValueError("Notion Database ID is required.")

        # 1) 遵守 Notion 3 req/s 频控频次
        delay = 1.0 / max(1, self._config.rate_limit_rps)
        logger.info(
            f"[Notion Rate Limit] Delaying {delay:.2f} seconds before pushing {document.title}..."
        )
        await asyncio.sleep(delay)

        # 2) 构造 Notion 数据库属性页载荷
        # 优先使用完整的属性布局，以实现 Graceful Degradation (智能渐进式降级)
        properties = {
            "Name": {"title": [{"text": {"content": document.title}}]},
            "Collection": {"select": {"name": document.collection}},
            "Tags": {"multi_select": [{"name": t} for t in document.tags]},
            "DocID": {"rich_text": [{"text": {"content": document.doc_id}}]},
        }

        # 3) 组装页面内容 (Children Blocks)
        # 支持 Chunks 前 2-3 个分块写入 Notion Body
        children = []
        is_large = len(payload) > self._config.max_upload_bytes

        if is_large:
            # 大文件跳过二进制正文/附件上传，添加一段友好的警告块
            children.append(
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": (
                                        "⚠️ [Notion 免费版限制] 该文件大小超过 5MiB，"
                                        "已跳过文件二进制镜像。您可以去本地原件中查看。"
                                    )
                                },
                            }
                        ],
                        "icon": {"emoji": "⚠️"},
                        "color": "yellow_background",
                    },
                }
            )
        else:
            # 正常大小文件，写入标题和 Chunks 预览区块
            children.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {"type": "text", "text": {"content": "本地切片摘要 (Chunks Preview)"}}
                        ]
                    },
                }
            )

            try:
                # 获取该文档的 Chunks 预览
                chunks = await self._source_store.list_chunks(document.doc_id)
                # 仅添加前 3 个 Chunks
                for chunk in chunks[:3]:
                    text_content = chunk.text
                    if len(text_content) > 1000:
                        text_content = text_content[:1000] + "..."
                    children.append(
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {
                                            "content": f"[Chunk #{chunk.ordinal}] {text_content}"
                                        },
                                    }
                                ]
                            },
                        }
                    )
            except Exception as e:
                logger.error(
                    f"Failed to load document chunks for Notion body: {e}"
                )

        # 4) 调用 MCP 创建页面（带渐进降级保护）
        try:
            page_id = await self._mcp_adapter.create_database_page(
                database_id=self._config.database_id,
                properties=properties,
                children=children,
            )
        except Exception as e:
            logger.warning(
                f"Failed to create database page with full properties: {e}. "
                "Attempting graceful degradation to Name-only properties..."
            )
            # 降级：仅包含必填的 "Name" 属性
            min_properties = {
                "Name": {"title": [{"text": {"content": document.title}}]}
            }
            page_id = await self._mcp_adapter.create_database_page(
                database_id=self._config.database_id,
                properties=min_properties,
                children=children,
            )

        # 5) 对超过 5MiB 的大文档，利用 "skipped:" 前缀将跳过状态通知 SyncPipeline 记账
        if is_large:
            return f"skipped:{page_id}"
        return page_id

    async def delete(self, remote_ref: str) -> bool:
        if not self._config.enabled:
            return False
        # 1) 遵守 Notion 3 req/s 频控
        delay = 1.0 / max(1, self._config.rate_limit_rps)
        await asyncio.sleep(delay)

        # 2) 归档 Notion 页面
        return await self._mcp_adapter.delete_page(remote_ref)

    async def check_quota(self, pending_bytes: int = 0) -> QuotaUsage:
        # Notion 数据库不按字节计额度，默认返回 limit_bytes=0, used_bytes=0
        return QuotaUsage(
            target=SyncTargetKind.NOTION,
            used_bytes=0,
            limit_bytes=0,
            pending_bytes=pending_bytes,
        )


__all__ = ["NotionSyncTarget"]
