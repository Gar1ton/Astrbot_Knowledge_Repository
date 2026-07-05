"""Zotero 单向 Pull 同步任务的进度模型（domain-light，无 I/O）。

为什么存在：`sync_zotero_pull` 原本同步阻塞、且**不可观测**——几十篇 PDF 逐篇 Web API 下载→清洗→
分块→embedding 全压在一个 HTTP 请求里（数分钟，易超时 = 用户侧「失灵」），失败又被静默吞进
`ZoteroSyncResult.errors` 无人上报。本模块定义一个**纯内存**的同步任务快照，由 `core/api.py` 的后台
任务在 `ZoteroSyncPipeline.pull` 的各阶段/逐文档循环中更新，并经 HTTP 暴露给前端轮询，从而与 Milvus/
LightRAG 共用同一套「后台任务 + 进度条」体验（见 `core/milvus_build.py:MilvusBuildJob`）。

进度单位：以 PDF 附件文档为主（`docs_processed/docs_total`）；快照读取/镜像/删除等无文档计数的阶段
用 `_STAGE_BASE_PCT` 给出阶段底值，保证进度条平滑不假死。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── 状态常量（杜绝魔法字面量散落）─────────────────────────────
ZOTERO_SYNC_RUNNING = "running"
ZOTERO_SYNC_SUCCESS = "success"
ZOTERO_SYNC_PARTIAL = "partial_failure"
ZOTERO_SYNC_ERROR = "error"

ZOTERO_SYNC_ACTIVE_STATUSES = frozenset({ZOTERO_SYNC_RUNNING})
ZOTERO_SYNC_TERMINAL_STATUSES = frozenset(
    {ZOTERO_SYNC_SUCCESS, ZOTERO_SYNC_PARTIAL, ZOTERO_SYNC_ERROR}
)

# ── 阶段常量与展示标签 ────────────────────────────────────────
ZOTERO_STAGE_READING = "reading_snapshot"
ZOTERO_STAGE_MIRRORING = "mirroring"
ZOTERO_STAGE_SYNCING_DOCS = "syncing_documents"
ZOTERO_STAGE_APPLYING_REMOVALS = "applying_removals"
ZOTERO_STAGE_FINALIZING = "finalizing"

ZOTERO_STAGE_LABELS = {
    ZOTERO_STAGE_READING: "Reading Zotero library",
    ZOTERO_STAGE_MIRRORING: "Mirroring metadata",
    ZOTERO_STAGE_SYNCING_DOCS: "Syncing documents",
    ZOTERO_STAGE_APPLYING_REMOVALS: "Applying removals",
    ZOTERO_STAGE_FINALIZING: "Finalizing",
}

# 无文档计数阶段的进度底值（syncing_documents 在底值之上叠加文档完成比）。
_STAGE_BASE_PCT = {
    ZOTERO_STAGE_READING: 3,
    ZOTERO_STAGE_MIRRORING: 8,
    ZOTERO_STAGE_SYNCING_DOCS: 10,
    ZOTERO_STAGE_APPLYING_REMOVALS: 92,
    ZOTERO_STAGE_FINALIZING: 97,
}
# syncing_documents 阶段文档进度占据的百分比跨度（10% → 90%）。
_DOCS_PCT_SPAN = 80


@dataclass
class ZoteroSyncJob:
    """单次 Zotero Pull 的进度快照。

    契约：
    - `status`：`running` → 终态 `success` / `partial_failure`（有 errors 但有产出）/ `error`。
    - `stage`：见 `ZOTERO_STAGE_*`；`stage_label` 为人类可读标签（空则按 stage 查表）。
    - 文档进度以 PDF 附件为单位：`docs_total` 为本轮待考察附件数，每篇恰好落入
      `docs_processed`（成功摄入）/ `docs_failed`（摄入抛错）/ `skipped_unchanged`（增量跳过）之一。
    - `progress_percent`：success 固定 100；否则按阶段底值 + 文档完成比，封顶 99。
    - 同一时间全局只允许一个活动任务（由 api 层守卫，不在本对象内强制）。
    """

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = ZOTERO_SYNC_RUNNING
    stage: str = ZOTERO_STAGE_READING
    stage_label: str = ""
    incremental: bool = True
    sync_mode: str = ""
    storage_mode: str = ""
    access_mode: str = ""
    items_total: int = 0
    docs_total: int = 0
    docs_processed: int = 0
    docs_failed: int = 0
    skipped_unchanged: int = 0
    new_count: int = 0
    changed_count: int = 0
    removed_count: int = 0
    detached_count: int = 0
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
        self.stage_label = ZOTERO_STAGE_LABELS.get(stage, stage)

    def note_error(self, message: str) -> None:
        """登记一条错误（同时刷新 recent_error 供前端醒目展示）。"""
        self.errors.append(message)
        self.recent_error = message

    # ── 序列化 ────────────────────────────────────────────────
    def progress_percent(self) -> int:
        if self.status == ZOTERO_SYNC_SUCCESS:
            return 100
        base = _STAGE_BASE_PCT.get(self.stage, 0)
        if self.stage == ZOTERO_STAGE_SYNCING_DOCS and self.docs_total > 0:
            done = self.docs_processed + self.docs_failed + self.skipped_unchanged
            base += round(_DOCS_PCT_SPAN * min(1.0, done / self.docs_total))
        return min(99, max(0, base))

    def to_dict(self) -> dict[str, Any]:
        elapsed_end = self.finished_at or time.monotonic()
        elapsed = max(0.0, elapsed_end - self.started_at)
        return {
            "job_id": self.job_id,
            "type": "zotero_sync",
            "status": self.status,
            "stage": self.stage,
            "stage_label": self.stage_label or ZOTERO_STAGE_LABELS.get(self.stage, self.stage),
            "incremental": self.incremental,
            "sync_mode": self.sync_mode,
            "storage_mode": self.storage_mode,
            "access_mode": self.access_mode,
            "items_total": self.items_total,
            "docs_total": self.docs_total,
            "docs_processed": self.docs_processed,
            "docs_failed": self.docs_failed,
            "skipped_unchanged": self.skipped_unchanged,
            "new": self.new_count,
            "changed": self.changed_count,
            "removed": self.removed_count,
            "detached": self.detached_count,
            "progress_percent": self.progress_percent(),
            "elapsed_seconds": round(elapsed, 2),
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "recent_error": self.recent_error,
            "errors": self.errors[:5],
        }


__all__ = [
    "ZoteroSyncJob",
    "ZOTERO_SYNC_RUNNING",
    "ZOTERO_SYNC_SUCCESS",
    "ZOTERO_SYNC_PARTIAL",
    "ZOTERO_SYNC_ERROR",
    "ZOTERO_SYNC_ACTIVE_STATUSES",
    "ZOTERO_SYNC_TERMINAL_STATUSES",
    "ZOTERO_STAGE_READING",
    "ZOTERO_STAGE_MIRRORING",
    "ZOTERO_STAGE_SYNCING_DOCS",
    "ZOTERO_STAGE_APPLYING_REMOVALS",
    "ZOTERO_STAGE_FINALIZING",
    "ZOTERO_STAGE_LABELS",
]
