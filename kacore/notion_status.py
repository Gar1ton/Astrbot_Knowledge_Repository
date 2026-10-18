"""同步状态聚合：Notion 实体账本优先，保留既有同步列表和其他目标。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kacore.domain.models import NOTION_ENTITY_DOCUMENT, NOTION_PUSH_FAILED, SyncTargetKind

if TYPE_CHECKING:
    from kacore.repository.source_store.base import SourceDocumentStore


async def sync_status(store: SourceDocumentStore) -> list[dict[str, Any]]:
    """按文档/目标去重；Notion 的真实账本覆盖冗余 sync_records。"""
    records = await store.list_sync_records()
    rows = {(r.doc_id, r.target.value): {
        "doc_id": r.doc_id, "target": r.target.value, "remote_ref": r.remote_ref,
        "status": r.status.value, "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        "message": r.message,
    } for r in records}
    for rec in await store.list_notion_entities(NOTION_ENTITY_DOCUMENT):
        rows[(rec.entity_key, SyncTargetKind.NOTION.value)] = {
            "doc_id": rec.entity_key, "target": SyncTargetKind.NOTION.value,
            "remote_ref": rec.page_id, "status": rec.status,
            "synced_at": rec.synced_at.isoformat() if rec.synced_at else None,
            "message": rec.message,
        }
    return list(rows.values())


async def failure_summary(store: SourceDocumentStore) -> list[dict[str, Any]]:
    """相同错误合并计数，最多展示五类，避免 106 条重复文案。"""
    failed = [r for r in await store.list_notion_entities() if r.status == NOTION_PUSH_FAILED]
    failed.extend(await store.list_notion_outbox(NOTION_PUSH_FAILED))
    grouped: dict[str, dict[str, Any]] = {}
    for rec in failed:
        message = rec.message or "（无错误详情）"
        item = grouped.setdefault(message, {"message": message, "count": 0})
        item["count"] += 1
    return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)[:5]
