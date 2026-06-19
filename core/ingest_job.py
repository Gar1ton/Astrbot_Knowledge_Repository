"""文档上传/摄入任务的进度模型（domain-light，无 I/O）。

为什么存在：手动上传原本只有一个 spinner、无阶段反馈。本模块定义一个**纯内存**的摄入任务快照，
由 `core/api.py:register_document` 在「解析/分块 → 向量索引」两个编排边界上更新，经 HTTP 暴露给前端
统一进度面板轮询（与 `core/milvus_build.py`、`core/zotero_sync_job.py` 同构）。

刻意只在 api 编排层粗粒度跟踪（parsing → indexing），不侵入核心 `ingest_manager` 热路径。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ── 状态常量 ──────────────────────────────────────────────────
INGEST_RUNNING = "running"
INGEST_SUCCESS = "success"
INGEST_ERROR = "error"

INGEST_TERMINAL_STATUSES = frozenset({INGEST_SUCCESS, INGEST_ERROR})

# ── 阶段常量与标签 ────────────────────────────────────────────
INGEST_STAGE_PARSING = "parsing"
INGEST_STAGE_INDEXING = "indexing"

INGEST_STAGE_LABELS = {
    INGEST_STAGE_PARSING: "Parsing & chunking",
    INGEST_STAGE_INDEXING: "Vector indexing",
}

_STAGE_BASE_PCT = {
    INGEST_STAGE_PARSING: 20,
    INGEST_STAGE_INDEXING: 70,
}


@dataclass
class IngestJob:
    """单次文档摄入的进度快照。

    契约：`status` running → 终态 success / error；`stage` 见 `INGEST_STAGE_*`；
    `progress_percent` 终态 success 固定 100，否则取阶段底值（封顶 99）。
    """

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = INGEST_RUNNING
    stage: str = INGEST_STAGE_PARSING
    stage_label: str = ""
    title: str = ""
    doc_id: str = ""
    started_at: float = field(default_factory=time.monotonic)
    started_at_iso: str = ""
    finished_at: float | None = None
    finished_at_iso: str | None = None
    recent_error: str = ""

    def start(self) -> None:
        self.started_at_iso = datetime.now(timezone.utc).isoformat()

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = time.monotonic()
        self.finished_at_iso = datetime.now(timezone.utc).isoformat()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.stage_label = INGEST_STAGE_LABELS.get(stage, stage)

    def progress_percent(self) -> int:
        if self.status == INGEST_SUCCESS:
            return 100
        return min(99, max(0, _STAGE_BASE_PCT.get(self.stage, 0)))

    def to_dict(self) -> dict[str, Any]:
        elapsed_end = self.finished_at or time.monotonic()
        elapsed = max(0.0, elapsed_end - self.started_at)
        return {
            "job_id": self.job_id,
            "type": "ingest",
            "status": self.status,
            "stage": self.stage,
            "stage_label": self.stage_label or INGEST_STAGE_LABELS.get(self.stage, self.stage),
            "title": self.title,
            "doc_id": self.doc_id,
            "progress_percent": self.progress_percent(),
            "elapsed_seconds": round(elapsed, 2),
            "started_at": self.started_at_iso,
            "finished_at": self.finished_at_iso,
            "recent_error": self.recent_error,
        }


__all__ = [
    "IngestJob",
    "INGEST_RUNNING",
    "INGEST_SUCCESS",
    "INGEST_ERROR",
    "INGEST_STAGE_PARSING",
    "INGEST_STAGE_INDEXING",
    "INGEST_STAGE_LABELS",
]
