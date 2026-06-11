# 知识库控制台 · 前端重构后端改动报告

> 版本：v1（前端重构方案）· 编制者：设计 Agent · 状态：待后端确认
>
> 本报告对应一次**前端优先**的重构：界面从「左栏导航 + 多路由页面」改为
> **三段式集成面板**（File / Documents / Chat 常驻）+ Note 面板 + 三个全屏弹出面板
> （Setting / AstrBot / WorkFlow）。本文件**只**记录：①新设计用到、但后端尚不存在的能力与端口；
> ②已有端口需要的语义/行为调整；③不需要后端改动、纯前端即可完成的项（备查）。
>
> 现有端口契约详见原始 `deliverables/design-spec.md §6`。本报告是其**增量**。

---

## 0. 摘要（给后端负责人）

| 优先级 | 能力 | 现状 | 需要的后端动作 |
|---|---|---|---|
| **P0** | 文档原件下载 / PDF 阅读视图取流 | 无显式端口 | 新增 `GET /api/documents/{id}/raw` |
| **P0** | Note：本地笔记（新建 / 编辑 / 删除 / 关联） | 完全没有 | 新增 `notes` 资源族（见 §2） |
| **P0** | Note：Zotero annotations 读取 | 同步可带 annotations，但无读取端口 | 新增 `GET /api/documents/{id}/annotations` |
| **P0** | Chat「锁定回答」持久化 | chat history 存在，无 pin 标记 | 扩展 chat history（见 §3） |
| **P1** | Chat「Add to Linked Notes」 | 无 | 复用 §2 notes（带 `origin:"chat"`） |
| **P1** | 单文档 / 单集合 作为问答范围 | `/api/ask` 已支持 `collection` | 增加 `doc_id` 作用域参数（见 §4） |
| **P1** | LightRAG 与 Sync **构建隔离** | 逻辑上未强制隔离 | 增加构建作用域与触发隔离约束（见 §5） |
| **P1** | 引用 chunk → 定位原文 | `kb/chunk-context` 已有 | 返回 `page` / `char_offset` 以便滚动定位（见 §6） |
| **P2** | Zotero 同步 Push（弹窗 Push/Pull） | 仅 Pull | 评估是否需要 Push（见 §7） |
| **P2** | 登出 | 未见 `/api/logout` | 确认登出端口（沿用 design-spec §6.99） |

---

## 1. 文档原件下载 / 阅读视图取流（P0）

**场景**：Documents 面板「列表 → 阅读视图」中支持 `md / PDF` 切换；PDF 模式需要取到原件流；Note 面板与批量操作也有「下载原件」。

**新增端口**

```
GET /api/documents/{id}/raw
  → 200, 二进制流 (application/pdf | text/markdown | text/plain)
     Header: Content-Disposition: inline; filename="..."
  → 404 若文档不存在
```

- 前端 `md` 模式渲染清洗后的 Markdown（可复用 ingest 阶段已生成的清洗文本，若有 `GET /api/documents/{id}/markdown` 更佳；否则前端用 chunks 拼装，当前原型即如此降级）。
- 与 design-spec §6.99「下载待确认」一致，本报告将其升级为 **P0 必须**。

---

## 2. Note 子系统（P0 · 全新）

设计将 Note 提升为左侧常驻面板（打开某文档时替换 File 面板）。数据 = **Zotero 同步的 annotations（只读）** + **本地笔记（可写）**。后端目前两者都没有读取/写入端口。

### 2.1 Zotero annotations（只读）

```
GET /api/documents/{id}/annotations
  → 200 [{ id, color, page, text, comment, created_at }]
     color ∈ {purple,yellow,green,red,blue}（映射 Zotero 高亮色）
     仅对 origin="zotero" 的文档返回；本地文档返回 []
```

- 数据来源：Zotero 单向 Pull 同步时**一并镜像 annotations**（当前同步只镜像条目/附件，需扩展镜像范围）。
- 只读：注释在 Zotero 中编辑后经再次同步更新；前端不写回。

### 2.2 本地笔记（可写 · 全新资源）

