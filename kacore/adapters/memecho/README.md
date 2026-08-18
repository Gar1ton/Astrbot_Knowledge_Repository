# kacore/adapters/memecho/ — MemoryEcho REST 适配层

## 职责

把 Artific 托管记忆服务 **MemoryEcho API**（`https://api.artific.social`，见
`docs.artific.social/MemoryEcho`）的 REST 端点翻译为项目内部可消费的 dict/结构：
隔离 HTTP 细节（aiohttp）、Bearer 鉴权（`as_...`）、超时与**降级**（`degraded`/`pipeline`）解析、
错误码到异常类型的映射。

分支 `Experiment-with-MemEcho-API` 新增，用于「MemEcho 召回」这一新检索方法。

## 边界（防腐层）

- **纯翻译**：只做 HTTP ↔ dict 映射，不夹带召回融合 / 写回 / 导入编排决策——那些属于
  `kacore/pipelines/memecho_recall.py`。面向 `KnowledgeRepositoryApi` 调用方的公开门面
  （key 管理 / 探针 / vault / 导入 / `ask()` 的 `memecho` 分支实现）在 `kacore/api_memecho.py`
  的 `MemEchoApiMixin`——与 `client.py`/`pipelines/memecho_recall.py` 一样是独立文件，方便
  这条分支未来与 `developer` 再次同步时冲突面小；`api.py` 里只留 `ask()` 的中央派发一行。
- **可测试缝**：`MemEchoClient` 接受可注入的 `transport`（默认 aiohttp），单测无需真实网络。
- **机密**：`api_key` 可为字符串或 `Callable[[], str]`（延迟从 secret_store/env 取值），本层不持久化密钥。

## 端点覆盖

| 方法 | MemoryEcho 端点 | 用途 |
|---|---|---|
| `list_vaults` / `get_vault` / `create_vault` | `GET/POST /api/v1/memory/vaults` | 记忆库管理 |
| `update_vault` | `PATCH /api/v1/memory/vaults/{id}` | 更新记忆库名称/描述 |
| `delete_vault` | `DELETE /api/v1/memory/vaults/{id}` | 软删除（移入回收站） |
| `list_vault_trash` / `restore_vault` / `purge_vault` | `GET/POST/DELETE /api/v1/memory/vaults/trash*` | 回收站管理 |
| `list_messages` | `GET /api/v1/memory/vaults/{id}/messages` | 记忆库内消息流 |
| `query_readonly` / `query` | `POST /api/v1/memory/query-readonly` · `/query` | 语义召回（只读 / 留痕） |
| `append_user_message` / `append_assistant_message` | `POST /api/v1/memory/append-*` | 写回记忆 |
| `import_file` | `POST /api/v1/memory/vaults/{vault_id}/import_file`（SSE） | 文件导入（解析 SSE 进度事件） |
| `list_files` / `get_file_content` | `GET /api/v1/memory/files` · `/files/content` | 已导入文件列表 / 原始内容 |
| `get_usage` | `GET /api/v1/dashboard/services/memory/usage` | 用量概览 |
| `probe` | list_vaults + usage | 连通性探针 |

> `import_file` 的路径在 MemoryEcho 文档 2026-07 版更新中从 `/api/v1/memory/memories/import_file`
> 改为 `/api/v1/memory/vaults/{vault_id}/import_file`（vault 现同时出现在路径与 body 的
> `library_id` 中）；本仓库已按新文档同步。
>
> `update_vault`/`delete_vault`/回收站三件套/`list_messages`/`get_file_content` 是本次文档同步
> 新增的纯翻译方法，**未接入**任何编排层（`pipelines/memecho_recall.py`）或产品面
> （`kacore/api_memecho.py` 门面 / web 路由 / 前端）——是否要在 UI 上暴露记忆库删除、回收站恢复
> 等操作，属于后续独立的功能决策。
>
> 文档新增的 `POST /api/v1/memory/chat`（MemEcho 代理 LLM Hub 对话，真正的增量 SSE 流式）尚未实现：
> 项目现有 `_ask_memecho`（见 `kacore/api_memecho.py`）已自带独立 LLM 合成逻辑，且该端点的流式契约
> 与 `import_file` 的「收全文本再解析」不同，需要新的 transport 契约，留待有实际需求时再做。

## 异常层级

`MemEchoError`（基类，带 `status`）→ `MemEchoAuthError`(401/403) · `MemEchoQuotaError`(402) ·
`MemEchoNotFoundError`(404) · `MemEchoPayloadTooLargeError`(413)。
