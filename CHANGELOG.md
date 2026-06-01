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

## [v0.13.0] — 2026-06-01

### 新增功能 (Added)

- **WebUI 能力接通 (`web/frontend/lib/api.ts`, `app/(console)/*`)**：接通显式登出、文档原件下载、R2 / Notion 手动同步、同步状态展示、空集合删除与图谱 collection 筛选；`/api/sync/all` 现会 fan-out 到全部同步目标。
- **配置诊断 (`core/config.py`)**：在只读有效配置中增加 R2 / Notion enabled 状态缺失字段诊断；R2 与 Notion 信息继续由 AstrBot 原生插件设置提供，Notion token 仍由 MCP server 管理。

### 修复 (Fixed)

- **HTTP 契约对齐 (`web/server.py`, `web/frontend/lib/api.ts`)**：collection 创建、文档上传与文档更新返回完整资源；文档 JSON 补齐 `size`、`updated`、`filename`、`ext`、`chunks`；修正 KB 搜索 `top_k`、reserved `501` 和图谱查询字段映射。
- **R2 灾备闭环 (`core/pipelines/sync_pipeline.py`, `core/repository/sync_targets/*`)**：数据库快照改用专用 `backups/knowledge_repository.db` 键；通过 SQLite backup API 生成一致快照；恢复时先写临时文件、执行完整性校验并原子替换，返回 `restart_required`。
- **文档生命周期 (`core/api.py`, `core/managers/ingest_manager.py`, `core/repository/source_store/*`)**：摄入失败回滚插件托管原件和元数据；删除文档时清理图谱贡献、远端镜像、同步账本与托管原件；SQLite chunk 替换失败时显式 rollback。
- **Ask 生产装配 (`core/plugin_initializer.py`)**：将已构造的 `LLMAdapter` 注入 `KnowledgeRepositoryApi`，避免生产环境 Ask 固定退化为检索摘要。

### 架构健康 (Refactor)

- **运行时配置边界 (`core/runtime_config.py`, `core/plugin_initializer.py`)**：运行时覆盖仅允许 Notion 自动建库生成的非敏感字段；AstrBot 原生写回改为完整合并配置，避免局部 override 覆盖其它配置。
- **能力声明校准 (`_conf_schema.json`, `core/config.py`, `migrations/003_graph_store.sql`)**：明确备份范围为插件托管原件与 `knowledge_repository.db`；Notion 大文件当前仅同步元数据；实体 embedding 持久化标记为后续预留。

### 测试 (Tests)

- **回归补强 (`tests/backend/`)**：新增 HTTP 资源契约、reserved 协议、图谱查询字段、配置白名单、R2 专用快照键、无效快照拒绝、SQLite 重启读取、文档生命周期清理、摄入失败回滚和 `sync all` fan-out 测试。

### 构建与工程 (Build/CI)

- **静态发布 (`web/frontend/out`, `pages/`)**：完成 Next.js 静态导出并通过 `tools/sync_frontend.py` 镜像同步。

## [v0.12.1] — 2026-06-01

### 修复 (Fixed)

- **WebUI 截图基线对齐 (`web/frontend/`)**：补齐左栏搜索/跳转框、品牌副标题、`AI` badge、在线状态与激活项强调条；校准 Ask 空状态、文档工具条、居中检索卡片、平面毛玻璃图谱节点和同步分组布局，使五个主页面贴近 `docs/` 中的目标截图。
- **全局氛围层去重 (`web/frontend/app/(console)/*`, `components/fx/Atmosphere.tsx`, `styles/tokens.css`)**：保留外壳唯一 `Atmosphere`，移除页面重复 `DotField` 与额外 Aurora，并修复 `--ring` 被固定色覆盖导致 HSL 换肤级联不完整的问题。
- **动态预览入口修复 (`tests/run_webui.py`)**：优先托管 `web/frontend/out/`，构建产物不存在时回退 `pages/`，避免继续加载遗留源码目录。

### 构建与工程 (Build/CI)

