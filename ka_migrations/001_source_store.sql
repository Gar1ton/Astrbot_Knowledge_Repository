-- 001_source_store.sql
-- 集合、源文档和文档分块的初始表结构

PRAGMA foreign_keys = ON;

-- 1) 集合表（对应 AstrBot 知识库分类）
CREATE TABLE IF NOT EXISTS collections (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- 2) 源文档表（原件，如 PDF）
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    collection TEXT NOT NULL REFERENCES collections(name) ON DELETE RESTRICT,
    tags TEXT NOT NULL DEFAULT '[]', -- JSON 格式的标签数组
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);

-- 3) 文档分块表（切切分后的文本块，供检索与图谱使用）
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_ordinal ON chunks(doc_id, ordinal);
