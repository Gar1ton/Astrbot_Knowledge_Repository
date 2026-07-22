-- Codex 驱动的 LightRAG 自定义知识图谱任务账本。
--
-- 任务只保存本地文档切片与处理状态；实体/关系结果直接写入 LightRAG，
-- 不经过插件 LLM，也不把 Codex 响应持久化为第二份知识库。

CREATE TABLE IF NOT EXISTS codex_graph_tasks (
    task_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, doc_id, chunk_index),
    FOREIGN KEY(job_id) REFERENCES graph_build_jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_codex_graph_tasks_job_status
    ON codex_graph_tasks(job_id, status, chunk_index);

CREATE INDEX IF NOT EXISTS idx_codex_graph_tasks_doc
    ON codex_graph_tasks(job_id, doc_id, chunk_index);
