-- 图谱构建任务持久化表
-- 记录每次 LightRAG 构建任务的状态与进度，支持重启后识别中断任务并从断点续建。
CREATE TABLE IF NOT EXISTS graph_build_jobs (
    job_id           TEXT PRIMARY KEY,
    collection       TEXT NOT NULL,
    status           TEXT NOT NULL,
    stage            TEXT NOT NULL,
    processed_docs   INTEGER NOT NULL DEFAULT 0,
    failed_docs      INTEGER NOT NULL DEFAULT 0,
    total_docs       INTEGER NOT NULL DEFAULT 0,
    processed_chunks INTEGER NOT NULL DEFAULT 0,
    failed_chunks    INTEGER NOT NULL DEFAULT 0,
    total_chunks     INTEGER NOT NULL DEFAULT 0,
    recent_error     TEXT NOT NULL DEFAULT '',
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
