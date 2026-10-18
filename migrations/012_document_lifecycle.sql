-- 012_document_lifecycle.sql
-- 文档生命态 + 末次同步时间：支撑 conservative 脱管(detached)语义与「修改时间」指示元数据。

PRAGMA foreign_keys = ON;

-- active | detached（conservative 脱管文档：移除 Milvus 但保留制品/LRAG，Zotero 侧恢复后可复活；strict_mirror 会硬删）
ALTER TABLE documents ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active';
-- 末次成功同步系统时间（ISO8601）；本地上传保持空
ALTER TABLE documents ADD COLUMN last_synced_at TEXT;

CREATE INDEX IF NOT EXISTS idx_documents_lifecycle ON documents(lifecycle_state);
