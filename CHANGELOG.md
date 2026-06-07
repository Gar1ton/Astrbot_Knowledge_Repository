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

- **Ask 页知识库选中高亮边与发送键灰态**：选中集合时输入卡片显示橙色高亮边（`--accent-border`）；加载期间边框退回普通色、仅保留旋转辉光；图谱检索模式下未选有效集合时发送键变灰，点击仍触发已有 toast 提示（`web/frontend/app/globals.css`, `web/frontend/app/(console)/ask/page.tsx`）。
- **Milvus 自动索引开关说明文案优化**：label 改为「上传后立即建立 Milvus 向量索引」，说明文字补充延迟索引 / 批量重建工作流说明（`web/frontend/app/(console)/settings/page.tsx`）。

### 构建与工程 (Build/CI)

- **PDF 清洗依赖改为插件自动安装**：将 `pymupdf4llm>=0.0.17,<0.1.0` 与 `PyMuPDF>=1.24,<2.0` 纳入 AstrBot 自动安装的根 `requirements.txt`，并从 `requirements-additional.txt` 移除重复声明；`pdf_extract` 不再出现在可选依赖白名单或手动安装面板中，ingest 环节改为报告核心依赖来源（`requirements.txt`, `requirements-additional.txt`, `core/capabilities.py`, `core/managers/markdown_extractor.py`, `web/frontend/lib/api.ts`, `tests/backend/test_capabilities.py`, `tests/backend/test_web_server.py`）。

## [v0.22.0] — 2026-06-07

> Zotero 镜像 + PyMuPDF4LLM 清洗内核 + 制品包数据模型 + 作用域检索。引入以 `document_id = <library_id>_<item_key>_<attachment_key>` 为核心的制品包模型，打通 Zotero → 清洗 → 检索整体数据流。

### 新增功能 (Added)

- **Zotero 单向 Pull 同步**：只读 `zotero.sqlite`（主路径）镜像本地 Zotero 的 libraries/collections/items/creators/tags/attachments/relations；三种同步模式（`strict_mirror` 严格镜像 / `conservative` 保守同步（默认）/ `archive` 归档堆栈）× 两种存储模式（`managed_copy` 副本托管 / `linked` 链接 Zotero storage）；strict 脱管文档保留 LRAG workspace 标 `detached`，切回兼容模式自动 reattach；增量（zotero version 跳过未变）；手动（sync 页）+ 自动（重启 + 定时间隔）触发（`core/adapters/zotero/{sqlite_reader,local_api,paths}.py`, `core/pipelines/zotero_sync_pipeline.py`, `core/plugin_initializer.py`）。
- **PyMuPDF4LLM 清洗内核**：PDF → 干净 Markdown（无可见页码）+ pages.json（写盘 LF 归一化后的字符偏移），**完全替换 fitz 手写抽取**；IngestManager 改为「制品包 + clean.md 字符区间分块」，保证 `clean.md[start:end] == chunk.text` 的 offset 不变量；本地上传以 `LOCAL` 库 + 合成 key 镜像（`core/managers/markdown_extractor.py`, `core/managers/ingest_manager.py`）。
- **制品包数据模型**：每文档一目录 `data_dir/library/<document_id>/{original.pdf, clean.md, pages.json, meta.json}`；新增 Zotero 镜像表与 `page_chunks`、文档 `origin`/`read_only`/`lifecycle_state`/`last_synced_at`/`library_id` 等列（migrations 009-012）；domain 新增 `DocumentOrigin`/`DocumentLifecycle`/`Zotero*`/`PageChunk`（`core/domain/models.py`, `migrations/009-012_*.sql`, `core/repository/source_store/{base,sqlite,memory}.py`）。
- **作用域检索（item/collection/tag/library）**：orchestrator 新增 `resolve_scope` + **硬过滤契约**——任何候选 chunk 必须先满足 `allowed_document_ids` 才进入 RRF（覆盖 Milvus/SQLite lexical/LightRAG）；item/tag 子作用域禁用图谱通道防越界；`ask`/`search_kb` 与 `/api/ask`、`/api/kb/search` 接受 scope 参数（`core/pipelines/retrieval_orchestrator.py`, `core/api.py`, `web/server.py`）。
- **三指示元数据 + provenance**：文档序列化新增来源徽章、只读、生命态、`last_synced_at`、Milvus 覆盖、LRAG 索引状态与 Zotero 归一化引用（creators/year/venue/DOI/abstract）；Ask sources 携带 `document_id`/`pages`/Zotero 跳转 URI/引用（`web/server.py`, `core/api.py`）。
- **前端 Zotero UX**：sync 页 Zotero 连接状态卡 + 「从 Zotero 同步」按钮；documents 页来源徽章/只读详情/三指示/文献元数据；flow 页最左端 Zotero 来源节点；`lib/api.ts` 新增 `ZoteroConfig`/`ZoteroSyncResult` 类型与 `getZoteroConfig`/`syncZoteroPull`/`getZoteroSyncStatus`（`web/frontend/lib/api.ts`, `web/frontend/app/(console)/{sync,documents,flow}/page.tsx`）。
- **配置**：新增 `ZoteroSyncConfig` + `_conf_schema.json` 的 `zotero_sync` 段（storage_mode/sync_mode/linked_root/auto_sync 等；机密 `cloud_api_key` 仅经 `KR_ZOTERO_API_KEY` 环境变量）+ `CONFIG_KEY_POLICY` 登记（`core/config.py`, `_conf_schema.json`）。
- **R2 备份纳入制品包**：同步时把 clean.md/pages.json/meta.json 一并上传至 R2（key `artifacts/<collection>/<doc_id>/<name>`），两种存储模式下 PDF 均纳入备份（`core/pipelines/sync_pipeline.py`）。

### 安全 (Security)

- **Zotero 同步来源只读强制（service 层）**：`origin=zotero` 的文档/集合在 `delete_document`/`classify_document`/`delete_collection` 处抛 `ReadOnlyError`，web 层返回 403；仅 Zotero Pull 这一特权服务可变更，前端隐藏仅为第二层防护（`core/api.py`, `web/server.py`）。

### 架构健康 (Refactor)

- **移除 fitz 手写抽取路径**：`_extract_raw_doc_text` 改读 clean.md；删除文档级联清理整个 `library/<id>/` 制品包目录（`core/api.py`, `core/plugin_initializer.py`）。

### 构建与工程 (Build/CI)

- **PyMuPDF4LLM pinned 依赖**：`requirements-additional.txt` 固定 `pymupdf4llm>=0.0.17,<0.1.0` 与 `PyMuPDF>=1.24,<2.0`（不 vendor 源码，规避 AGPL 分发义务）；`core/capabilities.py` 登记 `pdf_extract` 依赖与 ingest 环节清洗就绪态；`metadata.yaml` → v0.22.0。

### 测试 (Tests)

- 新增 `test_zotero_mirror.py`（镜像/scope 助手/page_chunks 接口对换 16）、`test_ingest_manager.py`（offset 不变量重写）、`test_zotero_sync.py`（reader + 3 模式 + linked 6）、`test_retrieval_scope.py`（scope 解析 + 硬过滤 8）、`test_readonly_enforcement.py`（只读 4）+ web 路由/能力测试调整；全套 252 passed，ruff + mypy 干净，Next.js build 13 页 + sync_frontend 150 文件。

## [v0.21.0] — 2026-06-07

### 修复 (Fixed)

- **LRAG 召回后零结果 bug（关键修复）**：`retrieve_lightrag_context()` 原本要求集合内所有文档均处于 `status="indexed"` 才允许查询，但 `get_lightrag_readiness()` 只要求至少一篇已索引即报告就绪，且构建失败后 `partial_failure` 任务仍标记索引兼容；两者逻辑矛盾导致部分失败后查询立即抛 "requires indexing" 而非走图谱。修复方案：删除 `retrieve_lightrag_context()` 中的逐文档状态循环，转而完全依赖 `has_workspace()` 与 `is_lightrag_compatible()` 判断可查询性，与 LightRAG 全图查询语义一致（`core/pipelines/retrieval_orchestrator.py`）。

