-- 014_chat_history_lock.sql
-- 锁定/固定聊天回答。locked 消息可在清空会话时保留。

ALTER TABLE chat_history ADD COLUMN locked INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_history ADD COLUMN locked_at TEXT;
ALTER TABLE chat_history ADD COLUMN updated_at TEXT;

CREATE INDEX IF NOT EXISTS idx_chat_history_conv_locked
    ON chat_history(conversation_id, locked);
