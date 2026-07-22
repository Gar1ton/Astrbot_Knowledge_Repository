-- Allow the internal Strict-mode archived tombstone status in the Notion ledger.
-- SQLite cannot alter a CHECK constraint in place, so rebuild only this table.

DROP INDEX IF EXISTS idx_notion_entity_map_status;

ALTER TABLE notion_entity_map RENAME TO notion_entity_map_v020;

CREATE TABLE notion_entity_map (
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('document', 'note')),
    entity_key    TEXT NOT NULL,
    page_id       TEXT NOT NULL DEFAULT '',
    metadata_hash TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'synced', 'degraded', 'failed', 'archived')),
    synced_at     TEXT,
    message       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (entity_type, entity_key)
);

INSERT INTO notion_entity_map (
    entity_type,
    entity_key,
    page_id,
    metadata_hash,
    content_hash,
    status,
    synced_at,
    message
)
SELECT
    entity_type,
    entity_key,
    page_id,
    metadata_hash,
    content_hash,
    status,
    synced_at,
    message
FROM notion_entity_map_v020;

DROP TABLE notion_entity_map_v020;

CREATE INDEX idx_notion_entity_map_status
    ON notion_entity_map(status);
