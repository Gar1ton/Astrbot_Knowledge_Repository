-- 010_documents_artifacts.sql
-- 制品包模型：documents 表追加 Zotero/制品包列；新增 page_chunks 页面 provenance 表。
-- 每个 migration 仅应用一次（runner 按文件名去重），故 ALTER ... ADD COLUMN 安全。

PRAGMA foreign_keys = ON;

-- documents 追加列：library_id / zotero key / origin / read_only / 制品包相对路径 / converter
ALTER TABLE documents ADD COLUMN library_id TEXT NOT NULL DEFAULT 'LOCAL';
ALTER TABLE documents ADD COLUMN zotero_item_key TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN attachment_key TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN origin TEXT NOT NULL DEFAULT 'local';      -- zotero | local
ALTER TABLE documents ADD COLUMN read_only INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN zotero_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN markdown_rel_path TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN pages_rel_path TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN converter TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN converter_version TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_documents_origin ON documents(origin);
CREATE INDEX IF NOT EXISTS idx_documents_zotero_item ON documents(library_id, zotero_item_key);

-- 页面级 provenance：clean.md 中每页的字符偏移区间（写盘归一化后的 str 偏移）
CREATE TABLE IF NOT EXISTS page_chunks (
    document_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    markdown_start_char INTEGER NOT NULL,
    markdown_end_char INTEGER NOT NULL,
    PRIMARY KEY (document_id, page)
);

CREATE INDEX IF NOT EXISTS idx_page_chunks_doc ON page_chunks(document_id);
