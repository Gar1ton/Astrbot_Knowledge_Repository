-- 013_scoped_notes.sql
-- 文档/集合作用域笔记。本地字段对齐 Zotero note，便于后续接入 Zotero 写回。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scoped_notes (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('document', 'collection')),
    scope_key TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    note_html TEXT NOT NULL DEFAULT '',
    doc_id TEXT REFERENCES documents(doc_id) ON DELETE CASCADE,
    collection_name TEXT REFERENCES collections(name) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_scoped_notes_scope
    ON scoped_notes(scope_type, scope_key, updated_at);

CREATE INDEX IF NOT EXISTS idx_scoped_notes_doc
    ON scoped_notes(doc_id);

CREATE INDEX IF NOT EXISTS idx_scoped_notes_collection
    ON scoped_notes(collection_name);

CREATE INDEX IF NOT EXISTS idx_scoped_notes_zotero_key
    ON scoped_notes(library_id, zotero_note_key);
