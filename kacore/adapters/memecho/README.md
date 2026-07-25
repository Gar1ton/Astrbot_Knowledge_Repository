# kacore/adapters/memecho/ — MemoryEcho REST 适配层

## 职责

把 Artific 托管记忆服务 **MemoryEcho API**（`https://api.artific.social`，见
`docs.artific.social/MemoryEcho`）的 REST 端点翻译为项目内部可消费的 dict/结构：
隔离 HTTP 细节（aiohttp）、Bearer 鉴权（`as_...`）、超时与**降级**（`degraded`/`pipeline`）解析、
错误码到异常类型的映射。

分支 `Experiment-with-MemEcho-API` 新增，用于「MemEcho 召回」这一新检索方法。

## 边界（防腐层）

- **纯翻译**：只做 HTTP ↔ dict 映射，不夹带召回融合 / 写回 / 导入编排决策——那些属于
  `kacore/pipelines/memecho_recall.py`。
- **可测试缝**：`MemEchoClient` 接受可注入的 `transport`（默认 aiohttp），单测无需真实网络。
- **机密**：`api_key` 可为字符串或 `Callable[[], str]`（延迟从 secret_store/env 取值），本层不持久化密钥。

## 端点覆盖

| 方法 | MemoryEcho 端点 | 用途 |
|---|---|---|
| `list_vaults` / `get_vault` / `create_vault` | `GET/POST /api/v1/memory/vaults` | 记忆库管理 |
| `query_readonly` / `query` | `POST /api/v1/memory/query-readonly` · `/query` | 语义召回（只读 / 留痕） |
| `append_user_message` / `append_assistant_message` | `POST /api/v1/memory/append-*` | 写回记忆 |
| `import_file` | `POST /api/v1/memory/memories/import_file`（SSE） | 文件导入（解析 SSE 进度事件） |
| `list_files` | `GET /api/v1/memory/files` | 已导入文件列表 |
| `get_usage` | `GET /api/v1/dashboard/services/memory/usage` | 用量概览 |
| `probe` | list_vaults + usage | 连通性探针 |

## 异常层级

`MemEchoError`（基类，带 `status`）→ `MemEchoAuthError`(401/403) · `MemEchoQuotaError`(402) ·
`MemEchoNotFoundError`(404) · `MemEchoPayloadTooLargeError`(413)。