```
GET    /api/documents/{id}/notes
  → 200 [{ note_id, body, origin, linked_chunk_id?, created_at, updated_at }]
         origin ∈ {"manual","chat"}

POST   /api/documents/{id}/notes
  body { body: string, origin?: "manual"|"chat", linked_chunk_id?: string }
  → 201 { note_id, ... }

PATCH  /api/notes/{note_id}
  body { body?: string }
  → 200 { ... }

DELETE /api/notes/{note_id}
  → 200 { status:"ok" }
```

**建议存储**：新增迁移 `013_notes.sql`

```sql
CREATE TABLE notes (
  note_id        TEXT PRIMARY KEY,
  doc_id         TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  body           TEXT NOT NULL,
  origin         TEXT NOT NULL DEFAULT 'manual',   -- manual | chat
  linked_chunk_id TEXT,                              -- 来自 chat 引用时回链
  conversation_id TEXT,                              -- chat 来源会话
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX idx_notes_doc ON notes(doc_id);
```

> 笔记随文档删除级联清理（与现有 `DELETE /api/documents/{id}` 同时清 LightRAG 索引的行为对齐）。

---

## 3. Chat「锁定回答」持久化（P0）

**场景**：Chat 面板每条 assistant 回答可「锁定」；锁定的回答**持续保留**，清空对话（`DELETE /api/chat/history`）也不删除。

**改动**：扩展现有 chat history（design-spec §6 未列，但前端实现已有 `/api/chat/history`）。

```
PATCH /api/chat/messages/{message_id}
  body { pinned: boolean }
  → 200 { message_id, pinned }

DELETE /api/chat/history?conversation_id=...
  行为变更：仅删除 pinned=false 的消息；pinned=true 保留
```

**存储**：`007_chat_history.sql` 增列

```sql
ALTER TABLE chat_messages ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
```

---

## 4. 问答作用域：单文档 / 单集合（P1）

**场景**（用户明确）：
- 若只选中**一篇 PDF** → 以该文章为唯一知识库背景；
- 若在**某 collection** 界面 → 以该 collection 内容为背景。

**改动**：`POST /api/ask` 增加可选 `doc_id` 作用域（与既有 `collection` 互斥优先）。

```jsonc
// POST /api/ask  (在 design-spec §7 基础上增量)
{
  "question": "…",
  "collection": "RAG & Retrieval | null",
  "doc_id": "d-react | null",   // ← 新增：单文档作用域，优先于 collection
  "top_k": 5,
  "conversation_id": "…"
}
```

- 当 `doc_id` 非空：检索仅在该文档的 chunks 内进行；`sources` 全部来自该文档。
- 返回的 `sources[].doc_id / chunk_id / page` 用于前端「点击引用 → 在 Documents 打开并滚动高亮」。

---

## 5. LightRAG 构建与 Sync 的隔离（P1 · 重要约束）

**场景**（用户明确）：`File` 树的 `LightRAG Collection` 分区，是「已构建过图谱索引的集合」。其同步逻辑必须与 Zotero/Local 的 Sync **隔离**——**Sync 的变化不得自动触发或影响 LightRAG 索引**，以保证图谱构建成本不失控。

**改动 / 约束**：

1. **触发隔离**：上传、Zotero Pull、集合变更等 Sync 事件**不得**调用 LightRAG 构建。构建只能由前端 `LightRAG Collection` 分区的「构建 / 增量」按钮显式触发（已与 design-spec §5.4 的「确认成本估算后手动触发」一致，此处强调跨 Sync 隔离）。
2. **作用域快照**：构建作业应记录其**输入文档快照**（doc_id 列表 + 内容指纹），后续 Sync 改动这些文档时：
   - 不自动重建；
   - 在 `GET /api/graph` 的集合状态里标记 `stale: true` + `stale_doc_ids: [...]`，由前端在 `LightRAG Collection` 行上提示「N 篇已变更，可增量更新」。
3. **构建进度**端口（已存在于 design-spec / api.ts，确认沿用）：
   ```
   POST /api/graph/build            → { job_id, status }   （成本隔离：仅此处触发）
   GET  /api/graph/build/{job_id}   → { status, processed_chunks, total_chunks, stage, ... }
   GET  /api/graph/build/active     → { job: {...}|null }
   ```
   前端把进度条渲染在 `File / LightRAG Collection` 行内（已实现）。`stage` 建议返回中文/枚举：`实体抽取 | 关系合并 | 向量化`。