### 新增功能 (Added)

- **图谱构建浮窗（全局常驻）**：新增 `BuildWidget` 组件，挂载在控制台 shell 层，切换任何页面均保持可见；实时轮询 `GET /api/graph/build/active`，显示进度条、已用时、剩余预估时间；支持**暂停 / 继续**按钮，一键跳转图谱页（`web/frontend/components/build/BuildWidget.tsx`, `web/frontend/app/(console)/layout.tsx`）。
- **构建暂停 / 继续**：后端 `BuildJob` 新增 `paused` 字段，`KnowledgeRepositoryApi` 维护每个任务的 `asyncio.Event` 暂停信号；构建 asyncio 任务在每篇文档处理前 `await` 该信号，暂停时原地阻塞；新增 `POST /api/graph/build/{job_id}/pause`、`POST /api/graph/build/{job_id}/resume`、`GET /api/graph/build/active` 三个端点（`core/lightrag_core.py`, `core/api.py`, `web/server.py`, `web/frontend/lib/api.ts`）。
- **构建任务持久化与断点恢复**：新增 SQLite 迁移 `migrations/008_graph_build_jobs.sql`，记录每次构建的状态与进度；启动时 `mark_interrupted_build_jobs()` 自动将前次中断任务标为 `interrupted` 并写日志提示；`SourceDocumentStore` 接口与 SQLite / 内存实现均新增 `upsert_build_job / list_build_jobs / mark_interrupted_build_jobs`（`migrations/008_graph_build_jobs.sql`, `core/repository/source_store/base.py`, `core/repository/source_store/sqlite.py`, `core/repository/source_store/memory.py`, `core/api.py`, `core/plugin_initializer.py`）。
- **图谱页断点续建横幅**：图谱就绪面板加载历史任务，若检测到 `status=interrupted` 的记录，展示已处理文档数与续建提示；构建按钮文案切换为「续建知识图谱」；通过 `GET /api/graph/build/history` 获取数据（`web/frontend/app/(console)/graph/page.tsx`, `web/frontend/lib/api.ts`, `web/server.py`, `web/frontend/lib/i18n.ts`）。

### 测试 (Tests)

- **LRAG partial-failure 后仍可查询**：更新 `test_lightrag_context_rejects_pending_collection` 为 `test_lightrag_context_queries_workspace_regardless_of_doc_status`，验证 d1 已索引、d2 失败时查询仍正常到达 LightRAG；新增 `test_lightrag_context_rejects_missing_workspace` 确保 workspace 缺失时仍正确拒绝（`tests/backend/test_retrieval_orchestrator.py`）。

### 构建与工程 (Build/CI)

- **前端产物同步**：运行 Next.js 静态构建并同步 150 个文件至 `pages/`（`web/frontend/`, `pages/`, `tools/sync_frontend.py`）。

## [v0.20.8] — 2026-06-06

### 新增功能 (Added)

- **LightRAG LLM 运行模式显式选择**：新增 `graph.lightrag_llm_provider = main/local/api`，正式插件、配置 schema、能力检测与 Flow 快速配置同步支持；本地 `run_dev_realtime.py` 与 `tests/mock_data/Config/config.example.py` 支持 `LLM_PROVIDER=api/local` 和 `LIGHTRAG_LLM_PROVIDER=main/local/api`，旧的 `LIGHTRAG_LLM_BASE_URL` + `LIGHTRAG_LLM_MODEL` 配置继续按 local 兼容（`core/config.py`, `_conf_schema.json`, `core/plugin_initializer.py`, `core/capabilities.py`, `tests/mocks/run_dev_realtime.py`, `tests/mock_data/Config/config.example.py`, `web/frontend/components/flow/QuickConfigPanel.tsx`, `web/frontend/lib/i18n.ts`）。

### 修复 (Fixed)

- **LightRAG Graph 未就绪状态不再误报即将上线**：`GET /api/graph` 在 LightRAG 未启用、依赖未就绪或 workspace 未构建时返回结构化 `not_ready` 状态；Graph 页据此展示真实原因与构建入口，保留对旧 reserved 响应的兼容但不再将正式功能宣称为未上线（`core/api.py`, `web/server.py`, `web/frontend/app/(console)/graph/page.tsx`, `web/frontend/lib/api.ts`）。

### 测试 (Tests)

- **LightRAG provider 与 not-ready 契约回归**：补充 `graph.lightrag_llm_provider` 默认/显式/旧字段兼容测试，并将 `/api/graph` 未配置 LightRAG 的断言从 reserved 501 调整为 not_ready 200（`tests/backend/test_config.py`, `tests/backend/test_web_server.py`）。

### 构建与工程 (Build/CI)

- **正式前端产物同步**：运行 Next.js 静态构建并通过 `tools/sync_frontend.py` 将 `web/frontend/out/` 同步到 AstrBot 运行时使用的 `pages/`，确保 Graph not-ready UI 与 Flow 快速配置在正式插件中可见（`web/frontend/`, `pages/`, `tools/sync_frontend.py`）。

## [v0.20.7] — 2026-06-06

### 修复 (Fixed)

- **Flow 节点内部滚动条移除**：移除 `.flow-node-body` 与 `.flow-quick-config` 的内部滚动限制，网格行高改为 `minmax(340px, auto)`，让同一行节点按最高内容自动等高对齐，避免节点内部滚动与画布整体移动冲突（`web/frontend/styles/tokens.css`）。
- **Flow 连线标签可读性提升**：放大“默认 / 高精度 / 备份旁路”连线标签字号、粗细和胶囊留白，并保持基于连线中点定位（`web/frontend/styles/tokens.css`）。

## [v0.20.6] — 2026-06-06

### 修复 (Fixed)

- **Flow 背景拖拽误选文字修复**：背景开始 pan 时调用 `preventDefault()`，并在 Flow 画布/world 层禁用文本选择，保留快速配置输入框可编辑，避免长按拖动背景时选中文本导致拖拽卡住（`web/frontend/components/flow/FlowDiagram.tsx`, `web/frontend/styles/tokens.css`）。
- **Flow 节点行高与横屏宽度优化**：拓扑网格改为更宽列宽和统一 `grid-auto-rows`，所有节点单元撑满所在行，减少横屏下文字挤压并保持每行节点高度对齐（`web/frontend/styles/tokens.css`）。
- **Flow 快速配置移除手动最大 Token 项**：删除 `embedding.max_token_size` 的 Flow 节点快速配置字段、Flow 文案和 mock restart 标记，避免把自动适配项暴露为手动参数（`web/frontend/components/flow/QuickConfigPanel.tsx`, `web/frontend/lib/i18n.ts`, `web/frontend/lib/api.ts`）。

## [v0.20.5] — 2026-06-06

### 新增功能 (Added)

- **Flow 节点快速配置**：`/flow` 同时读取 capabilities 与 effective config，在节点卡片内新增 embedding、Milvus auto-index、LightRAG、Sync、Ingest 的紧凑快速配置面板；保存复用 `updateConfigValue(section, key, value)`，逐节点锁定保存状态并按返回的 restart/rebuild 标记复用顶部 banner；API Key、R2/Notion 密钥与结构性 ID 仅显示配置提示，不在 Web UI 输入或保存（`web/frontend/app/(console)/flow/page.tsx`, `web/frontend/components/flow/QuickConfigPanel.tsx`, `web/frontend/components/flow/FlowNode.tsx`, `web/frontend/components/flow/FlowDiagram.tsx`, `web/frontend/lib/api.ts`, `web/frontend/lib/i18n.ts`, `web/frontend/styles/tokens.css`）。

### 修复 (Fixed)

- **Flow 并行分支节点高度对齐**：`retrieval` 与 `graph` 节点使用一致高度基准，保持连接点由真实节点中心重新测量，减少分支视觉高度差对连线稳定性的影响（`web/frontend/components/flow/FlowDiagram.tsx`, `web/frontend/styles/tokens.css`）。

## [v0.20.4] — 2026-06-06

### 修复 (Fixed)