- **静态发布改为镜像同步 (`tools/sync_frontend.py`, `pages/`)**：同步前清理旧 `pages/`，`--check` 同时检查目标目录多余文件，避免旧 hash chunk 累积或误加载。
- **版本记录统一 (`metadata.yaml`, `TODO.md`)**：版本号更新为 `v0.12.1`，闭环补丁计划与验证结果。

## [v0.12.0] — 2026-06-01

### 新增功能 (Added)

- **前端视效与交互增强 (`web/frontend/`)**：
  - 新增跟随光标缓动的暖色柔光氛围层 `<Atmosphere />`，通过 RequestAnimationFrame 实现 LERP (`0.06`) 位置缓动、三层极光错峰漂移、分层视差与无障碍降级支持（`prefers-reduced-motion`）（`components/fx/Atmosphere.tsx`, `app/(console)/layout.tsx`）。
  - 增强漂浮点场 `DotField` 至 `22` 个点，针对近景小点添加 `box-shadow` 发光光晕与错峰明灭（`components/fx/DotField.tsx`）。
  - 重构 `Ask Agent` 初始页，移除示例推荐问题，改用精致简洁的居中 `✦` 图标及标题 (`ask_empty_title` / `ask_empty_sub`)，并移除了应用内冗余的 `SunBloom` 太阳（`app/(console)/ask/page.tsx`）。
  - 在设置页新增「色相/饱和度/明度」HSL 渐变滑杆与 6 组经典色彩预设，驱动全站 `tokens.css` 级联变色与换肤，并利用 `localStorage` 自动持久化偏好（`app/(console)/settings/page.tsx`, `styles/tokens.css`, `lib/theme.ts`）。
  - 彻底重构知识图谱为 HTML + SVG 混合式扁平淡毛玻璃图谱。节点采用 HTML 圆盘辅以 `backdrop-filter: blur(7px)` 与 `color-mix` 软透明色彩；关系标签采用毛玻璃小药丸且仅在聚焦邻域时悬浮浮现；交互支持 Hover/选中一阶邻域高亮，点击画布空白处重置（`app/(console)/graph/page.tsx`）。
  - 完善多语言字典，新增空状态和设置滑杆相关的中英文翻译键值对（`lib/i18n.ts`）。

## [v0.11.0] — 2026-05-31

### 新增功能 (Added)

- **HTTP API 端口补全 (`web/server.py`)**：
  - 新增 `GET /api/documents/{doc_id}/raw` 文档下载端点，返回本地 PDF 物理原件二进制流。
  - 新增 `POST /api/logout` 显式登出端点，清理 session Token 并彻底删除 `kr_session` cookie。

### 架构与加固 (Refactor/Hardening)

- **配置持久化收敛 (`core/runtime_config.py`, `core/plugin_initializer.py`)**：
  - 重构 `RuntimeConfigStore` 边界，增加对 AstrBot 原生配置回写适配接口的自适应调用 (`save_config` / `update_config` / `persist_config`)。
- **Notion 自动分页与属性诊断 (`core/adapters/notion_mcp.py`, `core/repository/sync_targets/notion.py`)**：
  - 为 `NotionMCPAdapter.query_database` 补齐完整的循环自动分页拉取逻辑。
  - 增强元数据同步的 schema 缺失诊断与智能过滤机制，并提供精细化的 `skipped_details` (no_properties, schema_missing, no_docid, missing_local, no_change) 统计返回。
  - 为 `SyncRecord` 的推送记账添加 `degraded:` / `degraded_skipped:` 前缀支持，精确审计属性降级写入的状态。

### 测试 (Tests)

- **回归与契约测试强补 (`tests/backend/test_web_server.py`, `tests/backend/test_notion_target.py`)**：
  - 补充 `test_logout_route` 和 `test_download_document_route` 集成测试，验证 100% 下载与会话移除。
  - 补充 `test_notion_query_database_paging` 单元测试，验证 paged 循环拉取流程。

---

## [v0.10.0] — 2026-05-31

### 新增功能 (Added)

