CREATE TABLE IF NOT EXISTS lightrag_index_status (
    doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    collection TEXT NOT NULL,
    status TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