- **Flow 页面首帧闪乱与操作发糊修复**：`FlowDiagram` 在节点测量与首次 fit 完成前隐藏拓扑 world 层，避免进入 `/flow` 时暴露默认 `scale=1,x=0,y=0` 的错误首帧；默认进入视角改为清晰优先，尽量保持参考截图式 100% 视角，仅在小屏放不下时缩小；画布缩放由 `transform: scale()` 改为 CSS `zoom`，并将 fit/拖拽/滚轮缩放产生的平移坐标归整到整数像素，减少文字和节点在操作后被合成缩放导致的发糊（`web/frontend/components/flow/FlowDiagram.tsx`, `web/frontend/styles/tokens.css`）。

## [v0.20.3] — 2026-06-06

### 新增功能 (Added)

- **Flow 页面 Langflow 拓扑重构**：`/flow` 从纵向堆叠流程改为横向固定分支拓扑，`ingest → embedding → vector_store` 后分叉到默认检索与 LightRAG 高精度路径并汇入 Ask，Sync 作为上传旁路；新增可平移/缩放/fit 的画布、节点真实位置测量、贝塞尔连线、端口 handle、ready 流动线与 off 虚线；删除旧 `DependencyPanel`，缺失依赖安装内联到节点；Ask/Sync 使用更显眼的入口节点并分别跳转 `/ask`、`/sync`，Graph 提供 `/graph` 次级入口；保持 `getCapabilities`、`updateConfigValue`、`installDependency`、`recheckDependencies` 网络契约不变（`web/frontend/app/(console)/flow/page.tsx`, `web/frontend/components/flow/`, `web/frontend/styles/tokens.css`, `web/frontend/lib/i18n.ts`）。

### 测试 (Tests)

- **Flow 页面拓扑重构验证**：通过前端类型检查、Next.js 静态构建与 capabilities/API 路由回归，确认新拓扑组件不改变现有能力检测、依赖安装、配置切换网络契约（`npx tsc --noEmit`, `npx -y node@20 node_modules/next/dist/bin/next build`, `python -m pytest tests/backend/test_api.py tests/backend/test_web_server.py -q`）。

## [v0.20.2] — 2026-06-06

### 新增功能 (Added)

- **LightRAG 构建进度升级为 LRAG chunk 级别**：`BuildJob` 新增 `processed_chunks` / `total_chunks` / `progress_basis` / `estimated_remaining_seconds` 等字段，`core/api.py` 在构建前按 LightRAG 等价切分规则生成 LRAG chunk plan，不复用 Milvus `DocumentChunk`；Graph/Ask 页优先展示 `LRAG chunk x / n`、真实已运行时间与动态剩余时间（`core/api.py`, `core/lightrag_core.py`, `web/frontend/lib/api.ts`, `web/frontend/app/(console)/graph/page.tsx`, `web/frontend/app/(console)/ask/page.tsx`）。
- **Terminal 结构化事件流**：内存日志新增 `category` / `source` / `operation` / `status` / `metadata` 字段，新增 `POST /api/logs/events` 接收前端 toast 事件；Terminal 页支持 graph/llm/embedding/retrieval/web/toast/system 等分类过滤（`core/log_capture.py`, `web/server.py`, `web/frontend/app/(console)/terminal/page.tsx`, `web/frontend/components/ui/Toast.tsx`）。

### 修复 (Fixed)

- **本地 phi4/LM Studio 图谱构建过早超时**：`LMStudioLLMAdapter` 的 `180s` 硬编码超时改为 `GraphConfig` 可配置的 `lightrag_llm_timeout_seconds`，并增加 `lightrag_llm_max_retries` 与 `lightrag_llm_retry_backoff_seconds`；LightRAG 实例同步设置 `default_llm_timeout`，避免本地慢推理被提前中断（`core/adapters/llm.py`, `core/config.py`, `core/plugin_initializer.py`, `_conf_schema.json`）。
- **图谱构建耗时估算过于乐观**：`estimate_lightrag_build()` 改为按每篇文档估算 LRAG chunk，并区分 local/remote runtime profile 与每 chunk 秒数配置，修正旧公式对文档数的重复放大/压缩问题（`core/lightrag_core.py`, `core/api.py`, `tests/backend/test_lightrag_core.py`）。

### 测试 (Tests)

- 新增覆盖 LRAG chunk plan、chunk 级 build job 进度、本地耗时估算和 toast 日志事件端点的测试（`tests/backend/test_lightrag_core.py`, `tests/backend/test_api.py`, `tests/backend/test_web_server.py`）。

## [v0.20.1] — 2026-06-05

### 架构健康 (Refactor)

- **LightRAG 索引路径与 Milvus chunk 路径分离**：`_run_lightrag_build_job` 新增优先从 `SourceDocument.file_path` 重提取原始文本（PDF 用 fitz 逐页提取，txt/md 直接读文件），避免将 Milvus 预切 chunk 重新拼接后二次分块的 overhead；fitz 未安装或文件不可读时自动降级到原有 chunk 拼接路径，完全向后兼容；新增模块级纯函数 `_extract_raw_doc_text(doc)` 封装提取逻辑（`core/api.py`）。

## [v0.20.0] — 2026-06-05

### 新增功能 (Added)

- **知识库检索前后文窗口**：`GET /api/kb/search` 现在为每个命中 chunk 内联返回 `context_before` / `context_after`（ordinal ±2 相邻 chunk），Search 页结果卡片三段式展示（前文弱化 → 命中高亮 → 后文弱化）；新增 `GET /api/kb/chunk-context?doc_id=&chunk_id=&window=` 端点供按需独立获取（`core/api.py`、`web/server.py`、`web/frontend/lib/api.ts`、`web/frontend/app/(console)/search/page.tsx`）。
- **引用来源 → 展开显示上下文**：SourcesPanel 中每个来源卡片可点击展开，异步调用 `getChunkContext()` 加载前后文，命中段落加粗，展开区域含 spinner 加载指示（`web/frontend/app/(console)/ask/page.tsx`）。
- **图谱页空态 CTA**：无图谱时主视图中央显示大尺寸「预估并构建知识图谱」主操作区，代替原来的小字提示（`web/frontend/app/(console)/graph/page.tsx`）。
- **图谱页侧边栏双 Tab**：「详情」Tab 保留节点/边信息，「图谱查询」Tab 包含原来底部的查询表单，功能组织更清晰（`web/frontend/app/(console)/graph/page.tsx`）。

### 修复 (Fixed)

- **知识库检索不可用**：Search 页改用 `listCollections()`（而非 `listKbCollections()`）初始化集合列表，解决非 AstrBot 环境下集合为空导致搜索按钮无效的问题（`web/frontend/app/(console)/search/page.tsx`）。
- **图谱页一直加载中**：`listCollections()` 调用加 5s `Promise.race` 超时保护，超时后仍调用 `loadGraph()` 清除初始 `loading: true` 状态（`web/frontend/app/(console)/graph/page.tsx`）。
- **图谱构建进度不可见**：buildJob 状态行改为带动态进度条的组件，`processed_docs / total_docs` 实时更新；构建成功后显示提取的实体/关系数量（`web/frontend/app/(console)/graph/page.tsx`）。

### 架构健康 (Refactor)

