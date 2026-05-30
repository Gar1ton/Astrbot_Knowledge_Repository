# TODO

> 本文件记录项目的开发计划、进行中的任务与待处理事项。
> **所有参与者（含 AI Agent）在读写本文件时必须遵守下方规范。** 这是「先更新 TODO 再动代码」闭环的载体。

## TODO 规范（写入指南）

### 状态标记

| 标记 | 含义 |
|------|------|
| `[x]` | 已完成（代码已落地**且相关测试已过**，不是「我以为写完了」） |
| `[ ]` | 待实现 |
| `🚧` | 进行中（当前 session 正在执行的条目） |
| `❌` | 明确不做（已决策 defer/放弃，**保留**不删，注明原因） |
| `✅` | 整体完成（用于小节/计划标题） |
| `💬` | 待讨论（Backlog 中未确认优先级，执行前须先讨论） |

### 版本号规范

- 每个计划 section 的标题：`## vX.Y.Z 计划名称 (状态)`，例如 `## v0.3.0 Persistence layer (in progress)`。
- 状态用英文：`planning` / `in progress` / `completed`。
- 版本号来自 `metadata.yaml`；计划完成后把标题末尾改为 `(completed)`。

### 新建计划规范

1. 在 **💬 待讨论 Backlog** 中找到或新增对应条目。
2. 在本文件顶部（Backlog 之后）新建版本 section。
3. section 内**按固定顺序**组织三个子块：
   - `### User constraints / 约束` — 用户明确要求的限制。
   - `### Technical implementation path` — 按 **Phase** 划分，每条前缀 `[ ]` / `[x]`，每个 Phase 说明动作 + 技术理由。
   - `### Verification` — 验证命令与结果，格式：`命令` → `结果`。
4. 完成后：把 Backlog 中对应条目移除或标 `[x]`；section 标题改为 `(completed)`。

### Agent 专项提示

- **先更新 TODO，再动代码**：每轮工作开始前先在本文件勾 `🚧`/`[x]` 或追加子项，再改源码。
- **测试通过后再标完成**：`[x]` 代表代码已落地且相关测试已过。
- **Deferred 项不删除**：推迟的条目保留在 Backlog，注明推迟版本与原因。
- **语言约定**：验证命令与代码标识符用英文；设计讨论与中文注释保持原语言。
- **不改 Completed 计划的内部细节**：已完成 Phase 的技术记录用于历史查阅，除修正错误外不得改动。

---

<!-- ↓↓↓ 版本计划区（最新在上，Backlog 之上）↓↓↓ -->

## v0.7.0 图谱可视化 + 检索预览进阶 (planning)

### User constraints / 约束

- 前端进阶：依赖 v0.5.0 独立 Web 控制台与 v0.6.0 图谱后端，把图谱与召回过程可视化。

### Technical implementation path

- [ ] **Phase 1** — 知识图谱可视化面板（实体/关系交互图，点击节点查看 source chunk）。
- [ ] **Phase 2** — 图谱查询前端（dual-level 召回 + RRF 融合路径可视化）。
- [ ] **Phase 3** — 检索预览增强：KB 向量召回 vs 图谱召回对比视图（调参用）。

### Verification

- 打开图谱页 → 渲染实体/关系；点节点显示来源
- 输入 query → 图示融合召回路径

---

## v0.6.0 LightRAG 知识图谱 (in progress)

### User constraints / 约束

- 用 LightRAG 增量式，规避 GraphRAG 高 LLM 成本（增量 ≈ $0.15 vs GraphRAG $4–7）。
- 仅对内容哈希变化的 chunk 抽取；实体嵌入复用 KB 既有 bge-m3；不生成社区报告。

### Technical implementation path

- [x] **Phase 1** — `repository/graph_store/base.py` ABC（实体/关系 upsert、邻域查询、契约 docstring）。
- [x] **Phase 2** — `graph_store/sqlite.py`（实体表+关系表+实体嵌入表）+ `memory.py`；`migrations/003_graph_store.sql`。
- [x] **Phase 3** — `pipelines/graph_build_pipeline.py`：变化 chunk → LLM 抽取 → 嵌入相似度归并 → upsert（增量）。
- [x] **Phase 4** — 混合查询：向量召回 + 图邻域扩展 + RRF 融合（对齐 AstrBot rrf_k）。
- 🚧 **Phase 5** — 命令 `/kr graph build`、`/kr graph query <q>`（薄壳一行委派）。
- [ ] **Phase 6** — 领域本体预设与自定义引擎（Dynamic Ontology Preset & Customization Engine）：支持在 `GraphSyncConfig` 配置自定义 `entity_types` 列表，动态注入 LLM 抽取 Prompt 系统提示词并实现全链路类型过滤召回。

### Verification

- `python -m pytest tests/backend/test_graph_store.py` → 全绿
- `/kr graph build` 仅处理变化 chunk；`/kr graph query` 返回融合结果

---

## v0.5.0 独立 Web 控制台 MVP (completed)