- **WebUI 全面重构（Next.js App Router + fumadocs-ui v16）**：
  - 新增 `web/frontend/`（Next.js 16 + React 19 + TypeScript）完全替代旧版单文件 HTML。
  - 设计语言：暖色奶油（`--bg: #f7f4ed`）+ 橙色强调（`--accent: #df7a18`），浅/深双主题，`data-palette` 4 色系切换。
  - `web/frontend/styles/tokens.css`：完整 CSS 变量体系，`.fx-glass` / `.fx-glass-edge` 毛玻璃工具类，`@keyframes` 动画集。
  - `web/frontend/lib/api.ts`：统一网络出口，封装所有 `/api/*` 端口，含 `?mock` 离线模式与 `reserved` 降级处理。
  - `web/frontend/lib/i18n.ts`：中英双语 i18n Context，`localStorage` 持久化。
  - `web/frontend/components/fx/`：视效层 `DotField`（12 点 CSS 动画）、`SunBloom`（SVG 旋转光晕）、`GrainOverlay`（feTurbulence 噪点叠层）。
  - `web/frontend/components/rail/Rail.tsx`：左栏导航，含 Ask Agent 特色入口、配额用量 badge、主题切换、登出。
  - 7 个页面全量实现：`/documents`（三栏工作台、多选批量操作）、`/ask`（Ask Agent 对话 + `[n]` 角标来源面板）、`/search`（KB 检索高亮）、`/graph`（SVG 图谱 + 查询）、`/sync`（Notion/R2/备份）、`/quota`（进度条配额仪表盘）、`/settings`（外观 + 有效配置只读区）。
- **新增后端 `POST /api/ask` 端口**（Ask Agent）：
  - `core/api.py::ask()`：KB 检索 + LLM 上下文拼装 + 答案生成，返回 `{ conversation_id, answer, sources }`。
  - `core/api.py`：`__init__` 新增 `llm_adapter` 依赖注入参数（`LLMAdapter | None`）。
  - `core/adapters/llm.py`：新增 `generate()` 通用文本生成方法与离线占位 `_mock_generate()`。
  - `web/server.py`：注册 `POST /api/ask` 路由 `handle_ask()`；静态服务层重构为 SPA catch-all，兼容 Next.js export 子目录 `index.html` 结构与 `/_next/` 资源包。
- **`tools/sync_frontend.py` 重构**：自动检测 `web/frontend/out/`（Next.js export 产物），存在则同步 `out/` 到 `pages/`，否则回退旧版逻辑；新增 `--force`/`-f` 兼容参数。
- **`CLAUDE.md §5`** 更新前端 Build & Test 命令为 `npm run build` + `sync_frontend.py`。

### 构建与工程 (Build/CI)

- 新增 `web/frontend/package.json`（Next.js 16.2.6 + fumadocs-ui 16.9.3 + next-themes + geist）。
- `web/frontend/next.config.ts`：`output: 'export'`（生产）/ dev rewrite → `:6520`（开发），`images.unoptimized: true`。
- `metadata.yaml`：version 升至 `v0.10.0`。

## [Unreleased]

### 新增功能 (Added)

- Notion 自动建库与反向元数据同步 (`core/adapters/notion_mcp.py`, `core/repository/sync_targets/notion.py`, `core/pipelines/sync_pipeline.py`):
  - 新增 Notion MCP `create_database` / `query_database` 适配能力，支持在指定 Parent Page 下创建标准 `Name` / `Collection` / `Tags` / `DocID` 数据库。
  - 新增运行时配置覆盖 `core/runtime_config.py`，自动建库成功后将 `database_id` 回写到 `data_dir/runtime_config.json` 并更新内存配置。
  - 新增 Notion pull 流程，只按 `DocID` 反向拉取 `Collection` / `Tags`，不覆盖标题、文件路径、content hash 或本地 PDF 原件。
- 设置核对与前后端接线验证 (`core/api.py`, `web/server.py`, `web/frontend/index.html`, `pages/index.html`):
  - 新增 `GET /api/config/effective`、`POST /api/notion/init`、`POST /api/sync/notion/pull`。
  - 新增 `/kr notion init` 与 `/kr sync notion --pull` CLI 薄壳。
  - Web 控制台新增“设置核对”页、前后端能力矩阵、Notion 初始化按钮和 Notion 反向拉取按钮。
