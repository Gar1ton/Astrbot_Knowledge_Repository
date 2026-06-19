"""Milvus 向量库重建任务的进度模型（domain-light，无 I/O）。

为什么存在：`rebuild_vector_store`（全量）/ `rebuild_index_pending`（增量）原本是同步阻塞、
无进度反馈的。本模块定义一个**纯内存**的构建任务快照对象，由 `core/api.py` 的后台任务在逐
文档循环中更新，并经 HTTP 暴露给前端轮询，从而复刻 LightRAG 构建进度条的体验。

与 LightRAG `BuildJob` 不同：Milvus 构建**无暂停**（必须构建成功）。进度单位是「阶段文档」：
先 data cleaning，再 vector indexing；旧字段 `processed_docs/total_docs` 继续表示索引文档进度。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# ── 状态常量（杜绝魔法字面量散落）─────────────────────────────
MILVUS_BUILD_RUNNING = "running"
MILVUS_BUILD_SUCCESS = "success"
MILVUS_BUILD_PARTIAL = "partial_failure"
MILVUS_BUILD_ERROR = "error"

MILVUS_BUILD_STAGE_CLEANING = "data_cleaning"
MILVUS_BUILD_STAGE_INDEXING = "vector_indexing"
MILVUS_BUILD_STAGE_FINALIZING = "finalizing"

MILVUS_BUILD_STAGE_LABELS = {
    MILVUS_BUILD_STAGE_CLEANING: "Data cleaning",
    MILVUS_BUILD_STAGE_INDEXING: "Vector indexing",
    MILVUS_BUILD_STAGE_FINALIZING: "Finalizing",
}

MILVUS_BUILD_ACTIVE_STATUSES = frozenset({MILVUS_BUILD_RUNNING})
MILVUS_BUILD_TERMINAL_STATUSES = frozenset(
    {MILVUS_BUILD_SUCCESS, MILVUS_BUILD_PARTIAL, MILVUS_BUILD_ERROR}
)


@dataclass
class MilvusBuildJob:
    """单次 Milvus 重建任务的进度快照。

    契约：
    - `mode`：`"pending"`（增量，仅 needs_reindex 文档）或 `"full"`（全量）。
    - `status`：`running` → 终态 `success` / `partial_failure`（有 failed_docs）/ `error`（整体异常）。
    - 旧进度字段保持兼容：`processed_docs` 表示已成功索引的文档数，`total_docs` 表示目标文档数。
    - 新进度以阶段文档为单位：cleaning 与 indexing 分开计数，`progress_percent` 使用二者合并值。
    - 同一时间全局只允许一个活动任务（由 api 层守卫，不在本对象内强制）。
    """

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    mode: str = "pending"
    status: str = MILVUS_BUILD_RUNNING
    stage: str = MILVUS_BUILD_STAGE_CLEANING
    stage_label: str = ""
    total_docs: int = 0
    processed_docs: int = 0
    failed_docs: int = 0
    total_clean_docs: int = 0
    processed_clean_docs: int = 0
    total_index_docs: int = 0
    processed_index_docs: int = 0
    total_chunks: int = 0
    started_at: float = field(default_factory=time.monotonic)
    started_at_iso: str = ""
    finished_at: float | None = None
    finished_at_iso: str | None = None
    recent_error: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        elapsed_end = self.finished_at or time.monotonic()
        elapsed = max(0.0, elapsed_end - self.started_at)
        phase_total = self.total_clean_docs + self.total_index_docs
        if phase_total > 0:
            phase_done = (
                self.processed_clean_docs
                + self.processed_index_docs
                + self.failed_docs
            )
            progress_percent = round((phase_done / phase_total) * 100)
        else:
            done = self.processed_docs + self.failed_docs
            progress_percent = round((done / self.total_docs) * 100) if self.total_docs > 0 else 0
        progress_percent = min(100, max(0, progress_percent))
        stage_label = self.stage_label or MILVUS_BUILD_STAGE_LABELS.get(self.stage, self.stage)
        return {
            "job_id": self.job_id,
            "type": "milvus_build",
            "mode": self.mode,
            "status": self.status,
            "stage": self.stage,
            "stage_label": stage_label,
            "total_docs": self.total_docs,
            "processed_docs": self.processed_docs,
            "failed_docs": self.failed_docs,
            "total_clean_docs": self.total_clean_docs,
            "processed_clean_docs": self.processed_clean_docs,
            "total_index_docs": self.total_index_docs,
            "processed_index_docs": self.processed_index_docs,
            "total_chunks": self.total_chunks,
            "progress_percent": progress_percent,
            "elapsed_seconds": round(elapsed, 2),
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "recent_error": self.recent_error,
            "errors": self.errors[:5],
        }


__all__ = [
    "MilvusBuildJob",
    "MILVUS_BUILD_RUNNING",
    "MILVUS_BUILD_SUCCESS",
    "MILVUS_BUILD_PARTIAL",
    "MILVUS_BUILD_ERROR",
    "MILVUS_BUILD_STAGE_CLEANING",
    "MILVUS_BUILD_STAGE_INDEXING",
    "MILVUS_BUILD_STAGE_FINALIZING",
    "MILVUS_BUILD_ACTIVE_STATUSES",
    "MILVUS_BUILD_TERMINAL_STATUSES",
]
