-- 018_unified_collection_tree.sql
-- 统一多归属集合树：把扁平的 collections 升级为「树形 + 稳定 key」，
-- 并用 document_collections 多对多表替代 documents.collection 单值归属（旧列保留作冗余 primary）。
--
-- 设计要点：
--   - coll_key 是新的「稳定逻辑主键」：local 集合 = 'L' + 随机 hex；
--     zotero 集合 = library_id + ':' + zotero_collection_key（由 Zotero 同步逻辑维护）。
--   - name 从全局唯一主键降级为「同 parent 下唯一」的展示名（支持 Zotero 同名子集合）。
--     这要求把 collections 主键改为 coll_key，并去掉 documents.collection 对 collections(name)
--     的外键（否则 name 非唯一会触发 foreign key mismatch）。SQLite 无法 ALTER 改主键/去约束，
--     故对两表做标准「建新表→拷数据→换名」重建。
--   - documents.collection 保留为普通列（冗余 primary，给 R2 key / Notion select / milvus tag 兜底），
--     归属真相源改为 document_collections 多对多（按 coll_key）。
--   - 重建期间关闭外键约束；完成后恢复。子表（chunks/page_chunks/... ON DELETE CASCADE）
--     按表名引用 documents，重建后自动重绑、数据不丢。
--   - 回填阶段对现有全部行统一发放唯一 'L' key（现有 zotero 行的 zotero_collection_key 多为空，
--     无法确定性派生）；zotero 部分的正确 coll_key/parent_key/library_id 由下次 Zotero 同步
--     全量重建修正，故此处临时 L key 不影响最终一致性。

PRAGMA foreign_keys = OFF;

-- 1) collections 追加树形字段并回填 coll_key（randomblob 逐行求值，保证唯一）
ALTER TABLE collections ADD COLUMN coll_key TEXT NOT NULL DEFAULT '';
ALTER TABLE collections ADD COLUMN parent_key TEXT NOT NULL DEFAULT '';
ALTER TABLE collections ADD COLUMN library_id TEXT NOT NULL DEFAULT 'LOCAL';
UPDATE collections SET coll_key = 'L' || lower(hex(randomblob(16))) WHERE coll_key = '';

-- 2) 重建 collections：coll_key 作主键，name 非唯一
CREATE TABLE collections_new (
    coll_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'local',
    zotero_collection_key TEXT NOT NULL DEFAULT '',
    read_only INTEGER NOT NULL DEFAULT 0,
    parent_key TEXT NOT NULL DEFAULT '',
    library_id TEXT NOT NULL DEFAULT 'LOCAL'
);
INSERT INTO collections_new
    (coll_key, name, description, created_at, origin, zotero_collection_key,
     read_only, parent_key, library_id)
SELECT coll_key, name, description, created_at, origin, zotero_collection_key,
       read_only, parent_key, library_id
FROM collections;
DROP TABLE collections;
ALTER TABLE collections_new RENAME TO collections;

CREATE INDEX idx_collections_origin ON collections(origin);
CREATE INDEX idx_collections_parent ON collections(parent_key);
CREATE INDEX idx_collections_name ON collections(name);