### User constraints / 约束

- 独立 Web server + 独立端口（参考 Moirai 2657 模式），自带登录鉴权；不挂 AstrBot dashboard。
- 覆盖用户端到端流程：上传 / 管理 / 分类 / 同步备份 / 配额仪表盘（先前端 MVP，后图谱）。
- **提前搭建**（用户要求）：前端先对接现有内存实现（`memory.py`）并播种示例数据预览，真实后端（v0.3.0/v0.4.0）就绪后只换组合根注入，前端不改。
- 零构建：前端用单页 HTML + 原生 JS（不引 npm），后端 `aiohttp`，确保「一键启动」。

### Technical implementation path

- [x] **Phase 1** — `web/server.py` 独立 server + 登录鉴权中间件 + `core/api.py` 门面补全（create_collection/register_document/delete/list_quota）。
- [x] **Phase 2** — 前端单页（`web/frontend/index.html`）：上传 + 文档列表/管理（删/改集合/改标签）。
- [x] **Phase 3** — 分类界面：集合 collection 与标签 tags 的手动 CRUD。
- [x] **Phase 4** — 配额仪表盘（R2 用量/10GB、Notion 用量的可视化与阈值警告）。
- [x] **Phase 5** — 一键调试启动脚本 `tests/run_webui.py`（播种内存数据）+ `tools/sync_frontend.py`（frontend→pages）。
- [x] **Phase 5b** — **全量预留接口**：core/api 7 个方法桩 + web 7 条路由（501+available_in）+ 前端 同步/备份、知识图谱 两页入口；后续接后端前端零改。
- [x] **Phase 5c** — 离线模拟预览模式：支持 file:// 协议与 ?mock 参数下免密登录并使用前端全数据仿真模拟。
- [x] **Phase 6**（待 v0.3.0/v0.4.0/v0.6.0/v0.7.0）— 把预留端口逐个接真实后端：组合根注入 sqlite/R2/Notion/graph 实现，替换 NotImplementedError。

### Verification

- `python tests/run_webui.py --no-auth` → 启动独立端口；浏览器见 文档/分类/同步备份/检索/图谱/配额 六区
- `python -m pytest tests/backend` → 61 passed（含 web 路由 + 8 预留端口 501 参数化）
- live smoke：index 200；`/api/*` 正常；预留端口回 `{"status":"reserved","available_in":"vX"}`
- `python tools/sync_frontend.py` → frontend 复制到 pages/
- 注：工具链在 `/usr/local/bin/python3`

---

## v0.4.0 AstrBot KB 读取 + Notion 单向镜像 (completed)

### User constraints / 约束

- 检索复用 AstrBot 默认 KB（FAISS+FTS5+RRF），不重造；Notion 单向镜像到用户提供的 Database，每文档一页。
- Notion 免费版上传上限 5MiB、限流 3 req/s：大文件改链接到 R2，超限给出耗时/额度警告。

### Technical implementation path

- [x] **Phase 1** — `repository/kb_reader/base.py` ABC + `adapters/astrbot_kb.py`（从 context 取 KB 句柄、对象↔domain 翻译）。
- [x] **Phase 2** — `kb_reader/astrbot.py` + `memory.py`：读集合/文档/分块。
- [x] **Phase 3** — `repository/sync_targets/notion.py` + `adapters/notion_mcp.py`：经 notion MCP 单向镜像（含 5MiB/限流处理）。
- [x] **Phase 4** — 命令 `/kr sync notion`、`/kr sync status`。

### Verification

- `python -m pytest tests/backend/test_notion_target.py`（MCP 桩）→ 全绿
- `/kr sync notion` → Database 出现文档页；>5MiB PDF 显示「改用 R2 链接」+ 限流提示

---

## v0.3.0 PDF 源库 + 分类/集合 + R2 备份 + 额度警告 (completed)

### User constraints / 约束

- 以 PDF 等原件为中心：不做 PDF→md 的 LLM 转换；文本抽取用本地 PyMuPDF（无 LLM），OCR/LLM 为可选且警告。
- 分类两级：集合 collection（=AstrBot 多知识库）+ 标签 tags；先手动，自动打标签留 ABC 口（默认关，见 Backlog 可优化项）。
- R2 free 10GB：接近 80% 或将超时硬警告并要求确认。凭据按「Cloudflare R2 图床配置」字段。

### Technical implementation path

- [x] **Phase 1** — `repository/source_store/{base.py,sqlite.py,memory.py}`（含 collection/tags 字段）+ `migrations/001_source_store.sql`、`002_sync_state.sql`。
- [x] **Phase 2** — `managers/ingest_manager.py`：登记原件 + PyMuPDF 抽取（无 LLM）+ 内容哈希 + 入集合/标签。
- [x] **Phase 3** — `managers/category_manager.py`：collection 与 tags 手动 CRUD；预留自动打标签 ABC 口（默认关）。
- [x] **Phase 4** — `repository/sync_targets/r2.py`（S3 兼容 API：原件+manifest+kb.db 快照，哈希增量，key 前缀=collection）。
- [x] **Phase 5** — `managers/quota_manager.py` + `pipelines/sync_pipeline.py`：push 前额度预检 + R2 10GB gap 警告。
- [x] **Phase 6** — 命令 `/kr add`、`/kr sync r2`、`/kr quota`、`/kr collection`、`/kr tag` + 组合根注册周期备份任务。

