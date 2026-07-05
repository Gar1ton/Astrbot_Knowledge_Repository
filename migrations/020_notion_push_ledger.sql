-- 020_notion_push_ledger.sql
-- Notion 单向推送账本与 QA 暂存箱：
--   notion_entity_map — (entity_type, entity_key) → page_id + 双指纹（metadata/content），
--     增量判定与幂等 upsert 的本地真相源。不设 FK（entity_key 跨 documents/scoped_notes
--     两表）；本地实体删除后的孤儿行由 NotionSyncPipeline push 时对账清理。
--   notion_outbox — agent/Ask 推送 QA 的暂存箱；pushed 后 content 置空留存根，
--     failed/pending 保留全文等待补推。

CREATE TABLE IF NOT EXISTS notion_entity_map (
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('document', 'note')),
    entity_key    TEXT NOT NULL,
    page_id       TEXT NOT NULL DEFAULT '',
    metadata_hash TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'synced', 'degraded', 'failed')),
    synced_at     TEXT,
    message       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (entity_type, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_notion_entity_map_status
    ON notion_entity_map(status);

CREATE TABLE IF NOT EXISTS notion_outbox (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '[]',
    citations  TEXT NOT NULL DEFAULT '[]',
    source     TEXT NOT NULL DEFAULT 'chat',
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'pushed', 'failed')),
    page_id    TEXT NOT NULL DEFAULT '',
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    pushed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_notion_outbox_status
    ON notion_outbox(status);
