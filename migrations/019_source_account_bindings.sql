-- 019_source_account_bindings.sql
-- 外部同步源账号绑定：用于在 Zotero token 指向新账号时阻止静默混库。

CREATE TABLE IF NOT EXISTS source_account_bindings (
    source TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    account_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
