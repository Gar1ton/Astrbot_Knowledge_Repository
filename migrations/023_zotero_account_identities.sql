-- Zotero 跨源（local SQLite / Web API）账号身份链接表。
--
-- 同一个 Zotero 账号在 local 与 server 两种 access_mode 下的 library_id 不同
-- （local 通常为 '1'，server 为数字 user_id），会导致同一条目/附件被同步两次、
-- 产生重复文档与重复集合。本表记录「哪些 (access_mode, library_id) 命名空间
-- 属于同一逻辑账号」，供跨源合并确认（confirm_zotero_account_merge）与后续
-- 同步移除逻辑（_apply_removals）识别、避免重新制造重复。

CREATE TABLE IF NOT EXISTS zotero_account_identities (
    namespace TEXT PRIMARY KEY,   -- '{access_mode}:{library_id}'，如 'local:1'
    account_key TEXT NOT NULL,    -- 同账号在多个命名空间下共享的逻辑标识
    library_id TEXT NOT NULL,
    access_mode TEXT NOT NULL,
    linked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_zotero_account_identities_account_key
    ON zotero_account_identities(account_key);
