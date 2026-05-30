# CHANGELOG

> 本文件记录项目的所有重要变更。**所有参与者（含 AI Agent）在写入时必须遵守下方「写入规范」。**

## 写入规范

- **倒序排列**：最新版本永远在最上方；`[Unreleased]` 在所有已发布版本之上。
- **版本标题格式**：`## [vX.Y.Z] — YYYY-MM-DD`，遵循 [SemVer](https://semver.org/)；版本号与 `metadata.yaml` 的 `version` 对齐。
  - MAJOR：不兼容的接口/数据结构变更；MINOR：向后兼容的新功能；PATCH：向后兼容的修复。
- **子分区**（按需出现，无内容则省略，顺序固定）：
  - `新增功能 (Added)` — 新能力、新接口、新配置项。
  - `修复 (Fixed)` — bug 修复。
  - `性能优化 (Performance)` — 不改变行为的提速/降耗。
  - `架构健康 (Refactor)` — 重构、死代码清理、接口收敛。
  - `测试 (Tests)` — 新增/调整的测试。
  - `构建与工程 (Build/CI)` — 依赖、CI、打包、工具链。
- **每条变更点名涉及的文件或模块**，强化可追溯，例如：
  - `修复 RecallManager 热路径串行写入：在 EventRepository 新增 bump_event_usage 合并 3 次 UPDATE 为单事务（core/repository/base.py, sqlite.py）。`
- **写入时机**：任务收尾时追加（见 `CLAUDE.md` §4 工作闭环）；先进 `[Unreleased]`，发布时整体改写为版本标题 + 日期。
- 语言：正文中文，标识符/路径/版本号英文。

---

## [Unreleased]

### 新增功能 (Added)

## [v0.4.0] — 2026-05-30

### 新增功能 (Added)

- AstrBot KB 适配器与读取器 (`core/adapters/astrbot_kb.py`, `core/repository/kb_reader/astrbot.py`):
  - 实现双向适配层，支持将运行时 raw dict/object 转换为标准的 `DocumentChunk` 领域模型。
  - 基于反射机制 `getattr` 实现安全可靠的 AstrBot 框架知识库读取。
- Notion MCP 同步适配器与同步目标 (`core/adapters/notion_mcp.py`, `core/repository/sync_targets/notion.py`):
  - 实现基于 MCP tool 调用的 Notion 客户端，完美映射 Page 属性与 Block 内容。
  - 支持免 R2 直连同步解耦，超过 5MiB 大文件仅在 Notion 创建附带警告的元数据卡片而跳过二进制流推送，并产生 `SyncStatus.SKIPPED` 事务状态。
  - 实现防抖/限频控制（3 req/s 延迟限制），避免触发 Notion Rate Limit。
  - 提供单次同步超过 10 篇文档时的交互式耗时估算与额度警告。
  - 实现渐进降级策略：优先创建完整元数据属性，当缺失自定义属性列（如 Collection/Tags/DocID）时自动捕获异常并降级为仅同步 `Name`（标题），打印详细的数据库属性配置说明。
- 命令行指令 plumbling (`core/event_handler.py`, `core/main.py`):
  - 新增 `/kr sync notion` 镜像同步指令及批量执行安全警告。
  - 新增 `/kr sync status` 命令以查看同步历史记录及最终结果。
- 架构闭环与组合根装配 (`core/plugin_initializer.py`):
  - 完成 Notion 同步服务生命周期构建与注入，显式捕获 `asyncio.CancelledError` 以确保生命周期正常收尾。

### 测试 (Tests)

- 新增 `tests/backend/test_notion_target.py`：对限频控制、大文件镜像跳过策略、Notion 数据库属性列缺失渐进降级等进行了 100% 覆盖。

## [v0.3.0] — 2026-05-30

### 新增功能 (Added)

- PDF 物理原件库管理 (`core/repository/source_store/sqlite.py`, `migrations/001_source_store.sql`):
  - 实现基于 `aiosqlite` 的 SQLite 仓储持久化，支持参数化绑定以防止 SQL 注入。
  - 创建幂等性迁移执行器 `migrations/runner.py`。
- 本地免成本 PDF 文本抽取与稳定切块 (`core/managers/ingest_manager.py`):
  - 基于 PyMuPDF (`fitz`) 实现本地文本抽取，保持 OCR/LLM 为可选/警示。
  - 采用独创「物理页隔离 + 动态段落合并」切分算法，单页超限自动重叠切分。
- Cloudflare R2 对象存储备份 (`core/repository/sync_targets/r2.py`, `core/pipelines/sync_pipeline.py`):
  - 通过 `boto3` 实现原件二进制流上传，前缀匹配集合，自动备份云端 SQLite 快照。
- 配额预警与安全阻断 (`core/managers/quota_manager.py`):
  - 接入 R2 10GB 免费空间限制，在 80% (8GB) 时触发 WARN，100% (10GB) 触发 BLOCK。
- 组合根组装与 CLI 控制台 plumbling (`core/plugin_initializer.py`, `core/event_handler.py`, `core/main.py`):
  - 实现组合根的完整生命周期，启用 PRAGMA 外键约束，自动执行周期背景同步。
  - Plumb 了 `/kr add`, `/kr sync r2`, `/kr quota`, `/kr collection`, `/kr tag` 命令。

### 测试 (Tests)

- 新增 `tests/backend/test_lifecycle_and_cli.py`：100% 覆盖 PluginInitializer, EventHandler CLI command 交互与生命周期 symmetry。

- v0.5.0 独立 Web 控制台 MVP（**提前实现**，按用户要求先对接内存实现预览，真实后端 v0.3.0/v0.4.0 接入后只换组合根注入）：
  - `web/server.py`：aiohttp 独立服务，认证中间件（session cookie）+ 路由委派 `core/api`，零业务；静态前端由 static_dir 托管（生产 pages/，调试 web/frontend/）。
  - `web/frontend/index.html`：单页零构建控制台（原生 JS），四区——文档管理（拖拽上传/删/改集合/改标签）、分类集合（CRUD）、知识库检索、配额仪表盘（接近阈值变色警告）。**新增离线仿真预览模式（Offline Mock Mode）**，在 `file://` 协议或携带 `?mock=true` 下自动免密登录，并在前端通过 JS 内存模拟所有后端接口。
  - `core/api.py` 门面补全：`create_collection/delete_collection/register_document/delete_document/list_quota`（注入 `sync_targets`）。
  - **预留端口（接口先行）**：`core/api` 留 `sync_documents/get_sync_status/backup_now/restore_from_backup/build_graph/query_graph/get_graph` 方法桩（NotImplementedError），`web/server` 对应路由经 `_reserved()` 回 501+`available_in`，前端 `callReserved()` 统一渲染「将在 vX 接入」。后端接入后前端零改动。
  - 前端补「同步/备份」「知识图谱」两个标签页与按钮（对接上述预留端口）。
  - `core/repository/sync_targets/memory.py`：新增 `base_used_bytes`（模拟已有用量不真分配字节，用于配额演示）。
  - `tests/run_webui.py`：一键调试启动脚本（播种示例集合/文档/KB/配额，`--no-auth`/`--port`/`--empty`）。
  - `tools/sync_frontend.py`：前端源码 → `pages/` 同步（`--check` 供 CI 一致性校验）。
- v0.2.0 Phase 4（类型化配置 + 业务门面 + 薄壳/组合根）：
  - `core/config.py`：唯一配置解析入口，5 组 typed config（SourceStore/R2Sync/NotionSync/WebConsole/Graph）；机密经环境变量注入（`KR_R2_SECRET_ACCESS_KEY`、`KR_WEB_PASSWORD`）；R2 endpoint/free_tier_bytes、Notion max_upload_bytes 为派生量。
  - `core/api.py`：框架无关业务门面 `KnowledgeRepositoryApi`（只读门面：列集合/文档、分类、读 KB/检索；编排写操作随后续 managers 接入）。
  - `core/{main,plugin_initializer,event_handler}.py`：薄壳 + 组合根 + 事件分发真实文件（替换并删除 `*.example.py` 占位）；薄壳生命周期 smoke test 通过。
- v0.2.0 Phase 2/3（domain 模型 + 4 个仓储端口）：
  - `core/domain/models.py`：纯数据模型（零依赖）——SourceDocument/Collection/DocumentChunk/SyncRecord/QuotaUsage/QuotaWarning/GraphEntity/GraphRelation 与枚举 SyncTargetKind/SyncStatus/QuotaLevel；QuotaUsage 提供 ratio/projected_bytes/will_exceed 派生量。
  - 4 个 ABC 端口（接口先行，契约写入 docstring）+ 各自内存实现：
    `core/repository/source_store/{base.py,memory.py}`（原件/集合/分块）、
    `core/repository/kb_reader/{base.py,memory.py}`（AstrBot KB 只读）、
    `core/repository/sync_targets/{base.py,memory.py}`（R2/Notion 统一 push/delete/check_quota）、
    `core/repository/graph_store/{base.py,memory.py}`（LightRAG 风格属性图，增量 upsert + chunk 状态 + 邻域扩展）。

### 测试 (Tests)

- 端口对换测试 + Web 路由 smoke 测试（注入内存实现，无外部 I/O），共 61 passed：
  `tests/backend/{test_source_store,test_kb_reader,test_sync_target,test_graph_store,test_config,test_api,test_web_server}.py`。
  `test_web_server.py` 用 aiohttp TestServer 覆盖集合/文档 CRUD、multipart 上传、KB 检索、配额、认证拦截/登录、
  以及 8 个预留端口均返回 501+`available_in`（参数化）。
  （ruff: All checks passed；mypy: Success，domain 严格。Web 控制台 live smoke：index 200 + 各 API（含预留端口 501）返回正确。注：工具链在 `/usr/local/bin/python3`。）

### 安全 (Security)

- v0.2.0 Phase 5：机密一律经环境变量注入，`_conf_schema.json` 密钥字段默认空且 hint 标注勿提交；
  加固 `.gitignore`（原已含 `.env`/`*.db`/`*.sqlite`，本次补 `.env.*`、`*.log`、`/data/`）；
  扫描确认本仓库无硬编码密钥（`core/`、`*.json`、`*.yaml`、`*.md`）。
  ⚠️ 备注：AstrBot 运行态目录（`astrbot-data-docker/data/mcp_server.json` 等，位于本仓库工作区之外，未改动）
  曾以明文存放真实 Notion(`ntn_…`)/Cloudflare(`cfut_…`) token。

### 测试 (Tests · 修复)

- `tests/backend/test_api.py`：去掉 `async def` fixture，改为 async 工厂 `_make_api()` 在各测试内构造，
  规避 pytest-asyncio auto 模式下 async fixture 被重复收集的问题。

### 构建与工程 (Build/CI)

- v0.2.0 Phase 1（框架填空）：填写项目清单与配置 schema，替换模板占位（metadata.yaml, _conf_schema.json, pyproject.toml, requirements.txt, CLAUDE.md §5）。
  - `metadata.yaml`：name=astrbot_plugin_knowledge_repository，version=v0.2.0。
  - `_conf_schema.json`：定义 5 组配置 source_store / r2_sync / notion_sync / web_console / graph（含 R2 10GB 额度预警字段、Notion 5MiB 限制、Web 独立端口、LightRAG 增量参数）。
  - `requirements.txt`：aiosqlite/PyMuPDF/boto3/aiohttp/numpy + 测试链（检索与 Notion 复用 AstrBot 既有能力，故不引入向量库/notion-sdk）。
  - `CLAUDE.md §5`：填入 install/test/lint 真实命令。

<!--
发布时：把上面的 [Unreleased] 整体改写为：

## [vX.Y.Z] — YYYY-MM-DD

### 新增功能 (Added)
- ...

### 修复 (Fixed)
- ...
-->

---

## [v0.1.0] — YYYY-MM-DD

### 构建与工程 (Build/CI)

- 基于通用项目框架模板初始化仓库；建立分层骨架、治理三件套（CLAUDE/CHANGELOG/TODO）与 CI。
