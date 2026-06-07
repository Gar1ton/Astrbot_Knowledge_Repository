-- 011_collection_origin.sql
-- collections 追加来源标记：Zotero 同步来的集合只读，本地手动创建的可改可删。

PRAGMA foreign_keys = ON;

ALTER TABLE collections ADD COLUMN origin TEXT NOT NULL DEFAULT 'local';            -- zotero | local
ALTER TABLE collections ADD COLUMN zotero_collection_key TEXT NOT NULL DEFAULT '';
ALTER TABLE collections ADD COLUMN read_only INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_collections_origin ON collections(origin);