- **引用来源绑定当前查看消息**：`sources` state 替换为 `selectedMsgIndex`（`number | null`）+ 派生的 `displayedSources`；点击 assistant 气泡触发白色辉光动画（2圈）并切换来源面板内容；SourcesPanel 关闭 X 按钮改为点击即收起的折叠 bar（`web/frontend/app/(console)/ask/page.tsx`）。
- **RA 顶部栏精简**：移除「Research Agent」标题文字，直接展示 `Milvus · 本地 Embedding · 注入增强` 状态行；集合选择持久化至 `localStorage("kr_ask_collection")`，切换页面后恢复上次选择（`web/frontend/app/(console)/ask/page.tsx`）。
- **输入框焦点辉光统一化**：移除 `.ask-card:focus-within` 的橙色 `border-color` + `box-shadow` ring；新增 `:not(.ask-card--loading):focus-within::before` 轨道辉光（1.8s/圈，亮白混橙，扩散半径更大）与 loading 辉光视觉统一；新增 `.msg-bubble--glow` 白色辉光动画类（`web/frontend/app/globals.css`）。
- **图谱构建按钮显著化**：无图谱时工具栏按钮切换为 `variant="primary"` 并改文字「预估并构建知识图谱」（`web/frontend/app/(console)/graph/page.tsx`）。
- **移除文档页手动索引入口**：删除 auto-index toggle 按钮和手动「重建索引」按钮（Milvus auto-index 始终开启），清理相关 state 和废弃 import（`rebuildIndexPending`、`getPendingReindexCount`、`updateConfigValue`）（`web/frontend/app/(console)/documents/page.tsx`）。
- **搜索页图谱 tab 移除**：`/search` 页完全专注于向量检索；图谱检索功能已整合至 `/graph` 侧边栏「图谱查询」Tab（`web/frontend/app/(console)/search/page.tsx`）。
- **预先存在的 E501 lint 修复**：修正 `core/api.py`（翻译 prompt 换行）、`core/plugin_initializer.py`（Milvus 状态检查）、`core/repository/source_store/sqlite.py`（SQL INSERT 换行）的超长行。

## [v0.19.1] — 2026-06-04

### 新增功能 (Added)

- **Search 页图谱检索 tab**：在 `/search` 页新增第三个 tab「图谱检索」，调用已有的 `GET /api/graph/query` 端点，将 LightRAG 返回的 answer、entities、relations 以结构化卡片展示；与向量检索 tab 并列，方便直接对比两种召回路径的结果差异；共享 collection 下拉选择器（`web/frontend/app/(console)/search/page.tsx`）。
- **Graph 页实体搜索浮层**：在图谱画布左上角新增实体名称搜索输入框，输入时对已加载的 `nodes` 做前端模糊过滤（最多显示 8 条），点击结果直接聚焦并高亮对应节点及其邻居；支持 × 一键清空，无需新增后端接口（`web/frontend/app/(console)/graph/page.tsx`）。
- **Graph 页构建完成后显示实体/关系数量**：LightRAG 构建任务状态栏在 `status === "success"` 时追加「已提取 N 个实体，M 条关系」，数据来自构建完成后自动刷新的图谱快照（`web/frontend/app/(console)/graph/page.tsx`）。
- **LightRAG 连通性探针**：`run_dev_realtime.py` 在创建 Deepseek 适配器后立即执行 1 次轻量 LLM API 调用（Phase 7.1），验证 DEEPSEEK_API_KEY / LLM_API_URL / LLM_MODEL 三项配置可达；失败时立即打印错误并退出，防止用户等到构建阶段才发现密钥错误；启动 banner 新增 LightRAG 测试操作路径说明（`tests/mocks/run_dev_realtime.py`）。

### 测试 (Tests)

- **LightRAG API 层覆盖补充**：在 `tests/backend/test_api.py` 新增 6 个测试，覆盖此前缺失的路径：`get_lightrag_readiness()` 全通路（ready=True）、部分已索引状态（partial indexed）、`build_graph(confirmed=False)` 的 ValueError guard、insert 抛异常导致 `partial_failure`、`probe_lightrag_core()` 委托传参、`query_graph()` 委托 registry 并验证返回。
- **LightRAG 核心层单元测试补充**：在 `tests/backend/test_lightrag_core.py` 新增 2 个测试：`has_workspace()` 的 True/False 检测（基于文件系统目录），以及 `manual_probe()` 在 `get()` 初始化失败时返回 `{"status": "error"}` 并记录 steps。

---

## [v0.19.0] — 2026-06-04

### 新增功能 (Added)

- **Ask 聊天记录持久化**：新增 `migrations/007_chat_history.sql` 表，每次 ask() 成功后自动将用户问题与 LLM 回答（含来源、召回模式）写入 SQLite；Ask 页加载时从 `localStorage` 读取 `conversation_id` 并拉取历史恢复对话；"新对话"按钮调用 `DELETE /api/chat/history` 清除 DB 记录并生成新 ID（`migrations/007_chat_history.sql`, `core/repository/source_store/base.py`, `core/repository/source_store/sqlite.py`, `core/repository/source_store/memory.py`, `core/api.py`, `web/server.py`, `web/frontend/lib/api.ts`, `web/frontend/app/(console)/ask/page.tsx`）。
- **Ask 查询设置新增「使用英语召回」与「回答语言」**：用 LLM 将中文问题翻译为英语后再送入 embedding，提升英语文档向量召回精度（默认开启）；新增强制 LLM 用中文/英文/自动回答的三档语言选项，替代原"与问题同语言"自动逻辑（`core/api.py`, `web/server.py`, `web/frontend/lib/api.ts`, `web/frontend/app/(console)/ask/page.tsx`）。
- **本地集成测试脚本**：新增 `tests/mocks/run_dev_realtime.py`，使用真实 Milvus Lite + LightRAG + Deepseek API 在端口 6521 启动测试 WebUI，直接从 `tests/mock_data/Brian Massumi/` 读取 PDF 播种数据，绕开 IngestManager；新增 `tests/mocks/reset_dev_realtime.py` 一键归档/清理测试数据；新增 `tests/mock_data/Config/config.example.py` 配置模板；相关文件全部入 `.gitignore`（`tests/mocks/`, `tests/mock_data/Config/config.example.py`, `.gitignore`）。

### 修复 (Fixed)

- **终端日志不显示问题**：`core/plugin_initializer.py` 在 `initialize()` 第一行即调用 `log_capture.install()`，使嵌入探针、Milvus 初始化等启动日志能被终端页捕获；末尾输出组件激活摘要，Milvus 未激活时发出 WARNING；`tests/run_webui.py` 同步提前安装 handler（`core/plugin_initializer.py`, `tests/run_webui.py`）。
- **日志噪声过滤**：扩展 `MemoryLogHandler._SKIP_PREFIXES`，新增 `httpx`、`httpcore`、`hpack`、`charset_normalizer`、`urllib3`、`asyncio` 前缀，消除第三方库 DEBUG 日志刷屏（`core/log_capture.py`）。
- **重建索引错误静默问题**：`handle_rebuild_index_pending` 异常捕获从 `RuntimeError` 扩展为 `Exception` 并加 `exc_info=True`；前端 `handleRebuildIndex` 将 `catch {}` 改为 `catch (err) {}` 并在 toast 显示 `ApiError.message`（原为通用"请重试"）；RuntimeError 消息中文化并指向正确操作（`core/api.py`, `web/server.py`, `web/frontend/app/(console)/documents/page.tsx`）。
- **重建索引进度日志**：`rebuild_index_pending()` 新增"N 个文档待重建"与逐文档"嵌入 N chunks"进度日志；`MilvusLiteVectorStore.upsert_chunks` 添加 INFO 级日志（`core/api.py`, `core/repository/vector_store/milvus_lite.py`）。
- **Ask 查询设置 dropdown 点击失效**：原 `document.addEventListener("mousedown")` 与 React 18 事件委托同层导致 `stopPropagation` 无效，改为 `refs.contains(target)` 检测点击是否在组件内，彻底修复设置项无法交互的问题（`web/frontend/app/(console)/ask/page.tsx`）。
- **聊天记录加载可靠性**：历史拉取从主 `useEffect([])` 拆出至独立 `useEffect([conversationId])`，用 `historyLoadedRef` 防重复加载，`.catch(() => {})` 改为 `.catch(console.error)` 不再静默吃错误（`web/frontend/app/(console)/ask/page.tsx`）。

### 架构健康 (Refactor)