- 图谱可视化与检索预览进阶 (`core/api.py`, `web/server.py`, `web/frontend/index.html`, `pages/index.html`):
  - `GraphStore` 正式扩展 `list_entities()` / `list_relations()` 读取契约，并在 SQLite / 内存实现中保持一致，供图谱前端通过 API 门面读取。
  - `core/api.py::get_graph()` 落地 collection 级图谱数据接口，返回 nodes / edges 与 `source_previews` 来源片段预览，不直读前端侧数据库细节。
  - `/api/graph/query?debug=true` 返回向量召回、实体关键词召回、1-hop 图邻域召回和 RRF score 诊断，默认查询仍保持轻量。
  - Web 控制台新增轻量 SVG 图谱视图、节点/边详情、来源片段预览、融合查询结果和调试诊断面板；同步更新静态产物 `pages/index.html`。

### 测试 (Tests)

- 增强 `tests/backend/test_config.py`、`tests/backend/test_notion_target.py`、`tests/backend/test_web_server.py`、`tests/backend/test_lifecycle_and_cli.py`，覆盖 Notion 自动建库、pull 合并策略、配置脱敏、HTTP 路由和 CLI 入口。
- 增强 `tests/backend/test_graph_store.py`、`tests/backend/test_api.py`、`tests/backend/test_graph_search_pipeline.py`、`tests/backend/test_web_server.py`，覆盖图谱读取契约、collection 过滤、source preview、HTTP graph data 与 debug 查询。

## [v0.6.0] — 2026-05-30

### 新增功能 (Added)

- 属性图混合检索与 RRF 融合管道 (`core/pipelines/graph_search_pipeline.py`):
  - 整合向量相似度召回（bge-m3 语义分块）、本地关键词精确召回（实体匹配）、以及图邻域单步扩展召回（1-hop 边关联分块）。
  - 采用互惠排名融合（RRF）算法，科学对齐排序权重，整合检索结果并按 RRF 得分排序，输出 Top-K 文本分块。
  - 自动将召回的实体、关系与文本分块编译为富学术上下文，支持大语言模型在下游进行精准推理。
- 知识图谱 CLI 命令与业务 API 门面整合 (`core/api.py`, `core/main.py`, `core/event_handler.py`, `core/plugin_initializer.py`):
  - 将 `build_graph` 与 `query_graph` 业务实现委派给 `GraphBuildPipeline` 和 `GraphSearchPipeline`，并将提取/检索的领域模型进行健壮的序列化，输出 JSON 兼容字典。
  - 组合根中完整装配了图谱 SQLite 数据库、LLM 适配器和检索构建管线，注入到 `KnowledgeRepositoryApi` 中。
  - Plumb 了 `/kr graph build` (支持按集合增量抽取构建) 与 `/kr graph query <q>` (执行 RRF 融合检索并在终端美化输出) 的 CLI 交互命令。
- 领域本体预设与自定义引擎支持 (`core/config.py`, `_conf_schema.json`):
  - 完美支持 `entity_types` 本体配置，并在 LLM 系统提示词动态注入与抽取清洗中实施全链路本体类型过滤和默认回退对齐。

### 测试 (Tests)

- 新增 `tests/backend/test_graph_search_pipeline.py`：对混合检索管道、多路召回融合、RRF 排序、以及上下文合成逻辑进行了 100% 单元测试覆盖。
- 增强 `tests/backend/test_lifecycle_and_cli.py`：添加了对 `/kr graph build` 和 `/kr graph query` 的集成测试，验证其能在离线 Mock LLM 环境下稳定抽样、织入 SQLite 并输出排序检索。
- 增强 `tests/backend/test_web_server.py`：添加了对 HTTP 接口 `/api/graph/build` 与 `/api/graph/query` 的集成测试，确保正常运作时返回 200 OK 并序列化输出。

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
