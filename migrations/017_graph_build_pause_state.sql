-- LightRAG 构建暂停/恢复状态持久化

ALTER TABLE graph_build_jobs
    ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0;

ALTER TABLE graph_build_jobs
    ADD COLUMN paused_at TEXT;

ALTER TABLE graph_build_jobs
    ADD COLUMN paused_seconds REAL NOT NULL DEFAULT 0;

ALTER TABLE graph_build_jobs
    ADD COLUMN progress_current INTEGER NOT NULL DEFAULT 0;

ALTER TABLE graph_build_jobs
    ADD COLUMN progress_total INTEGER NOT NULL DEFAULT 0;
