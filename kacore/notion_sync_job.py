"""Notion 单向推送任务的进度模型（domain-light，无 I/O）。

为什么存在：`NotionSyncPipeline.push_all` 原本同步阻塞、且**不可观测**——文档 diff/upsert、
QA outbox 补推、strict 选项清理全压在一个 HTTP 请求里（大库时数分钟，易超时 = 用户侧「失灵」），
失败又被塞进返回 dict 无人上报。本模块定义一个**纯内存**的推送任务快照，由 `kacore/api.py` 的
后台任务在 `push_all` 的各阶段/逐文档循环中更新，并经 HTTP 暴露给前端轮询，从而与
Zotero/Milvus/LightRAG 共用同一套「后台任务 + 进度条」体验（见 `kacore/zotero_sync_job.py`）。

进度单位：以文章文档为主（`docs_processed/docs_total`）；QA 补推与 strict 选项清理阶段无文档计数，
用 `_STAGE_BASE_PCT` 给出阶段底值，保证进度条平滑不假死。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── 状态常量（杜绝魔法字面量散落）─────────────────────────────
NOTION_SYNC_RUNNING = "running"
NOTION_SYNC_SUCCESS = "success"
NOTION_SYNC_PARTIAL = "partial_failure"
NOTION_SYNC_ERROR = "error"

NOTION_SYNC_ACTIVE_STATUSES = frozenset({NOTION_SYNC_RUNNING})
NOTION_SYNC_TERMINAL_STATUSES = frozenset(
    {NOTION_SYNC_SUCCESS, NOTION_SYNC_PARTIAL, NOTION_SYNC_ERROR}
)

# ── 阶段常量与展示标签 ────────────────────────────────────────
NOTION_STAGE_PREPARING = "preparing"
NOTION_STAGE_PUSHING_DOCUMENTS = "pushing_documents"
NOTION_STAGE_PUSHING_QA = "pushing_qa"
NOTION_STAGE_PRUNING_TAGS = "pruning_tags"
NOTION_STAGE_FINALIZING = "finalizing"

NOTION_STAGE_LABELS = {
    NOTION_STAGE_PREPARING: "Preparing",
    NOTION_STAGE_PUSHING_DOCUMENTS: "Pushing documents",
    NOTION_STAGE_PUSHING_QA: "Pushing QA outbox",
    NOTION_STAGE_PRUNING_TAGS: "Pruning stale options",
    NOTION_STAGE_FINALIZING: "Finalizing",
}

# 无文档计数阶段的进度底值（pushing_documents 在底值之上叠加文档完成比）。
_STAGE_BASE_PCT = {
    NOTION_STAGE_PREPARING: 3,
    NOTION_STAGE_PUSHING_DOCUMENTS: 8,
    NOTION_STAGE_PUSHING_QA: 88,
    NOTION_STAGE_PRUNING_TAGS: 94,
    NOTION_STAGE_FINALIZING: 98,
}
# pushing_documents 阶段文档进度占据的百分比跨度（8% → 85%）。
_DOCS_PCT_SPAN = 77


@dataclass
class NotionSyncJob:
    """单次 Notion push_all 的进度快照。

    契约：
    - `status`：`running` → 终态 `success` / `partial_failure`（有 warnings 但有产出）/ `error`。
    - `stage`：见 `NOTION_STAGE_*`；`stage_label` 为人类可读标签（空则按 stage 查表）。
    - 文档进度以文章为单位：`docs_total` 为本轮待推文档数，每篇恰好落入
      created/updated/archived/skipped/failed 之一，并统一累加进 `docs_processed`。
    - `progress_percent`：success 固定 100；否则按阶段底值 + 文档完成比，封顶 99。
    - 同一时间全局只允许一个活动任务（由 api 层守卫，不在本对象内强制）。
    """

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = NOTION_SYNC_RUNNING
    stage: str = NOTION_STAGE_PREPARING
    stage_label: str = ""
    force: bool = False
    sync_mode: str = ""
    docs_total: int = 0
    docs_processed: int = 0
    docs_created: int = 0
    docs_updated: int = 0
    docs_archived: int = 0
    docs_skipped: int = 0
    docs_failed: int = 0
    qa_pushed: int = 0
    qa_failed: int = 0
    tags_pruned: int = 0
    started_at: float = field(default_factory=time.monotonic)
    started_at_iso: str = ""
    finished_at: float | None = None
    finished_at_iso: str | None = None
    recent_error: str = ""
    errors: list[str] = field(default_factory=list)

    # ── 生命周期助手 ──────────────────────────────────────────
    def start(self) -> None:
        """记录起始 ISO 时间（monotonic 已在构造时落定，仅用于 elapsed）。"""
        self.started_at_iso = datetime.now(timezone.utc).isoformat()

    def finish(self, status: str) -> None:
        """落定终态与结束时间。"""
        self.status = status
        self.finished_at = time.monotonic()
        self.finished_at_iso = datetime.now(timezone.utc).isoformat()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.stage_label = NOTION_STAGE_LABELS.get(stage, stage)

    def note_error(self, message: str) -> None:
        """登记一条错误（同时刷新 recent_error 供前端醒目展示）。"""
        self.errors.append(message)
        self.recent_error = message

    def record_document(self, action: str) -> None:
        """按 push 动作累加计数：created/updated/archived/skipped/failed 之一 + 总数。"""
        self.docs_processed += 1
        counter = f"docs_{action}"
        if hasattr(self, counter):
            setattr(self, counter, getattr(self, counter) + 1)

    # ── 序列化 ────────────────────────────────────────────────
    def progress_percent(self) -> int:
        if self.status == NOTION_SYNC_SUCCESS:
            return 100
        base = _STAGE_BASE_PCT.get(self.stage, 0)
        if self.stage == NOTION_STAGE_PUSHING_DOCUMENTS and self.docs_total > 0:
            done = min(self.docs_processed, self.docs_total)
            base += round(_DOCS_PCT_SPAN * min(1.0, done / self.docs_total))
        return min(99, max(0, base))

    def to_dict(self) -> dict[str, Any]:
        elapsed_end = self.finished_at or time.monotonic()
        elapsed = max(0.0, elapsed_end - self.started_at)
        return {
            "job_id": self.job_id,
            "type": "notion_sync",
            "status": self.status,
            "stage": self.stage,
            "stage_label": self.stage_label or NOTION_STAGE_LABELS.get(self.stage, self.stage),
            "force": self.force,
            "sync_mode": self.sync_mode,
            "docs_total": self.docs_total,
            "docs_processed": self.docs_processed,
            "docs_created": self.docs_created,
            "docs_updated": self.docs_updated,
            "docs_archived": self.docs_archived,
            "docs_skipped": self.docs_skipped,
            "docs_failed": self.docs_failed,
            "qa_pushed": self.qa_pushed,
            "qa_failed": self.qa_failed,
            "tags_pruned": self.tags_pruned,
            "progress_percent": self.progress_percent(),
            "elapsed_seconds": round(elapsed, 2),
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "recent_error": self.recent_error,
            "errors": self.errors[:5],
        }


__all__ = [
    "NotionSyncJob",
    "NOTION_SYNC_RUNNING",
    "NOTION_SYNC_SUCCESS",
    "NOTION_SYNC_PARTIAL",
    "NOTION_SYNC_ERROR",
    "NOTION_SYNC_ACTIVE_STATUSES",
    "NOTION_SYNC_TERMINAL_STATUSES",
    "NOTION_STAGE_PREPARING",
    "NOTION_STAGE_PUSHING_DOCUMENTS",
    "NOTION_STAGE_PUSHING_QA",
    "NOTION_STAGE_PRUNING_TAGS",
    "NOTION_STAGE_FINALIZING",
    "NOTION_STAGE_LABELS",
]