- **Ask 页底部工具栏重设计**：设置按钮移至左侧并改为齿轮图标；原"三横线"图标删除；集合选择按钮始终展示当前选中集合名（无选择时显示"全部"）；"使用英语召回"和"回答语言"归入设置 dropdown（此前错误放在工具栏裸露），高精度召回改名为"LightRAG 召回"；checkbox 全部替换为 iOS 风格 toggle 开关组件 `SettingRow`；删除顶部水平召回进度条 `RetrievalProgress`（`web/frontend/app/(console)/ask/page.tsx`, `web/frontend/app/globals.css`）。
- **Ask 输入框辉光动画**：新增 `@property --ask-beam-angle` + `@keyframes askBeamOrbit`，加载时边框辉光弧形绕 `ask-card` 轨道旋转（1.5s/圈，双层 `drop-shadow`，宽弧形渐入），无 `@keyframes` 以外的 JS 依赖（`web/frontend/app/globals.css`）。

### 构建与工程 (Build/CI)

- 前端所有变更均通过 `npm run build && python tools/sync_frontend.py` 同步至 `pages/`（`pages/`）。

---

## [v0.18.1] — 2026-06-04

### 修复 (Fixed)

- **LightRAG 内存缓存脏数据泄露修复**：在重置工作区时不仅清空磁盘目录，还对所有 JsonKVStorage 和 JsonDocStatusStorage 的全局共享内存缓存执行 drop() 抛弃脏缓存，防止进程内图谱重建时静默跳过实体提取（`core/lightrag_core.py`）。

## [v0.18.0] — 2026-06-04

### 新增功能 (Added)

- **数据流 / 配置向导页**：新增独立 WebUI 页面 `/flow`，把「上传 → 向量化 → 向量库 → 检索 → 图谱 → 问答 → 同步」七环节绘成分步流程图，每个节点带 TODO 式状态徽章（就绪/待处理/可选关闭），展示当前后端与生效引擎，并可在节点内按需切换后端（embedding provider / vector_db backend / graph enabled / ask mode），切换后明确提示需重启或重建索引（`web/frontend/app/(console)/flow/page.tsx`, `web/frontend/components/rail/Rail.tsx`, `web/frontend/lib/i18n.ts`, `web/frontend/lib/api.ts`）。
- **可选依赖一键安装与管理**：新增 `/api/capabilities`、`/api/dependencies`、`/api/dependencies/install`、`/api/dependencies/recheck` 接口；flow 页依赖面板展示 `requirements-additional.txt` 各包（pymilvus / sentence-transformers / lightrag-hku / boto3）的安装状态与版本，可一键 `pip install`（仅白名单包、防注入），安装输出实时写入终端日志，完成后提示重启插件并附 Docker 持久化提醒（`core/capabilities.py`, `core/api_capabilities.py`, `web/server.py`）。
- **数据流非机密开关可运行时切换**：`r2_sync.enabled`、`notion_sync.enabled`、`source_store.ocr_enabled` 纳入可经 `/api/config/update` 写入的键（机密仍仅经环境变量注入）（`core/config.py`, `core/runtime_config.py`, `core/api.py`）。

### 架构健康 (Refactor)

- **系统能力单一真相源**：新建 `core/capabilities.py` 作为「可选依赖是否安装 + 各数据流环节当前后端/就绪/切换后果」的唯一来源，消除 `config.py` 与 `plugin_initializer.py` 中重复的 `_module_available` 实现，并取代前端对诊断字符串的子串匹配（`core/capabilities.py`, `core/config.py`, `core/plugin_initializer.py`）。
- **可写配置键登记收敛**：在 `core/config.py` 建立 `CONFIG_KEY_POLICY` 单一登记表，`api._CONFIG_UPDATE_KEYS`/`_STRUCTURAL_KEYS` 与 `runtime_config._ALLOWED_RUNTIME_KEYS` 改为派生，restart/rebuild 后果统一由登记表 `consequence` 计算，消除三处重复（`core/config.py`, `core/api.py`, `core/runtime_config.py`）。
- **业务门面初步拆分**：抽出 `core/api_capabilities.py::CapabilitiesApiMixin`，确立按职责拆分巨型 `KnowledgeRepositoryApi` 的 mixin 范式；documents/retrieval/graph/sync 子门面与 `plugin_initializer` 分阶段化登记 TODO v0.18.0 Phase 3b 跟进（`core/api.py`, `core/api_capabilities.py`）。

### 测试 (Tests)

- 新增 `tests/backend/test_capabilities.py`（环节状态机、依赖清单、安装白名单防注入）；`tests/backend/test_web_server.py` 新增 capabilities/dependencies 路由与「拒绝白名单外包名」测试；调整 `test_config_update_route` 以反映 `r2_sync` 节开放 `enabled` 后机密键改由键白名单拒绝（`tests/backend/test_capabilities.py`, `tests/backend/test_web_server.py`）。

### 构建与工程 (Build/CI)

- 前端构建产物同步至 `pages/`（新增 `/flow` 静态路由）（`pages/`, `tools/sync_frontend.py`）。

## [v0.17.0] — 2026-06-04

### 新增功能 (Added)

- **Milvus 默认召回与按需高精度模式**：新安装默认使用 Milvus；Web Research Agent 可在指定 collection 中显式启用 `Milvus chunks + LightRAG context` 高精度召回，并由外层 LLM 单次生成最终答案。回答气泡展示实际召回方式，LightRAG 未就绪时可查看构建预估、构建后自动续问或仅本次使用默认召回（`core/api.py`, `core/pipelines/retrieval_orchestrator.py`, `web/frontend/app/(console)/ask/page.tsx`）。
- **Embedding 运行时真值与索引兼容性**：新增顶层 `embedding` 配置、真实向量维度探针和持久化索引指纹；Milvus 与 LightRAG 在 provider/model/base URL/实际维度变化后拒绝静默复用旧索引（`core/config.py`, `core/index_compatibility.py`, `core/plugin_initializer.py`）。
- **设置页 LightRAG Core 参数问号说明**：新增可复用 `HelpTip` 问号角标组件，为设置页 LightRAG Core 区的「启用图谱索引 / 检索模式 / LLM 并发上限 / Embedding 并发上限 / 工作目录（只读）」5 个设置项各加一个悬停/聚焦/点击即显的中英文解释气泡，降低非专家用户的理解门槛（`web/frontend/components/ui/HelpTip.tsx`, `web/frontend/app/(console)/settings/page.tsx`, `web/frontend/lib/i18n.ts`）。

### 修复 (Fixed)

- **AstrBot 插件安装被大型 PyTorch/CUDA 下载中断修复**：根 `requirements.txt` 仅保留 PDF 上传、SQLite 基础召回与 Web 控制台所需轻量依赖；Milvus、本地 Embedding、LightRAG、R2 与开发工具统一放入手动安装的 `requirements-additional.txt`，避免 AstrBot 自动安装 `sentence-transformers` 时继续拉取超大 `torch`/CUDA wheel（`requirements.txt`, `requirements-additional.txt`, `.github/workflows/tests.yml`）。
- **缺少可选依赖时的启动降级**：未安装本地 Embedding、Milvus、LightRAG 或 boto3 时插件继续启动，默认上传与 AstrBot/SQLite 基础召回保持可用，并通过 diagnostics 指明对应安装文件；R2 改为调用时懒加载 boto3（`core/config.py`, `core/plugin_initializer.py`, `core/repository/sync_targets/r2.py`）。
- **Milvus 生命周期一致性**：启动时前置校验依赖与 collection schema，维度冲突或 `pymilvus` 不可用时受控回退 AstrBot；写入与查询严格校验向量维度，文档移动集合时同步更新 Milvus collection 映射（`core/repository/vector_store/milvus_lite.py`, `core/api.py`）。
- **Discord 问答路径确定化**：Discord `query_agent` 始终走默认召回，不再自动调用 LightRAG；`/kr agent on` 明确提示高精度模式仅在 Web Research Agent 提供（`core/event_handler.py`）。
- **AstrBot 对话增强 hook 修复**：`inject` 改由官方 `on_llm_request` hook 写入 system prompt；`query_agent` 直接返回答案，不再依赖 AstrBot LLM 遵循转述指令（`main.py`, `core/event_handler.py`）。
- **首次安装基础上传与召回可用性**：初始化时在缺失时创建配置指定的默认 collection，避免首次上传触发外键错误且不覆盖存量描述；Embedding/Milvus 不可用时继续保存 PDF 与 SQLite 分块，并增强中文无空格查询的词汇召回（`core/plugin_initializer.py`, `core/pipelines/retrieval_orchestrator.py`）。
- **Web 上传原件单副本存储**：Web 上传改用 `uploads/` 临时目录，成功摄入后仅保留 `documents/{doc_id}.pdf` 托管原件，失败时清理暂存文件（`core/plugin_initializer.py`, `web/server.py`）。