-- 3) 重建 documents：去掉 collection 对 collections(name) 的外键（保留为普通冗余 primary 列）
CREATE TABLE documents_new (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    collection TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    needs_reindex INTEGER NOT NULL DEFAULT 0,
    library_id TEXT NOT NULL DEFAULT 'LOCAL',
    zotero_item_key TEXT NOT NULL DEFAULT '',
    attachment_key TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'local',
    read_only INTEGER NOT NULL DEFAULT 0,
    zotero_version INTEGER NOT NULL DEFAULT 0,
    markdown_rel_path TEXT NOT NULL DEFAULT '',
    pages_rel_path TEXT NOT NULL DEFAULT '',
    converter TEXT NOT NULL DEFAULT '',
    converter_version TEXT NOT NULL DEFAULT '',
    lifecycle_state TEXT NOT NULL DEFAULT 'active',
    last_synced_at TEXT,
    local_meta TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO documents_new
    (doc_id, title, file_path, content_type, size_bytes, content_hash, collection, tags,
     created_at, updated_at, needs_reindex, library_id, zotero_item_key, attachment_key,
     origin, read_only, zotero_version, markdown_rel_path, pages_rel_path,
     converter, converter_version, lifecycle_state, last_synced_at, local_meta)
SELECT
    doc_id, title, file_path, content_type, size_bytes, content_hash, collection, tags,
    created_at, updated_at, needs_reindex, library_id, zotero_item_key, attachment_key,
    origin, read_only, zotero_version, markdown_rel_path, pages_rel_path,
    converter, converter_version, lifecycle_state, last_synced_at, local_meta
FROM documents;
DROP TABLE documents;
ALTER TABLE documents_new RENAME TO documents;

CREATE INDEX idx_documents_collection ON documents(collection);
CREATE INDEX idx_documents_needs_reindex ON documents(needs_reindex);
CREATE INDEX idx_documents_origin ON documents(origin);
CREATE INDEX idx_documents_zotero_item ON documents(library_id, zotero_item_key);
CREATE INDEX idx_documents_lifecycle ON documents(lifecycle_state);

-- 4) 重建 scoped_notes：去掉 collection_name 对 collections(name) 的外键（name 已非唯一）。
--    保留 doc_id 对 documents 的外键（重建后自动重绑）与 scope CHECK 约束。
CREATE TABLE scoped_notes_new (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('document', 'collection')),
    scope_key TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    note_html TEXT NOT NULL DEFAULT '',
    doc_id TEXT REFERENCES documents(doc_id) ON DELETE CASCADE,
    collection_name TEXT,
    library_id TEXT NOT NULL DEFAULT 'LOCAL',
    parent_item_key TEXT NOT NULL DEFAULT '',
    parent_attachment_key TEXT NOT NULL DEFAULT '',
    zotero_note_key TEXT NOT NULL DEFAULT '',
    zotero_version INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',
    collections TEXT NOT NULL DEFAULT '[]',
    relations TEXT NOT NULL DEFAULT '{}',
    linked INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    chat_conversation_id TEXT NOT NULL DEFAULT '',
    chat_message_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_zotero_json TEXT NOT NULL DEFAULT '{}',
    CHECK (
        (scope_type = 'document' AND doc_id IS NOT NULL AND collection_name IS NULL)
        OR
        (scope_type = 'collection' AND collection_name IS NOT NULL AND doc_id IS NULL)
    )
);
INSERT INTO scoped_notes_new
    (id, scope_type, scope_key, content, note_html, doc_id, collection_name, library_id,
     parent_item_key, parent_attachment_key, zotero_note_key, zotero_version, tags,
     collections, relations, linked, source, chat_conversation_id, chat_message_id,
     created_at, updated_at, raw_zotero_json)
SELECT
    id, scope_type, scope_key, content, note_html, doc_id, collection_name, library_id,
    parent_item_key, parent_attachment_key, zotero_note_key, zotero_version, tags,
    collections, relations, linked, source, chat_conversation_id, chat_message_id,
    created_at, updated_at, raw_zotero_json
FROM scoped_notes;
DROP TABLE scoped_notes;
ALTER TABLE scoped_notes_new RENAME TO scoped_notes;

CREATE INDEX idx_scoped_notes_scope ON scoped_notes(scope_type, scope_key, updated_at);
CREATE INDEX idx_scoped_notes_doc ON scoped_notes(doc_id);
CREATE INDEX idx_scoped_notes_collection ON scoped_notes(collection_name);
CREATE INDEX idx_scoped_notes_zotero_key ON scoped_notes(library_id, zotero_note_key);

-- 5) 多对多归属表（替代 documents.collection 单值；旧列保留作冗余 primary）
CREATE TABLE document_collections (
    doc_id    TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    coll_key  TEXT NOT NULL,
    PRIMARY KEY (doc_id, coll_key)
);
CREATE INDEX idx_doc_collections_coll ON document_collections(coll_key);

-- 7) 数据迁移：把现有单值归属灌入多对多表（此刻 name 仍唯一，JOIN 无歧义）
INSERT OR IGNORE INTO document_collections (doc_id, coll_key)
SELECT d.doc_id, c.coll_key
FROM documents d
JOIN collections c ON d.collection = c.name;

PRAGMA foreign_keys = ON;
