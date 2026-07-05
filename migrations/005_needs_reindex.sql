-- 005_needs_reindex.sql
-- 为 documents 表添加 needs_reindex 字段，支持延迟索引模式（v0.15.0）
-- 存量文档默认 0（已索引），不影响现有数据。

ALTER TABLE documents ADD COLUMN needs_reindex INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_documents_needs_reindex ON documents(needs_reindex);