### 架构健康 (Refactor)

- **删除旧 GraphStore 体系并收敛 Ask 数据流**：删除旧 GraphStore、GraphBuild/GraphSearch pipeline 与专属领域类型；LightRAG 独立图谱接口保留完整回答，统一 Ask 仅按需获取 context，避免双答案生成（`core/repository/graph_store/`, `core/pipelines/`, `core/domain/models.py`, `core/lightrag_core.py`）。
- **Embedding 配置分组迁移**：`vector_db` 仅保留后端与索引开关，`graph` 仅保留 LightRAG 专属设置；旧字段继续兼容读取并输出迁移 diagnostics，API Key 仅从 `KR_EMBEDDING_API_KEY` 读取（`_conf_schema.json`, `core/config.py`, `core/runtime_config.py`, `web/frontend/app/(console)/settings/page.tsx`）。
- **AstrBot 消息职责拆分与设置页风格统一**：`on_message` 与 `on_llm_request` 分离；LightRAG 查询模式继续使用项目自定义 `Select` 组件（`core/event_handler.py`, `main.py`, `web/frontend/app/(console)/settings/page.tsx`）。
- **首次安装默认参数与设置页收敛**：默认本地模型切换为轻量多语言 `intfloat/multilingual-e5-small`，设置页在现有设计语言内明确区分默认 Milvus/SQLite 基础召回与可选 LightRAG 高精度路径，并展示运行时 diagnostics（`core/config.py`, `_conf_schema.json`, `web/frontend/app/(console)/settings/page.tsx`）。

### 测试 (Tests)

- 新增 context-only LightRAG 查询、单次外层 LLM、仅图谱上下文、真实探针维度、探针失败降级、首次安装 PDF 摄入/中英文词汇召回、Web 暂存清理、Milvus schema 冲突、索引指纹失效与结构化 HTTP 错误覆盖；AstrBot KB reader 测试对齐 v4 `list_kbs/retrieve` 契约（`tests/backend/`）。

### 构建与工程 (Build/CI)

- 将基础 PDF 摄入所需 `PyMuPDF` 纳入运行时核心依赖，并记录默认 Milvus/本地 Embedding 与 SQLite 降级行为（`requirements.txt`）。
- 新增扩展功能安装手册与单一 `requirements-additional.txt`；设置页和原生配置 Schema 明确基础安装、Milvus 首选配置及各可选运行时的边界（`docs/OPTIONAL_DEPENDENCIES.md`, `README.md`, `_conf_schema.json`, `web/frontend/app/(console)/settings/page.tsx`）。

## [v0.16.1] — 2026-06-04

### 修复 (Fixed)

- **`embedding_provider='astr'` 导致插件整体崩溃修复**：`graph.enabled=true` 时若 embedding provider 配置为未实现的 `'astr'`，`NotImplementedError` 不加捕获直接向上传播，致使插件初始化失败、整体不可用。现在在 `plugin_initializer.py` 中加 try/except 降级：provider 创建失败时仅禁用图谱/向量检索功能并打印警告，插件主体（问答、文档管理、CLI 等）照常运行（`core/plugin_initializer.py`）。
- **lightrag-hku 安装失败修复**：`==1.5.0` 在阿里云 PyPI 镜像尚未同步，改为 `>=1.5.0rc1,<2.0.0`；`1.4.x` 与 AstrBot 核心依赖 `google-genai==2.7.0` 冲突（`<2.0.0` vs `==2.7.0`），`1.5.0rc3+` 已放宽至 `<3.0.0` 不再冲突（`requirements.txt`）。
- **插件热重载后 `on_llm_request` AttributeError 修复**：`_purge_stale_local_modules()` 原仅清理其他插件的 `core.*` 缓存，本插件自身旧版 `EventHandler`（不含 `on_llm_request`）在重载后仍留在 `sys.modules`，导致每条消息报 `AttributeError`。改为无条件清除所有 `core.*`/`web.*`/`migrations.*` 模块，重载时强制从磁盘重新导入（`main.py`）。
- **Web 控制台配置保存报"api_key 机密字段"修复**：前端保存设置时将所有字段一并发送，空的 `api_key` 字段被拦截导致保存失败。写保护条件改为 `key in _SECRET_KEYS and value`，仅拦截非空机密值（`core/api.py`）。
- **文档上传 Internal Server Error 无错误信息修复**：`handle_upload_document` 对 `register_document` 的调用无 try/except，任何异常（PDF 解析失败、路径错误等）均变成 aiohttp 裸 500，前端不知原因，dashboard 无日志。新增 try/except 捕获后返回含具体错误信息的 JSON 并通过 `KRWebServer` logger 输出完整 traceback（`web/server.py`）。

### 新增功能 (Added)

- **全局 HTTP 错误中间件**：新增 `_error_middleware`，置于中间件链最外层。所有 handler 内未被捕获的 `Exception` 统一转为 `{"error": "..."}` 的 JSON 500 响应，并经 `KRWebServer` logger 输出完整 traceback（在 AstrBot dashboard 可见）。原有 23 个缺少 try/except 的 handler 一次全部覆盖（`web/server.py`）。
- **结构性配置字段写保护**：`update_config_value` 新增 `_STRUCTURAL_KEYS` 黑名单：`graph.embedding_dim`、`graph.max_token_size`、`graph.working_dir`、`vector_db.db_filename`。这些字段运行时修改会静默破坏已有向量/图谱索引，现在写入时返回 400 并提示需手动改配置文件后重启（`core/api.py`）。

### 架构健康 (Refactor)

- **AstrBotKnowledgeBaseReader 接口对齐修复**：原实现调用 `context.kb_manager.search()`，该方法在 AstrBot v4 中不存在（实际为 `KnowledgeBaseManager`，暴露 `list_kbs()` + `retrieve(query, kb_names, ...)`），导致 `vector_db.backend='astr'` 配置下检索永远返回空列表、inject 模式静默无效。重写 `search()` 和 `list_collections()`：`list_kbs()` 枚举 AstrBot KB，`retrieve()` 调用正确的 FAISS+FTS5+RRF 融合检索，collection 优先映射到同名 KB，不存在则搜索全部 KB（`core/repository/kb_reader/astrbot.py`）。
- **日志策略优化——用户触发操作终端可见性**：确立日志哲学：写/变更操作记入口+结果，只读/轮询不记（降噪）。具体改动：① `handle_update_config` 新增入口 INFO、成功 INFO、拒绝 WARNING（此前配置保存失败 dashboard 完全空白）；② `handle_rebuild_index_pending` 新增入口 INFO、完成 INFO、失败 ERROR；③ `handle_upload_document` 新增入口 INFO（文件名/大小/集合）；④ `handle_delete_document`、`handle_graph_build`、`handle_sync` 新增入口 INFO；⑤ `update_config_value` 新增入口 INFO + 持久化成功 INFO；⑥ `ingest()` 新增入口 INFO（`web/server.py`, `core/api.py`, `core/managers/ingest_manager.py`）。

- **lightrag-hku 1.5.0 API 兼容性加固**：`insert_document` 捕获并记录 `ainsert` 在 1.5.0 新增的 `track_id` 返回值；`delete_doc` 结果解析改为 `getattr` 取 `.status`/`.message`，兼容 1.5.0 `DeletionResult` 对象与 1.4.x 旧返回类型（`core/lightrag_core.py`）。

## [v0.16.0] — 2026-06-03

### 新增功能 (Added)

