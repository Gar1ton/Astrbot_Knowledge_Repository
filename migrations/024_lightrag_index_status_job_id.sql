-- 为 lightrag_index_status 补充 job_id：取消构建（cancel_build_job）需要按 job 精确
-- 清理「本次任务写入的索引状态」，不能牵连其他任务/其他构建轮次对同一文档的记录。
-- 可空、追加式；PK 仍为 doc_id（同一时刻一份文档只会被一个 job 主动索引）。

ALTER TABLE lightrag_index_status ADD COLUMN job_id TEXT;

CREATE INDEX IF NOT EXISTS idx_lightrag_index_status_job
    ON lightrag_index_status(job_id);
