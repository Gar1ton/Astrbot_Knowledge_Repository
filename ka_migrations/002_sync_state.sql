-- 002_sync_state.sql
-- 源文档同步状态表结构

PRAGMA foreign_keys = ON;

-- 同步记录表（追踪每个文档对每个同步目标的上传状态）
CREATE TABLE IF NOT EXISTS sync_records (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    target TEXT NOT NULL,          -- notion, r2 等
    remote_ref TEXT,               -- S3 key 或 Notion page id，未同步时为 NULL
    content_hash TEXT,             -- 上次同步成功时的原件哈希，与当前不符即需重新同步
    status TEXT NOT NULL DEFAULT 'pending', -- pending, synced, skipped, failed
    synced_at TEXT,                -- ISO8601 格式的时间，NULL 表示尚未成功同步过
    message TEXT NOT NULL DEFAULT '', -- 失败原因或说明
    PRIMARY KEY (doc_id, target)
);

CREATE INDEX IF NOT EXISTS idx_sync_records_status ON sync_records(status);