- **官方 LightRAG Core 单后端接入**：新增按 collection 隔离 workspace 的 `LightRAGCoreRegistry`、严格真实 LLM/Embedding adapter、显式 KR `doc_id` 插入、查询、真实 CSV 导出解析与 `adelete_by_doc_id` 删除路径（`core/lightrag_core.py`, `core/api.py`, `core/plugin_initializer.py`）。
- **手动确认构建与进度**：新增 dry-run estimate、`confirmed=true` 构建门槛、后台 build job 轮询、部署后真实探针及可读 terminal 输出（`web/server.py`, `docs/LIGHTRAG_DEPLOYMENT_PROBE.md`）。
- **独立 LightRAG 索引状态**：新增 `lightrag_index_status`，以 KR `doc_id` 跟踪 pending/indexed/error，不复用 `needs_reindex`（`migrations/006_lightrag_index_status.sql`, `core/repository/source_store/*`）。
- **LightRAG WebUI**：图谱页新增成本估算确认、免责声明、job 进度、answer/context 展示；文档删除/移动提示索引影响；设置页新增 LightRAG Core 参数区（`web/frontend/`）。

### 架构健康 (Refactor)

- **移除旧图谱生产装配**：组合根不再装配 `SQLiteGraphStore`、旧 GraphBuild/GraphSearch pipeline；CLI build 改为无 LLM 的 estimate-only 输出（`core/plugin_initializer.py`, `core/event_handler.py`）。

### 测试 (Tests)

- 新增 workspace sanitize、build estimate、官方导出 CSV 解析和新 HTTP 契约覆盖；旧图谱 pipeline 测试标记为 v0.16 已替换（`tests/backend/`）。

### 构建与工程 (Build/CI)

- 新增 `lightrag-hku` 核心依赖，不启用 `[api]` extra；版本同步至 `v0.16.0`（`requirements.txt`, `metadata.yaml`, `_conf_schema.json`）。


### 新增功能 (Added)

- **Web 控制台自动启动接线**：`core/plugin_initializer.py` 新增 `_start_web_console()` 私有方法与 `_web_runner` 实例变量；`initialize()` 步骤 7 读取 `web_console` 配置，若 `enabled=true` 且 `password` 非空则自动以 aiohttp `AppRunner` + `TCPSite` 启动 Web 控制台服务器（静态文件指向插件 `pages/` 目录，上传目录复用 `data_dir/documents`）；`teardown()` 补充 `runner.cleanup()` 优雅关闭。密码为空或端口占用时仅 log error，不影响插件主体运行。涉及 `core/plugin_initializer.py`。

### 架构健康 (Refactor)

- **枚举型配置字段改为选项**：`_conf_schema.json` 中三个值域固定的字段补充 `options` 数组，AstrBot 配置 UI 将渲染为下拉框，防止拼写错误静默失效。涉及字段：`vector_db.backend`（`astr` / `milvus`）、`vector_db.embedding_provider`（`local` / `external` / `astr`）、`ask.conversation_enhancement_mode`（`inject` / `query_agent`）。涉及 `_conf_schema.json`。

### 修复 (Fixed)

- **`api_key` 可经 Web API 明文持久化漏洞修复**：`core/runtime_config.py` 的 `_ALLOWED_RUNTIME_KEYS["vector_db"]` 中移除 `"api_key"`，切断通过 `RuntimeConfigStore.set_value` 将 embedding API Key 写入明文 JSON 文件的路径；同时在 `core/api.py` 的 `update_config_value` 新增 `_SECRET_KEYS` 显式拦截层（含 `api_key / secret_access_key / access_key_id / password`），命中后返回 400 并提示改用环境变量，形成双重防护。涉及 `core/runtime_config.py`、`core/api.py`。

- **Embedding 错误日志脱敏**：`core/repository/embedding/external.py` HTTP 错误日志不再记录 API 响应体（`err_text` 可能含鉴权失败详情），仅保留 HTTP 状态码；异常对象仍携带完整信息供上层处理。涉及 `core/repository/embedding/external.py`。

---

## [v0.15.1] — 2026-06-02

### 修复 (Fixed)

- **`fitz`（PyMuPDF）模块顶层无条件 import 消除**：将 `import fitz` 从 `core/managers/ingest_manager.py` 顶层移入 `_extract_and_chunk()` 方法体，用 `try/except ImportError` 包裹并抛出带安装指引的友好 `RuntimeError`。修复后即使 PyMuPDF 安装失败，插件主体仍可正常加载，仅在实际调用文档摄入时才触发错误。涉及 `core/managers/ingest_manager.py`。

- **`_conf_schema.json` `vector_db.db_filename` 默认值同步**：将 schema 中该字段的默认值由遗留的 `"milvus_lite.db"` 更新为 `"vector_store.db"`，与 v0.15.0 对 `core/config.py` 的修正保持一致，消除 AstrBot 原生插件配置 UI 显示旧默认值的混淆。涉及 `_conf_schema.json`。

- **`_conf_schema.json` 补充 `auto_index_enabled` 字段**：v0.15.0 在 `core/config.py` 新增了 `vector_db.auto_index_enabled` 配置项，但未在 `_conf_schema.json` 中声明，导致该字段在 AstrBot 原生插件配置 UI 中不可见。本版本补充该字段（bool，default `true`）至 `vector_db` section。涉及 `_conf_schema.json`。

- **同步目标 disabled 时返回状态语义修正**：当所有文档同步均失败（如同步目标 R2/Notion 未启用）时，`SyncPipeline.sync()` 之前错误地返回 `{"status": "success", "failed_count": N}`，语义误导。现在全部失败时返回 `status: "error"`，部分失败时返回 `status: "partial_failure"`。涉及 `core/pipelines/sync_pipeline.py`。

### 测试 (Tests)

- **Milvus Lite 集成测试 CI 修复**：`test_milvus_lite_vector_store_lifecycle` 在 CI 环境（未安装 `pymilvus`）下因 `ModuleNotFoundError` 失败。为该测试添加 `pytest.mark.skipif(not pymilvus_available, ...)` 检测，使其在无 `pymilvus` 的环境中优雅跳过。涉及 `tests/backend/test_retrieval_orchestrator.py`。

---

## [v0.15.0] — 2026-06-02

### 新增功能 (Added)

- **集合删除确认弹窗与文档安全迁移**：删除集合时弹出模态框，要求用户手动输入集合名称才可确认；非空集合删除前自动将文档迁入系统集合 `_uncategorized`，防止数据丢失。涉及 `web/frontend/app/(console)/documents/page.tsx`（`DeleteCollectionModal` 组件、侧边栏悬停删除按钮）。

- **`_uncategorized` 系统集合（未归档）**：新增受保护的系统集合，集合删除时文档自动迁入；前端侧边栏以收件箱图标+「未归档」标签区别展示，置于普通集合之上；不可通过 UI 删除。涉及 `core/api.py`（`SYSTEM_COLLECTION_UNCATEGORIZED` 常量、`_ensure_system_collections()`、改写 `delete_collection()`）、`core/repository/source_store/base.py`（新增 `move_documents_to_collection` 抽象方法）、`sqlite.py`、`memory.py`、`web/server.py`（`_collection_dict` 增加 `is_system` 字段、`handle_delete_collection` 返回 400 拦截系统集合）、`web/frontend/lib/api.ts`（`Collection.is_system`）。

- **延迟索引模式（索引维护模式）**：新增 `auto_index_enabled` 配置项；关闭后文档上传仅写入 SQLite，跳过 embedding 步骤，并标记 `needs_reindex=True`；工具栏新增「自动索引/索引暂停」toggle 与「重建索引」按钮（附待索引数 badge）；手动触发后批量 embedding 并清除标记。涉及 `migrations/005_needs_reindex.sql`（新文件）、`core/domain/models.py`（`needs_reindex` 字段）、`core/config.py`（`auto_index_enabled` 字段）、`core/runtime_config.py`（白名单扩展）、`core/repository/source_store/sqlite.py`（全量 SQL 适配、`list_pending_reindex_documents()`）、`core/api.py`（`register_document` 检查开关、`rebuild_index_pending()`、`get_pending_reindex_count()`）、`web/server.py`（两条新路由）、`web/frontend/lib/api.ts`（`rebuildIndexPending()`、`getPendingReindexCount()`）、`web/frontend/app/(console)/documents/page.tsx`。

