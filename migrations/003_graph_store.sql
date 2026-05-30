-- 003_graph_store.sql
-- 知识图谱（LightRAG 属性图）的表结构

PRAGMA foreign_keys = ON;

-- 1) 图谱实体表（存放节点，支持 Embedding 向量）
CREATE TABLE IF NOT EXISTS graph_entities (
    entity_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_chunk_ids TEXT NOT NULL DEFAULT '[]', -- JSON 格式的 chunk_id 数组
    degree INTEGER NOT NULL DEFAULT 0,
    embedding BLOB                               -- 存储浮点数向量二进制，供高层检索使用
);

CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(name);
CREATE INDEX IF NOT EXISTS idx_graph_entities_type ON graph_entities(entity_type);

-- 2) 图谱关系表（存放有向边 src_entity_id -> dst_entity_id）
CREATE TABLE IF NOT EXISTS graph_relations (
    relation_id TEXT PRIMARY KEY,
    src_entity_id TEXT NOT NULL REFERENCES graph_entities(entity_id) ON DELETE CASCADE,
    dst_entity_id TEXT NOT NULL REFERENCES graph_entities(entity_id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 1.0,
    source_chunk_ids TEXT NOT NULL DEFAULT '[]'  -- JSON 格式的 chunk_id 数组
);

CREATE INDEX IF NOT EXISTS idx_graph_relations_src ON graph_relations(src_entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_relations_dst ON graph_relations(dst_entity_id);

-- 3) 知识分块增量状态追踪表
CREATE TABLE IF NOT EXISTS graph_chunk_status (
    chunk_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);
