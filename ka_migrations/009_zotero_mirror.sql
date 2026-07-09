-- 009_zotero_mirror.sql
-- Zotero 逻辑镜像表（上游事实源的本地只读镜像；新 schema 幂等建表，无旧行迁移）。
-- 镜像 Zotero 的逻辑组织模型而非其内部 SQLite schema；每表保留 raw_zotero_json 原样备份。
-- 本地上传统一以合成 LOCAL 库 + origin='local' 表示。

PRAGMA foreign_keys = ON;

-- 1) Zotero 库（user / group / LOCAL 合成库）
CREATE TABLE IF NOT EXISTS zotero_libraries (
    library_id TEXT PRIMARY KEY,
    library_type TEXT NOT NULL,            -- user | group | LOCAL
    name TEXT NOT NULL DEFAULT '',
    raw_zotero_json TEXT NOT NULL DEFAULT '{}'
);

-- 2) Zotero 集合（树状；item 可属于多个集合）
CREATE TABLE IF NOT EXISTS zotero_collections (
    collection_key TEXT NOT NULL,
    library_id TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_collection_key TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'zotero', -- zotero | local
    raw_zotero_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (library_id, collection_key)
);

CREATE INDEX IF NOT EXISTS idx_zotero_collections_parent
    ON zotero_collections(library_id, parent_collection_key);

-- 3) 集合↔条目 多对多（Zotero 集合近似播放列表，非独占文件夹）
CREATE TABLE IF NOT EXISTS zotero_collection_items (
    library_id TEXT NOT NULL,
    collection_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    PRIMARY KEY (library_id, collection_key, item_key)
);

CREATE INDEX IF NOT EXISTS idx_zotero_collection_items_item
    ON zotero_collection_items(library_id, item_key);

-- 4) Zotero 条目（归一化引用字段 + raw JSON 保真）
CREATE TABLE IF NOT EXISTS zotero_items (
    item_key TEXT NOT NULL,
    library_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    creators TEXT NOT NULL DEFAULT '[]',   -- JSON 数组
    year TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    abstract TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'zotero',
    date_added TEXT,
    date_modified TEXT,
    raw_zotero_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (library_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_zotero_items_type ON zotero_items(item_type);

-- 5) Zotero 附件（PDF 等子条目；resolved_path 为本地绝对路径，md5 用于变更判定）
CREATE TABLE IF NOT EXISTS zotero_attachments (
    attachment_key TEXT NOT NULL,
    library_id TEXT NOT NULL,
    parent_item_key TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    resolved_path TEXT NOT NULL DEFAULT '',
    link_mode TEXT NOT NULL DEFAULT '',
    md5 TEXT NOT NULL DEFAULT '',
    raw_zotero_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (library_id, attachment_key)
);

CREATE INDEX IF NOT EXISTS idx_zotero_attachments_parent
    ON zotero_attachments(library_id, parent_item_key);

-- 6) 条目标签（type=0 手动 / 1 自动）
CREATE TABLE IF NOT EXISTS zotero_item_tags (
    library_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    tag TEXT NOT NULL,
    type INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'zotero',
    PRIMARY KEY (library_id, item_key, tag)
);

CREATE INDEX IF NOT EXISTS idx_zotero_item_tags_tag ON zotero_item_tags(library_id, tag);

-- 7) 条目间关系
CREATE TABLE IF NOT EXISTS zotero_relations (
    library_id TEXT NOT NULL,
    source_item_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_item_key TEXT NOT NULL,
    PRIMARY KEY (library_id, source_item_key, relation_type, target_item_key)
);