- **响应式面板布局**：为文档页左侧边栏和右侧检查器面板引入 CSS 自定义属性 `--sidebar-left-w` / `--inspector-w`，在 ≤1100px 时收窄、≤860px 时自动隐藏，中列加 `minWidth: 200` 防止内容区过度压缩。涉及 `web/frontend/styles/tokens.css`、`web/frontend/app/(console)/documents/page.tsx`（`data-panel` 属性）。

### 修复 (Fixed)

- **`VectorDbConfig.db_filename` 默认值语义错误**：新安装的默认向量库文件名由 `milvus_lite.db` 更正为 `vector_store.db`，更具通用性；存量安装的已持久化配置不受影响。涉及 `core/config.py`。

### 架构健康 (Refactor)

- `web/frontend/lib/i18n.ts` 新增 12 个国际化键（集合删除、索引模式系列），保持中英双语对齐。

---

## [v0.14.0] — 2026-06-01

### 新增功能 (Added)

- **NotebookLM 风格引用定位元数据与定位能力**：
  - 在 `core/domain/models.py` 的 `DocumentChunk` 中新增了 `metadata` 字典字段。
  - 在 `migrations/004_chunk_metadata.sql` 中新增数据库迁移，为 `chunks` 表追加了 `metadata` 列，并在 `core/repository/source_store/sqlite.py` 中实现了 JSON 格式的序列化存取。
  - 在 `core/managers/ingest_manager.py` 中，在 PDF 分块提取时自动捕获物理页码 (`page_number`)、段落序号 (`paragraph`) 与定位符 (`locator`) 元数据。
  - 在 `core/api.py` 的 `ask` 接口中，返回的 `sources` 列表支持透传 `metadata` 信息，并自动将页码信息注入到 LLM 的提示词上下文中，实现高可信的 NotebookLM 风格证据定位。
  - 在 `web/server.py` 的 `_chunk_dict` 序列化辅助函数中增加了对分块 `metadata` 的返回支持。
- **本地向量数据库适配器 (`core/repository/vector_store/milvus_lite.py`)**：使用 `pymilvus` 和内嵌进程级 Milvus Lite 实现了对分块的多集合 Dense 向量检索、条件检索与增量写删。
- **混合检索编排 (`core/api.py`, `core/plugin_initializer.py`)**：在组合根与业务层完整接入并实例化本地向量库、EmbeddingProvider 及统一检索编排器 `RetrievalOrchestrator`，实现 Dense + Lexical + Graph-RAG 多路融合。
- **消息 Hook 骨架与 Agent 控制 (`core/main.py`, `core/event_handler.py`)**：注册了普通消息捕获 Hook 骨架并打通信号通路；新增了用于普通对话记忆召回控制的 `/kr agent on|off` 开关指令。
- **Ask Agent Persona 开关与 UI 联动 (`web/frontend/app/(console)/ask/page.tsx`, `web/frontend/lib/api.ts`, `web/frontend/lib/i18n.ts`)**：前端问答输入框底部操作栏新增奶油风“启用 Persona 角色设定”Toggle开关，参数下发后由 `core/api.py` 动态拉取当前 AstrBot 设定的 Persona Prompt 融入系统提示词以指导 Standalone Ask 答复。
- **双模式对话增强与 Agent 工具契约 (`core/event_handler.py`, `_conf_schema.json`, `core/config.py`)**：新增了 `ask.conversation_enhancement_mode` 配置项，允许用户在原生召回注入 (`inject`) 和内部代理问答 (`query_agent`) 之间自由切换；在 `query_agent` 模式下，委派内部 Standalone Ask Agent 产生纯学术级客观严谨回答并强制关闭其 Persona，同时衍生绑定 `session_id` 以便在 WebUI 统一追踪 Ask 历史，并利用绝对系统提示词（Absolute System Override）控制主 LLM 进行 verbatim 代理输出。

### 修复与优化 (Fixed & Optimized)

- **普通消息 Hook 零开销旁路优化 (`core/event_handler.py`)**：优化了 `EventHandler.on_message` 的旁路分支，当 `/kr agent off` 状态下彻底不触发任何向量库或 FTS5 检索逻辑，实现 100% 零开销 pass-through 快速放行。

### 测试 (Tests)

- **混合检索与向量库单元测试 (`tests/backend/test_retrieval_orchestrator.py`)**：新增覆盖 Milvus Lite 完整生命周期 and `RetrievalOrchestrator` RRF 融合及词匹配倒排得分回退的单元/集成测试。
- **消息 Hook 旁路与双模式 Hook 测试 (`tests/backend/test_lifecycle_and_cli.py`)**：新增在事件分发链中对 `/kr agent` 命令和普通消息捕获 Hook 的透传验证，并为 Phase 7 增加了全面的 `inject` 和 `query_agent` 双模式消息 Hook 的集成与绑定测试。

### 构建与工程 (Build/CI)

- **前端静态产物编译与同步更新 (`web/frontend/app/(console)/settings/page.tsx`, `pages/`)**：在控制台 Settings 模块接入了 `ask` 状态数据卡片，并通过 Node 20 编译并成功同步了 Next.js 静态文件。

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

## [v0.8.0] — 2026-05-30

### 新增功能 (Added)

- Notion 自动建库与反向元数据同步 (`core/adapters/notion_mcp.py`, `core/repository/sync_targets/notion.py`, `core/pipelines/sync_pipeline.py`):
  - 新增 Notion MCP `create_database` / `query_database` 适配能力，支持在指定 Parent Page 下创建标准 `Name` / `Collection` / `Tags` / `DocID` 数据库。
  - 新增运行时配置覆盖 `core/runtime_config.py`，自动建库成功后将 `database_id` 回写到 `data_dir/runtime_config.json` 并更新内存配置。
  - 新增 Notion pull 流程，只按 `DocID` 反向拉取 `Collection` / `Tags`，不覆盖标题、文件路径、content hash 或本地 PDF 原件。
- 设置核对与前后端接线验证 (`core/api.py`, `web/server.py`, `web/frontend/index.html`, `pages/index.html`):
  - 新增 `GET /api/config/effective`、`POST /api/notion/init`、`POST /api/sync/notion/pull`。
  - 新增 `/kr notion init` 与 `/kr sync notion --pull` CLI 薄壳。
  - Web 控制台新增”设置核对”页、前后端能力矩阵、Notion 初始化按钮和 Notion 反向拉取按钮。

### 测试 (Tests)

- 增强 `tests/backend/test_config.py`、`tests/backend/test_notion_target.py`、`tests/backend/test_web_server.py`、`tests/backend/test_lifecycle_and_cli.py`，覆盖 Notion 自动建库、pull 合并策略、配置脱敏、HTTP 路由和 CLI 入口。

## [v0.7.0] — 2026-05-30

### 新增功能 (Added)

- 图谱可视化与检索预览进阶 (`core/api.py`, `web/server.py`, `web/frontend/index.html`, `pages/index.html`):
  - `GraphStore` 正式扩展 `list_entities()` / `list_relations()` 读取契约，并在 SQLite / 内存实现中保持一致，供图谱前端通过 API 门面读取。
  - `core/api.py::get_graph()` 落地 collection 级图谱数据接口，返回 nodes / edges 与 `source_previews` 来源片段预览，不直读前端侧数据库细节。
  - `/api/graph/query?debug=true` 返回向量召回、实体关键词召回、1-hop 图邻域召回和 RRF score 诊断，默认查询仍保持轻量。
  - Web 控制台新增轻量 SVG 图谱视图、节点/边详情、来源片段预览、融合查询结果和调试诊断面板；同步更新静态产物 `pages/index.html`。

### 测试 (Tests)

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

---

## [v0.1.0] — YYYY-MM-DD

### 构建与工程 (Build/CI)

- 基于通用项目框架模板初始化仓库；建立分层骨架、治理三件套（CLAUDE/CHANGELOG/TODO）与 CI。