### Verification

- `python -m pytest` -> 全绿 (89 passed)
- `ruff check .` -> All checks passed
- `/kr add sample.pdf --collection X --tag a`（无 LLM）→ `/kr sync r2` → bucket 出现 `X/` 原件+manifest → `/kr quota` 显示用量/10GB 及阈值警告

---

## v0.2.0 框架填空 + 端口骨架 (completed)

### User constraints / 约束

- 遵循 `ARCHITECTURE.md §8` 新增子系统清单与 `CONVENTIONS.md` 红线；机密走 env/secret 不入库。
- 本版承接 v0.1.0 的「填空 + 首个子系统」，落地 4 个稳定 ABC 端口 + `core/api.py` 业务门面骨架（为独立前端铺路）。

### Technical implementation path

- [x] **Phase 1** — 填 `metadata.yaml`(astrbot_plugin_knowledge_repository)、`_conf_schema.json`(source_store/R2/Notion/Web/Graph 配置)、`pyproject.toml`、`requirements.txt`、`CLAUDE.md §5` 命令占位。
- [x] **Phase 2** — `core/domain/models.py`（SourceDocument/Collection/tags/DocumentChunk/SyncTargetKind/SyncStatus/QuotaLevel/SyncRecord/QuotaUsage/QuotaWarning/GraphEntity/GraphRelation）。
- [x] **Phase 3** — 4 个端口 `base.py`（source_store/kb_reader/sync_targets/graph_store，契约 docstring）+ 各 `memory.py` + 端口对换测试。
- [x] **Phase 4** — `core/config.py`（各 XxxConfig，含 WebConsoleConfig 独立端口）+ `core/api.py` 业务门面骨架；`*.example.py` → 真实 `main.py`/`plugin_initializer.py`/`event_handler.py`（删除占位）。薄壳生命周期 smoke test 通过（`lifecycle OK`）。
- [x] **Phase 5** — 安全：机密改 env（config.py：R2 secret / Web 密码经环境变量）、扫描确认仓库无硬编码密钥、`.gitignore` 加固（补 `.env.*`/`*.log`/`/data/`）。⚠️ 运行态目录中泄露的 Notion/Cloudflare token 需用户手动轮换（文件在本仓库工作区外未改动）。

### Verification

- `python -m pytest tests/backend/` → 38 passed（仅内存实现，无外部 I/O）
- `ruff check .` → All checks passed；`mypy` → Success（domain 严格）
- 薄壳生命周期 smoke：`KnowledgeRepositoryPlugin.initialize/terminate` → `lifecycle OK`
- 注：本环境 pytest/ruff/mypy 装在 `/usr/local/bin/python3`（非 `/usr/bin/python3`），用前者运行。

---

## v0.1.0 项目初始化 (in progress)

### User constraints / 约束

- 基于通用项目框架模板，保留分层结构与治理三件套。

### Technical implementation path

- [x] **Phase 1 — 骨架**：复制模板，建立分层目录与治理文件。
- [ ] **Phase 2 — 填空**：替换 `metadata.yaml` / `_conf_schema.json` / `pyproject.toml` / `CLAUDE.md` §5 命令占位。
- [ ] **Phase 3 — 首个子系统**：按 `ARCHITECTURE.md` 的「新增子系统清单」落地第一个业务管线。

### Verification

- `<TEST_CMD>` → 全绿
- `<LINT_CMD>` → 无错误

---

## 💬 待讨论 Backlog

> 以下条目均处于**待讨论**状态，尚未纳入任何版本计划。执行前须明确优先级、设计方案并获确认，以防与未来改动冲突。

### 功能 (Features)

- 💬 **自动分类（可优化项）**：在手动分类基础上，提供可选 LLM/embedding 聚类自动打标签（默认关，开启时成本警告）。v0.3.0 已留 ABC 口，后续可升级为正式版本。
- 💬 **Notion 自动建库（可优化项）**：在初始化/同步阶段，如果检测到未配置 `database_id`，利用 Notion MCP 的 `create_database` 工具在指定的 Parent Page 下自动为用户新建一个标准属性的数据库，并回写至配置，提供一键零配置体验。
- 💬 **Notion 反向同步（可优化项）**：提供 `/kr sync notion --pull` 指令或 WebUI 拉取按钮，增量拉取 Notion 侧对页面属性（Tags/Collection）的修改并安全合并回本地，且绝不级联删除本地 PDF 原件。
- 💬 （示例）<在此登记尚未排期的功能想法。>

### 架构 / 清理 (Architecture / Cleanup)

- 💬 （示例）<在此登记需要讨论的重构/技术债。>
