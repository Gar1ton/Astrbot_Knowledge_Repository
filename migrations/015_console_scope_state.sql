-- 015_console_scope_state.sql
-- 控制台右侧上下文选择状态；按 global/collection/document scope 持久化。

CREATE TABLE IF NOT EXISTS console_scope_state (
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    selected_collection TEXT NOT NULL DEFAULT '',
    selected_doc_id TEXT NOT NULL DEFAULT '',
    note_doc_id TEXT NOT NULL DEFAULT '',
    right_panel TEXT NOT NULL DEFAULT '',
    reading_mode TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_type, scope_key)
);