**新增返回字段**（`GET /api/graph?collection=`）：

```jsonc
{ "status":"ready", "collection":"RAG & Retrieval",
  "entities": 142, "relations": 318,
  "stale": false, "stale_doc_ids": [],
  "built_doc_snapshot": ["d-react","d-lightrag", "..."] }
```

---

## 6. 引用 chunk → 原文定位（P1）

**场景**：Chat 点击 `[n]` 角标 → 中间面板切到该文档阅读视图，并**滚动到 chunk 原文位置高亮**。

**改动**：`sources[]` 与 `kb/chunk-context` 返回**定位信息**。

```jsonc
// /api/ask 的 sources[] 与 /api/kb/search 的 chunk 增量字段
{ "n":1, "doc_id":"d-react", "chunk_id":"react-3",
  "ordinal":3, "page":1, "char_start":1280, "char_end":1820,
  "text":"…", "rrf_score":0.0331 }
```

- 前端用 `chunk_id` 在阅读视图定位 DOM 锚点滚动（当前原型即按 `chunk_id` 锚点实现）；`page` / `char_*` 供 PDF 模式精确定位。

---

## 7. Zotero 同步 Push（P2 · 待确认）

设计草图标注 `Zotero 同步（弹窗选择 Push / Pull）`。当前后端**仅** `POST /api/sync/zotero/pull`（单向只读镜像，且 annotations 只读）。

**待确认**：是否需要 **Push**（把本地笔记/标签写回 Zotero）。考虑到 §2.1 注释只读策略，建议：
- 默认**仅 Pull**；弹窗的「Push」先置灰并标注「即将上线」，避免破坏只读保证；
- 若确需 Push，需新增 `POST /api/sync/zotero/push` 并明确冲突解决策略（本报告暂不展开）。

---

## 8. 不需要后端改动（纯前端，备查）

- 三段式面板布局、Note 替换 File 面板、面包屑返回、md/PDF 切换、面板开合。
- 三个全屏弹出面板（Setting / AstrBot / WorkFlow）的外壳与交互；其中数据仍走既有 `config/effective`、`quota`、`graph` 等端口。
- 全局强调色 / 主题 / 色系切换（CSS 变量，前端 + localStorage 持久化）。
- LightRAG「高级模式」全屏配色映射（纯前端 `data-mode` 切换）。
- 终端日志面板暂置于 Setting（沿用既有 `log_capture` / 日志端口）。
- WorkFlow 复用既有 Flow 数据（`capabilities` / `config/effective`），仅节点美术重绘。

---

## 9. 迁移与端口清单（速查）

```
# 新增端口
GET    /api/documents/{id}/raw                    P0  原件取流 / 下载
GET    /api/documents/{id}/markdown               P0  清洗后 Markdown（可选，优于前端拼装）
GET    /api/documents/{id}/annotations            P0  Zotero 注释（只读）
GET    /api/documents/{id}/notes                  P0  本地笔记列表
POST   /api/documents/{id}/notes                  P0  新建本地笔记
PATCH  /api/notes/{note_id}                        P0  编辑笔记
DELETE /api/notes/{note_id}                        P0  删除笔记
PATCH  /api/chat/messages/{message_id}             P0  锁定 / 取消锁定回答
POST   /api/sync/zotero/push                       P2  （待确认）写回 Zotero

# 行为 / 字段调整
POST   /api/ask                 + doc_id 作用域字段；sources[] + page/char_*    P1
DELETE /api/chat/history        仅删 pinned=false                              P0
GET    /api/graph               + stale / stale_doc_ids / built_doc_snapshot   P1
GET    /api/kb/search           chunk + page/char_start/char_end               P1
POST   /api/graph/build         强制与 Sync 隔离（仅显式触发）                  P1

# 新增迁移
013_notes.sql                   notes 表
014_chat_pin.sql                chat_messages ADD COLUMN pinned
015_graph_snapshot.sql          graph_build_jobs 记录 built_doc_snapshot / stale
```

---

> 备注：以上端口形状均为**前端视角的建议契约**，落地前请以后端 `core/api` 实际实现复核字段名；预留功能继续沿用 `{reserved:true, available_in:"vX"}` 降级约定。
