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

## [v0.28.2] — 2026-06-23

### 修复 (Fixed)

- **聊天端 Deep Thinking 改为后台执行，避免 AstrBot LLM tool 120s 同步超时**：`research_execute(mode="deep_thinking")` 在运行态 `main.py` 中先向原会话发送可见启动提示，再用 `asyncio.create_task` 后台完整执行 `ResearchService.execute(..., mode="deep_thinking")`，工具本身立即返回 `started` JSON，完成后主动回发答案与确定性引用；普通 `research_execute` 也会先发送“已开始检索”提示，避免长时间静默被误判为卡死。WebUI `/api/ask`、`KnowledgeRepositoryApi.ask()` 与 `DeepThinkingOrchestrator` 未改动，WebUI Deep Thinking 行为保持不变（`main.py`）。

### 构建与工程 (Build/CI)

- 版本号 bump 到 `v0.28.2`，并补齐 `bump_version.py` 的 `main.py` 与 README badge 同步能力，避免后续发布漏改（`metadata.yaml`、`main.py`、`README.md`、`bump_version.py`）。

## [v0.28.1] — 2026-06-23

### 新增功能 (Added)

- **research 改为对话式（主 LLM 指挥 + 两个无状态工具），支持中英双语**：`research_scope_probe`（模糊检索标题/集合/标签元数据 → 候选 + `ambiguity` + 建议/可用模式，供主 LLM 判断回应范围、决定直接执行或先与用户确认）与 `research_execute`（真召回 + 确定性 `Author - Year - Title` 引用列表）取代原 one-shot `knowledge_research`；范围界定与模式选择交给主对话 LLM，天然吃聊天上下文与追问。execute 默认英文召回（`use_english_retrieval`）+ 按提问语言作答（`answer_language=auto`）；probe 分词支持 CJK 2-gram，中文 query 可命中中文集合名/标题（`core/research_skill.py` 新 `ResearchService`、`main.py`、`core/plugin_initializer.py`、`core/main.py`）。
- **语义检索：reranker 静默自适应 + 宽召回**：`RetrievalOrchestrator.retrieve_with_outcome()` 新增 `candidate_k`/`reranker`——配置 cross-encoder 时「宽召回候选池 → 二次重排 → 取 top_k」（默认 answer top_k 不变，无 reranker 自动退回 RRF 截断）；`api.ask()` 新增 `candidate_k`/`use_reranker`，`research_execute` 据 `breadth`（narrow/normal/wide）放大候选池；reranker 实例由 `PluginInitializer` 共享给 default 路径与 deep_thinking（`core/pipelines/retrieval_orchestrator.py`、`core/api.py`、`core/plugin_initializer.py`）。

### 架构健康 (Refactor)

- 删除 one-shot research 的 `ScopeResolver`/`KeywordScopeResolver`/`ModeSelector`/`ResearchSkill`，收敛为 `ResearchService`（probe + execute）（`core/research_skill.py`）。

### 测试 (Tests)

- 重写 `tests/backend/test_research_skill.py` 覆盖 probe（ambiguity/author-year enrich/可用模式/中文集合命中）与 execute（英文召回/wide+reranker/引用拼装）；`test_api.py`、`test_retrieval_orchestrator.py` 适配 `candidate_k`/`reranker` 新参数。

> 注：`@filter.llm_tool` 的跨轮调用与返回语义依 AstrBot SDK，接入真实 AstrBot 需实测；不稳时退化为单工具 `phase: propose|execute`（见 `main.py` 注释与 TODO）。

## [v0.28.0] — 2026-06-22

### 新增功能 (Added)

- **聊天指令集从 `/kr` 重写为 `/ka`（纯运营控制面 + 自然语言 research）**：新增 `/ka help`、`/ka status`（模型/服务/运行时开关概览）、`/ka agent on|off`、`/ka research on|off`、`/ka persona on|off`、`/ka zotero pull`、`/ka r2 push|pull|force push|force pull`、`/ka webui on|off`；其中 `r2` 的 `force push`/`pull`/`force pull` 需 60s 窗口内重发同命令二次确认，`force pull` 恢复后自动触发软重启。文档/集合/标签/Notion/知识图谱等内容管理下沉 WebUI，聊天端不再暴露（`main.py`、`core/event_handler.py`、`core/main.py`）。
- **`knowledge_research` LLM 工具（research skill）**：由 AstrBot 主 LLM 经自然语言调用的只读知识检索工具，分四步流式产出「范围解析 → 模式选择 → api.ask → 答案」。范围解析（`KeywordScopeResolver`：显式集合名命中 + title 覆盖率评分）与模式选择（`ModeSelector`：quick/deep/auto × LightRAG 就绪度 → default/deep_thinking/high_precision）各为接口先行的可替换模块；工具仅做检索，绝不修改 Zotero/Notion/R2 同步配置（`core/research_skill.py`、`core/plugin_initializer.py`、`main.py`）。
- **运行时开关持久化**：`agent`/`research`/`persona`/`webui` 四个开关写入 `runtime_config.json`，重启保留；新增 `ask.agent_enabled`/`ask.research_enabled`/`web_console.enabled` 持久化策略与 `AskAgentConfig` 字段、`PluginInitializer.set_toggle()` 与 `start_web_console()`/`stop_web_console()` 实时启停（`core/config.py`、`core/plugin_initializer.py`）。

### 新增接口 (Added)

- `api.get_service_status()`（服务框架概览）、`api.list_titles_by_collection()`（research 范围解析的轻量门面）；`SyncPipeline.sync()` 与 `api.sync_documents()` 新增 `force` 参数（强制全量覆盖上传）（`core/api.py`、`core/pipelines/sync_pipeline.py`）。

### 架构健康 (Refactor)

- 删除 `/kr` 全部命令路由与对应 `EventHandler`/薄壳方法（add/quota/collection/tag/sync/notion/graph/agent），收敛聊天命令面（`core/event_handler.py`、`core/main.py`、`main.py`）。
- **移除会话增强 `query_agent` 模式与 `ask.conversation_enhancement_mode` 配置**：该模式在 `on_message` 阶段短路、会静默吞掉新的 `knowledge_research` skill，且与之高度冗余。agent 开启时只保留 `inject` 一种行为（被动上下文注入），主动检索统一走 research skill；删除 `on_message` 消息 hook（`@filter.event_message_type`）、`AskAgentConfig.conversation_enhancement_mode` 字段/策略/`to_public_dict` 暴露、`capabilities` 的 ask mode 候选项。WebUI 数据流图 STAGE 06「问答 Ask」的 MODE 切换（原生注入/内部代理）随之移除，仅保留 rerank 状态展示（`core/event_handler.py`、`main.py`、`core/main.py`、`core/config.py`、`core/capabilities.py`、`web/frontend/components/flow/model.ts`、`web/frontend/components/flow/FlowNode.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`pages/`）。

### 测试 (Tests)

- 新增 `tests/backend/test_research_skill.py`（范围解析/模式选择/handle 流式与 research 关闭短路）；重写 `test_lifecycle_and_cli.py` 的薄壳测试覆盖 `/ka` 路由、开关持久化往返与 R2 二次确认/自动重启；`test_config.py` 增 `/ka` 开关键持久化往返；`test_sync_pipeline.py` 增 `force` 全量重传（`tests/backend/`）。

## [v0.27.1] - 2026-06-21

### 修复 (Fixed)

- **AstrBot 主 LLM Provider 适配新 SDK**：`LLMAdapter` 新增 AstrBot 4.5.7+ 的 `context.llm_generate()` 调用路径，自动通过 `provider_manager.get_using_provider(ProviderType.CHAT_COMPLETION)` 或 `curr_provider_inst` 获取当前默认 chat provider，并统一解析 `LLMResponse.completion_text` / `result_chain.get_plain_text()`；同时保留旧版 `call_llm`、`llm_provider`、`get_llm_provider` 兼容路径，修复 Docker 真实 WebUI `6520` 中 Research Agent 误回退到“离线测试占位答案”的问题（`core/adapters/llm.py`）。

### 测试 (Tests)

- 新增 `LLMAdapter` 单元测试，覆盖 AstrBot `llm_generate` 返回 `completion_text`、`result_chain` 以及 `extract_graph()` 共用真实 provider 路径（`tests/backend/test_llm_adapter.py`）。

## [v0.27.0] — 2026-06-21

### 新增功能 (Added)

- **发布资料 README 与插件 logo**：根目录 `README.md` 从框架模板 landing 改为中文插件介绍，补齐安装、基础配置、可选依赖、WebUI 导览、`/kr` 指令速查、高级配置和开发者架构入口；新增根目录 `logo.svg`，并由当前前端使用的 `knowledge-arch-icon.svg` 生成 AstrBot 可识别的 `logo.png`（`README.md`、`logo.svg`、`logo.png`）。
- **登录页视觉重构**：按用户提供的 `Login Page.dc.html` 重做控制台登录页，新增本地 Bitcount 字体变量、深色点阵建筑背景、呼吸式亮暗动画、玻璃登录卡片与英文 `USERNAME` / `PASSWORD` 标签；登录 UI 从 console layout 抽离为独立 auth 组件，构建产物已同步到 `pages/`（`web/frontend/app/layout.tsx`、`web/frontend/components/auth/LoginScreen.tsx`、`web/frontend/components/auth/LoginScreen.module.css`、`pages/`）。

### 修复 (Fixed)

- **Zotero server 模式同步卡死在 3%**：`ZoteroWebApiReader.read_snapshot()` 在 `reading_snapshot` 阶段就串行下载整库所有 PDF（每篇 15s 超时），而 `docs_total/docs_processed` 要等读取整段返回后才设置，进度条因此长时间假死在阶段底值 3%；且增量「未变更」判断在下载之后，等于每次同步都重下整库。改为：`_attachments()` 只读元数据不下载、新增 `fetch_attachment_file()` 惰性单篇下载；pipeline 的 `_read_snapshot` 额外返回下载器，`_sync_documents` 重排为「先判增量未变更→直接跳过且不下载，仅新增/变更件在 syncing_documents 阶段按需下载（`asyncio.to_thread` 包裹避免阻塞事件循环）」，进度随 docs_processed 平滑推进（`core/adapters/zotero/web_api.py`、`core/pipelines/zotero_sync_pipeline.py`）。
- **进度面板可被手动关闭**：`ProgressDock` 头部的 `×` 关闭按钮会让用户在后台任务未完成时提前隐藏面板；移除该按钮与 `dismissed` 状态，面板仅保留收起/展开，随后台任务存在与否自动出现/消失（任务终态后由 `/api/sync/zotero/active` 短暂展示再返回 null），保证「任务成功后才结束」（`web/frontend/components/progress/ProgressDock.tsx`）。
- **FilePanel 同步按钮失效**：面板头部与 Zotero 区块的两个"同步"图标按钮缺少 `onClick` 绑定，点击无任何响应；补齐两处 `onClick={() => handleZoteroSync(true)}` 并新增 `handleZoteroSync` 函数（触发 `POST /api/sync/zotero/pull` + 本地轮询至完成 + 刷新 `listCollections`）、新增 i18n 键 `zotero_sync_started`（`web/frontend/components/panels/FilePanel.tsx`、`web/frontend/lib/i18n.ts`）。
- **同步期间刷新 WebUI 偶发白屏**：`sync_frontend.py` 先 `shutil.rmtree(pages/)` 再逐文件复制，中间窗口期 HTTP 请求会因找不到 `index.html` 而 404；改为先写临时目录 `pages.__tmp__`、完成后整体 `rename` 替换旧目录，消除窗口期（`tools/sync_frontend.py`）。
- **Flow 页同步卡住整个界面**：`get_zotero_config()` 中调用 `local_api.probe_connection()` 时使用同步 `urllib.request.urlopen`（timeout=1s），每次执行都阻塞 aiohttp 事件循环，导致所有并发 HTTP 请求在轮询周期内最多卡顿 1 秒；改为 `await asyncio.to_thread(local_api.probe_connection, ...)` 让阻塞 I/O 在线程池中运行（`core/api.py`，`get_zotero_config` 与 `probe_zotero_local` 两处）。
- **Flow 页同步按钮长期禁用**：`ZoteroQuickConfig.handleSyncNow` 把整段同步（可能持续数分钟）的轮询 while 循环内联在 onClick 回调中，期间按钮一直禁用且无法通过 ProgressDock 感知进度；改为 fire-and-forget——`handleSyncNow` 仅启动同步后立即置 `syncing=true` 并返回，进度轮询移至独立 `useEffect`，同步完成后更新状态摘要并回调 `onRefresh`（`web/frontend/components/flow/ZoteroQuickConfig.tsx`）。
- **Zotero 同步终态不可见**：`get_active_zotero_sync_job()` 过去在 success 时立即返回 `None`，导致 ProgressDock 和 toast 捕获不到完成态；改为 success/partial/error 终态保留 30 秒，前端在 ProgressDock 中对终态 toast 一次，所有同步入口点击后立即提示“已启动”（`core/api.py`、`web/frontend/components/progress/ProgressDock.tsx`、`web/frontend/components/flow/ZoteroQuickConfig.tsx`、`web/frontend/components/modals/SettingModal.tsx`、`web/frontend/components/panels/NotePanel.tsx`）。
- **基础面板无限 loading**：`apiFetch` 增加 `timeoutMs` / `AbortController` 兜底，日志、进度 active、capabilities、配置类接口设置短超时；`TerminalPanel` 增加 in-flight guard，`ProgressDock` 的轮询调度改为 finally 中续约，避免单个请求异常后停止刷新（`web/frontend/lib/api.ts`、`web/frontend/components/ui/TerminalPanel.tsx`、`web/frontend/components/progress/ProgressDock.tsx`）。

### 性能优化 (Performance)

- **`/api/capabilities` 热路径轻量化**：新增 `SourceDocumentStore.get_corpus_stats()`，SQLite 生产实现使用聚合 SQL 一次返回 document/pending/chunk 计数，memory 实现直接读内存结构；`CapabilitiesApiMixin._milvus_runtime_health()` 不再逐文档 `list_chunks()` 拉取 14999 个 chunk 正文，Zotero availability 外部探测也不再阻塞 capabilities 心跳（`core/repository/source_store/base.py`、`core/repository/source_store/sqlite.py`、`core/repository/source_store/memory.py`、`core/api_capabilities.py`）。
- **Flow 数据流面板刷新拆分**：自动刷新改走轻量 `getCapabilities()` + `getEffectiveConfig(1500ms)`；`recheckDependencies()` 仅用于手动刷新、依赖安装和重启确认，Zotero 详细配置异步补充，不再阻塞首屏 loading（`web/frontend/components/panels/FlowPageContent.tsx`、`web/frontend/lib/api.ts`）。

### 测试 (Tests)

- 新增 capabilities 聚合计数回归测试，确保 `/api/capabilities` 不再调用 `list_chunks()`；新增 Zotero active success 短暂保留测试；修正 Zotero SQLite reader 测试中的 Windows 路径分隔符断言（`tests/backend/test_api.py`、`tests/backend/test_zotero_sync.py`）。
- 新增 `test_pull_server_mode_downloads_lazily_and_skips_unchanged`：守护 web 模式首次按需下载恰好一次、二次增量跳过且不重下，防止 `read_snapshot` 预下载回归；更新 `test_web_api_reader_builds_personal_snapshot` 断言 `read_snapshot` 不再预下载、`fetch_attachment_file` 按需落盘（`tests/backend/test_zotero_sync.py`、`tests/backend/test_zotero_server.py`）。

### 构建与工程 (Build/CI)

- **发布版本 bump 到 v0.27.0**：手动定点更新插件 manifest 版本，避免 `bump_version.py` 误改当前 TODO 顶部历史段落；新增 `docs/PROJECT_STRUCTURE.md` 承接旧根 README 的目录结构、治理文件和发布前检查 landing 功能（`metadata.yaml`、`TODO.md`、`docs/PROJECT_STRUCTURE.md`）。

## [v0.26.3] — 2026-06-20

### 新增功能 (Added)

- **统一多归属集合树**：新增 `migrations/018_unified_collection_tree.sql`，把 `collections` 升级为 `coll_key` 稳定逻辑主键 + `parent_key` 树结构 + `library_id` 命名空间，并新增 `document_collections(doc_id, coll_key)` 多对多归属表；`Collection` 与 `SourceDocument` 同步补齐树形与多归属字段，保留 `documents.collection` 作为 primary 冗余标签（`migrations/018_unified_collection_tree.sql`、`core/domain/models.py`）。
- **本地集合树编辑 API**：新增按 `coll_key` 的本地集合新建子集合、重命名、移动、防环校验和删除能力；Zotero 来源集合保持只读，删除本地集合时子集合提升、无归属文档迁入 `_uncategorized`（`core/api.py`、`web/server.py`、`web/frontend/lib/api.ts`）。
- **前端文件面板真树形展示**：`FilePanel` 改为递归渲染本地集合与 Zotero 集合树，支持本地集合展开、建子集合、重命名和按 key 删除；Zotero 集合仅展示，不提供写操作（`web/frontend/components/panels/FilePanel.tsx`、`web/frontend/lib/i18n.ts`）。

### 架构健康 (Refactor)

- **SourceStore 契约改为 coll_key 优先**：在仓储抽象与 sqlite/memory 双实现中新增 `get_collection`、`get_collection_by_name`、`get_local_collection_descendants`、`delete_collection_by_key`、`set_document_collections`、`list_document_collection_keys`、`list_documents_by_collection_key(descendants)` 等契约；`add_document`/`update_document` 自动维护多归属表并回填 `collection_keys`（`core/repository/source_store/base.py`、`core/repository/source_store/sqlite.py`、`core/repository/source_store/memory.py`）。
- **Zotero 同步不再压扁集合树**：Zotero pull 将 collection snapshot 派生进统一 `collections`，`coll_key=library_id:zotero_collection_key`、`parent_key=library_id:parent_key`，并为 item 写入全部所属集合；陈旧 Zotero 集合和迁移临时行由同步流程清理（`core/pipelines/zotero_sync_pipeline.py`）。
- **问答与 LightRAG 范围统一为含后代**：collection scope 通过统一树解析为选中集合及全部后代文档，ask 默认在选中集合时派生含后代 scope；LightRAG readiness/build 也按父集合 + 后代合并为单一 workspace，DocumentsPanel 的 `collection_key` 查询仍只列本级文档（`core/api.py`、`core/pipelines/retrieval_orchestrator.py`、`web/server.py`）。
- **分类与系统集合兼容多归属**：分类管理继续保留 primary collection 语义，同时通过仓储层同步多归属，避免 R2/Notion/Milvus 既有 collection tag 行为被破坏（`core/managers/category_manager.py`、`core/repository/source_store/sqlite.py`）。

### 测试 (Tests)

- 新增 migration 018 回填与迁移测试，覆盖旧库集合 key 回填、`document_collections` 派生、同名树形集合和外键重建约束（`tests/backend/test_migration_018.py`）。
- 扩展 source store、sqlite store、retrieval scope、web server 与 Zotero 同步测试，覆盖多归属文档、按 `coll_key` 本级/含后代查询、本地集合编辑 REST、Zotero 树同步和 ask scope 含后代行为（`tests/backend/test_source_store.py`、`tests/backend/test_sqlite_source_store.py`、`tests/backend/test_retrieval_scope.py`、`tests/backend/test_web_server.py`、`tests/backend/test_zotero_sync.py`）。
- 已记录验证：`python -m pytest tests/backend/` → 414 passed；`ruff check .` → passed；`mypy` → passed（`TODO.md`）。

## [v0.26.2] — 2026-06-19

### 修复 (Fixed)

- **调试 WebUI 端口迁移到避让区间**：将项目内测试/调试后端端口统一改为 `26618`，前端开发端口统一改为 `26619`，覆盖 `rebuild.sh`、`tests/run_webui.py`、`core/config.py`、`_conf_schema.json`、`web/frontend/next.config.ts`、前端 mock config、文档与设计说明，避免继续碰到旧端口占用或转发密码异常（`rebuild.sh`、`tests/run_webui.py`、`core/config.py`、`_conf_schema.json`、`web/frontend/lib/api.ts`）。
- **旧端口残留清理**：全仓清理端口语义的旧后端/旧前端端口引用；保留 `PerfPanel`、`ProgressDock` 中作为毫秒阈值/轮询间隔的旧前端端口同值数字，不改变业务行为（`web/frontend/components/ui/PerfPanel.tsx`、`web/frontend/components/progress/ProgressDock.tsx`）。

### 构建与工程 (Build/CI)

- **Docker/devcontainer 端口发布同步**：将 devcontainer `appPort` 与 Dockerfile `EXPOSE` 同步为 `26619/26618`，并让 `rebuild.sh` 输出的新访问地址指向 `http://127.0.0.1:26618` 与 `http://127.0.0.1:26619`（`.devcontainer/devcontainer.json`、`.devcontainer/Dockerfile`、`rebuild.sh`）。

### 测试 (Tests)

- Docker 环境验证：`bash -n rebuild.sh` → passed；`python -m pytest tests/backend/test_config.py -q` → 26 passed；`node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed；`npm run build`（`web/frontend`）→ passed；`python tools/sync_frontend.py && python tools/sync_frontend.py --check` → passed（同步 362 个文件，`pages/` 一致）；`bash rebuild.sh` → passed；`26618/26619 auth smoke` → passed（`/api/auth` 200、前端首页 200、`admin/111111` 登录后 `logged_in=true`）。

## [v0.26.1] — 2026-06-19

### 新增功能 (Added)

- **统一进度面板 ProgressDock（左下角浮动停靠）**：新增 `web/frontend/components/progress/ProgressDock.tsx`，泛化自原未挂载的 `BuildWidget`，用一个内置 `useProgressJobs` hook 并行轮询四类后台任务的 `/active` 端点（Zotero 同步 / Milvus 向量构建 / LightRAG 图谱构建 / 文档上传摄入），归一化为统一进度行渲染：可收起/展开、终态/错误显式提示、LightRAG 行保留暂停/继续/查看图谱动作、全部空闲时返回 `null` 完全隐藏；层级 `Z.progressDock=1350`（Modal 之上、Toast 之下）。在 `app/(console)/layout.tsx` 的 `ConsoleProvider` 内挂载；新增 i18n `progress_dock_*` 键（`web/frontend/components/progress/ProgressDock.tsx`、`web/frontend/lib/zLayers.ts`、`web/frontend/app/(console)/layout.tsx`、`web/frontend/lib/i18n.ts`）。
- **Zotero Pull 异步任务 + 进度模型**：新增 `core/zotero_sync_job.py:ZoteroSyncJob`（纯内存进度快照，`to_dict()` 带 `type=zotero_sync`、`status`、阶段 `reading_snapshot→mirroring→syncing_documents→applying_removals→finalizing`、文档计数与 `progress_percent`），照搬 `MilvusBuildJob` 范式；`ZoteroSyncPipeline.pull(progress=...)` 在各阶段/逐文档更新 job；新增后端 `GET /api/sync/zotero/active` 与前端 `getActiveZoteroSyncJob()`/`ZoteroSyncJob` 类型（`core/zotero_sync_job.py`、`core/pipelines/zotero_sync_pipeline.py`、`core/api.py`、`web/server.py`、`web/frontend/lib/api.ts`）。
- **文档上传/摄入进度**：新增 `core/ingest_job.py:IngestJob`（parsing→indexing 两阶段），`KnowledgeRepositoryApi.register_document` 在编排边界跟踪并经新端点 `GET /api/documents/ingest/active` 暴露，纳入统一进度面板（`core/ingest_job.py`、`core/api.py`、`web/server.py`、`web/frontend/lib/api.ts`）。

### 修复 (Fixed)

- **Zotero Pull「失灵」根因修复**：① `sync_zotero_pull` 由「`await pull()` 整段同步阻塞」（几十篇 PDF 下载/清洗/embedding 数分钟、单 HTTP 请求易超时）改为**后台任务 + 立即返回任务快照**，全局单任务守卫，前端轮询 `/active` 看进度；② `ZoteroSyncResult` 历史上**缺 `status` 字段**，前端 `ZoteroQuickConfig` 全靠 `syncStatus.status==="error"` 判断 → 永远判不出成功/失败，现 `_run_zotero_pull` 据 `result.errors` 推导 `success/partial_failure/error` 并注入 `_last_zotero_sync`；③ **停止静默吞错**：`_index_and_mark` 的索引副作用失败（如 `VectorStore 未配置`）原仅 `logger.warning`，现追加进 `result.errors` 并 `logger.error(exc_info=True)`，使「同步出文档却未入向量库」可见；④ `ZoteroQuickConfig.handleSyncNow` 改为轮询任务至终态再刷新摘要（`core/api.py`、`core/pipelines/zotero_sync_pipeline.py`、`web/frontend/components/flow/ZoteroQuickConfig.tsx`）。

### 架构健康 (Refactor)

- **进度指示去重**：移除 `FilePanel` 内的 Milvus 进度卡片 `MilvusBuildCard` 及其状态/轮询/重试链（迁入统一进度面板），保留 `buildJob` 状态供构建按钮逻辑（`web/frontend/components/panels/FilePanel.tsx`）。

### 性能/可观测性 (Performance)

- **Terminal 日志补强（聚焦本次改动，不改前端）**：补 Zotero 同步全链路 `logger.info`（开始/各阶段/完成摘要）、`search_kb` 入口出口 + 命中数 + 耗时、`ask` 入口；被吞错误统一 `exc_info=True`（Zotero 索引失败、Milvus 后台重建失败、上传索引失败）（`core/pipelines/zotero_sync_pipeline.py`、`core/api.py`）。

### 测试 (Tests)

- 新增 `tests/backend/test_zotero_sync_job.py`（`ZoteroSyncJob` 的 `progress_percent`/`status`/`to_dict` 契约）；`tests/backend/test_zotero_sync.py` 增「pull 注入 progress 计数正确」与「索引副作用失败进 `result.errors`」回归。

## [v0.26.0] — 2026-06-19

### 新增功能 (Added)

- **数据流节点界面美术与配置统一重构**：① 节点左侧 mark 由纯色竖条改为随状态显色的辉光带（`box-shadow` 内发光 + `stripeFlow` 自上而下数据流高亮，非旋转），边末端连接点对齐其上沿；`flow-node-icon`(R9) 与状态徽章（原 R999 全圆角）统一为同一 R 角；节点 `column-gap` 52→68px 拉大横向间距；可选/旁路来源（dashed 边）去掉「可选来源」文字气泡，改用 from 端**靛紫菱形端点** + 靛紫描边（新增 `--flow-st-optional`）。② 各节点快速配置统一为「模块切换 + 必要配置 + 高级折叠浮层」三段式（推广 `ZoteroQuickConfig` 范式，抽出共享 `useQuickConfigDraft`/`computeUpdates`/`QuickConfigFieldGrid`/`AdvancedSection`）；高级浮层绝对定位、不计入节点测量高度，故展开/收起不影响边对齐；高级区补齐该节点全部 api 可写键——graph 的 LightRAG 专用 LLM `provider/base_url/model`、`source_store.default_collection`、Ask 节点并入 `deep_thinking` 全部调参，结构性键 `graph.working_dir` 只读展示。③ 节点头部状态徽章合并为**唯一保存入口**：未保存改动时节点整体变 dirty 蓝、徽章变「保存」按钮（经 ref 触发面板提交），保存后该节点进入「待重启」配色；数据流页顶部新增全局「重启插件」按钮（带待重启计数徽标），点击经新端点 `POST /api/plugin/restart` 软重启并轮询探活后清态。后端 `KnowledgeRepositoryApi.restart_plugin()` 经注入的 `PluginInitializer.reload()`（teardown → 重读持久化配置重建 `Config` → initialize）在进程内软重启、不杀 AstrBot 进程，无 `reload_callback` 时回退 unsupported（`web/frontend/styles/tokens.css`、`web/frontend/components/flow/FlowNode.tsx`、`FlowDiagram.tsx`、`QuickConfigPanel.tsx`、`ZoteroQuickConfig.tsx`、`web/frontend/components/panels/FlowPageContent.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`core/api.py`、`core/plugin_initializer.py`、`web/server.py`）。
- **AstrBot 配置收窄与 WebUI 设置迁移**：`_conf_schema.json` 顶层配置只保留 `web_console`、`r2_sync`、`notion_sync`、`embedding`、`ask` 五组并按用户指定顺序展示；`Config.to_public_dict()` 补齐 `source_store.default_collection`、图谱专用 LLM、Deep Thinking 调参和专用 LLM 字段；`CONFIG_KEY_POLICY` 开放迁移所需的非机密运行时写入键；`SettingModal` 的后端配置页新增临时高级配置编辑区，迁移源文档默认集合、图谱专用 LLM、Deep Thinking 参数，并把 `deep_thinking.llm_api_key` 保持为 env-only 展示（`_conf_schema.json`、`core/config.py`、`web/frontend/components/modals/SettingModal.tsx`、`web/frontend/lib/api.ts`）。
- **Milvus/Data Cleaning 统一进度条**：`MilvusBuildJob` 扩展 `stage`、`stage_label`、cleaning/indexing counters，并把 `progress_percent` 改为同一条进度条上的 data cleaning + vector indexing 合并进度；Milvus rebuild 在索引前预扫描 legacy chunks，调用 `IngestManager.rebuild_document_chunks_from_artifact()` 基于现有 `clean.md/pages.json` 重建 chunks，清洗失败的文档计入 `failed_docs` 并跳过 upsert；FilePanel 的 `MilvusBuildCard` 在同一卡片展示当前阶段与 `cleaned/indexed/failed` 明细（`core/milvus_build.py`、`core/api.py`、`core/api_capabilities.py`、`web/frontend/components/panels/FilePanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- **深度思考实时推演进度（逐轮可见）**：`ProgressStore.set/get` 新增可选 `detail`（向后兼容，无 detail 时返回结构不变）；`DeepThinkingOrchestrator.run` 的 `progress` 回调扩为 `(stage, pct, detail)`，PLAN 后推送信息点清单、每轮 SEA 后增量推送该轮 trace、finalize 时推送，detail 经新增 `deep_thinking_view.live_detail` 序列化（与最终 `thinking_trace` 同形，从根上保证「实时格式 == 最终格式」）；前端 `lib/api.ts` 新增 `getAskProgress`/`LiveProgressDetail`，`ChatPanel` 提交前预生成 `conversation_id`（首条消息也能在请求进行中轮询 `/api/ask/progress/{cid}`），新增 `LiveThinkingView` 把逐轮 detail 实时渲染进「思考中」区，请求结束替换为最终「思考过程」区块（格式与现状一致）（`core/ask_progress.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/pipelines/deep_thinking_view.py`、`core/api.py`、`web/frontend/lib/api.ts`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/i18n.ts`）。
- **本地 Sentence-Transformers Rerank 热切换与 AB Test**：Deep Thinking 专用 rerank 默认模型改为 `Alibaba-NLP/gte-reranker-modernbert-base`；缺省 provider 改为 auto 解析（安装 `sentence-transformers` 时启用 `cross_encoder`，未安装时 `noop`，显式 `noop` 始终保持关闭）；`deep_thinking.rerank_weight` 默认 0.2，缺真实 reranker 时仍回退纯 RRF；`CrossEncoderReranker` 暴露 `idle/loading/ready/failed`、model 与 last_error，首次 Deep Thinking 使用时懒加载/下载，失败不抛出并回退 passthrough；`/api/config/update` 写入 `rerank.provider/model` 后不再要求 restart，并立即替换现有 `DeepThinkingOrchestrator` 的 reranker；capabilities Ask 节点暴露 rerank provider/model/status/ST 依赖状态；数据流 Ask 快速配置新增 rerank 开关与模型输入、状态展示和加载 toast；realtime mock 支持 `RERANK_PROVIDER`、`RERANK_MODEL`、`DEEP_THINKING_RERANK_WEIGHT` 并打印首次使用下载提示（`core/config.py`、`core/api.py`、`core/api_capabilities.py`、`core/capabilities.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/repository/reranker/`、`_conf_schema.json`、`web/frontend/components/flow/QuickConfigPanel.tsx`、`web/frontend/components/flow/model.ts`、`web/frontend/components/panels/FlowPageContent.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`tests/mocks/run_dev_realtime.py`、`tests/mock_data/Config/config.example.py`）。
- **Deep Thinking 开放式深挖 + 答案结构 + 告警分界**：① loop 从「围预设 checklist 收敛填空」升级为「开放式发现」——SEA 新增 `discovered_aspects`（独立于 gaps，**不进** soft_missing/告警），由 orchestrator 去重后追加为非 critical checklist 项（`ChecklistItem.origin="discovered"`，受 `max_discovered_per_round=3`/`max_discovered_total=8` 约束）、驱动下一轮 REFINE 深挖、写入 `RoundTrace.discovered` 并序列化；收敛条件改为「sufficient 且无本轮新发现」。② per-aspect 排序：`_gather_round` 以「每个 sub_query 的 `rrf_score` 取 max」为主排序信号（无 reranker 也能让具体机制 chunk 浮出，不再退化为候选插入顺序），reranker 降为可调 `rerank_weight`（默认 0），>0 时按 query 分池 rerank 后线性混合；新增 `Reranker.is_passthrough`（`NoopReranker`/失效 `CrossEncoderReranker` → True）自动置零失效 reranker 权重。③ deep 合成：`synthesize_answer` 新增 `style="deep"` + `_SYNTH_SYSTEM_DEEP`（机制级、分维度、带跨实体对比与小结），verify 闭环与 api.ask fallback 两条路径都走 deep 风格。④ PLAN prompt 对「比较 A 与 B / 共享 X」类问题要求按实体并行铺机制探针。⑤ 调参：`wide_top_k`24、`deep_keep`12、`max_rounds`4、`max_final_evidence`18、`token_budget`36000、`call_budget`18；`rerank_weight` 经 `_conf_schema.json` 暴露可调（`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/pipelines/answer_synthesis.py`、`core/domain/deep_thinking.py`、`core/repository/reranker/base.py`、`noop.py`、`bge_local.py`、`core/config.py`、`core/api.py`、`_conf_schema.json`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- **Deep Thinking 展开召回与软降级**：常规 SEA gap、未满足 checklist 与 critical 缺口不再触发 `deep_degraded_to_default`，改为保留多轮探索 evidence 并通过 `verify_missing`/trace 暴露缺口；`_BASELINE_FLOOR_N=5` 只作为 LLM 不可用、最终证据为空等硬失败 fallback；新增内部 `DeepThinkingConfig.max_final_evidence=16`，正常 deep thinking final evidence 按 structural anchor、baseline floor、rerank score 优先级截断，避免固定只剩 5 个 chunk，同时防止上下文无限膨胀；verification 补检召回的新证据会重新进入 final evidence；PLAN prompt 明确要求子查询分散覆盖定义/背景、机制、对比、时间线、章节锚点、原文证据（`core/config.py`、`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`、`tests/backend/test_deep_thinking_orchestrator.py`、`tests/backend/test_api.py`）。
- **Deep Thinking prompt 协议与数据流图**：PLAN/SEA/REFINE/VERIFY prompt 升级为更细的结构化协议：PLAN 输出 evidence plan/search hints，SEA 输出 checklist coverage matrix，REFINE 支持 typed gap queries，VERIFY 输出 claim-level audit 并合并到现有 `verify_missing`；`ChecklistItem` 增加 evidence/search/coverage 相关默认字段，解析器保持旧 JSON 兼容；orchestrator 将 SEA coverage 回填 checklist，并优先用 typed gap 指导 REFINE；新增 `docs/deep_thinking_flow.md` Mermaid 源与 `docs/deep_thinking_flow.png` 数据流图（`core/domain/deep_thinking.py`、`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`、`tests/backend/test_deep_thinking_orchestrator.py`、`docs/deep_thinking_flow.md`、`docs/deep_thinking_flow.png`）。
- **PDF 文档强制重提取**：对已摄入文档新增 `IngestManager.reextract_document()`，定位 `data/library/<doc_id>/original.pdf`，用当前已修复的提取代码（含 `ignore_alpha=True`）重跑并覆写 `clean.md`/`pages.json`，重新分块写库并标 `needs_reindex`，无需删除文档重新上传；新增 `POST /api/documents/{doc_id}/reextract` 路由；`DocumentsPanel` 对 PDF 类型文档显示「重新提取」按钮（`core/managers/ingest_manager.py`、`core/api.py`、`web/server.py`、`web/frontend/components/panels/DocumentsPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- **深度思考降级原因暴露**：`DeepThinkingOutcome` 新增 `degraded_reason: str = ""` 字段；`_degraded()` 新增 `reason` 参数并透传到 outcome；PLAN/SEA/REFINE 各阶段 `except Exception` 传 `str(exc)` 作为原因，证据不足路径拼接「无最终证据 / 证据缺口率 X% ≥ 阈值 Y% / 关键检查项未满足」等人类可读说明；`_serialize_deep_thinking()` 暴露 `degraded_reason`；`ThinkingTraceView` 在降级 badge 下展示原因文字（`core/domain/deep_thinking.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`）。
- **深度思考独立 LLM 配置**：`DeepThinkingConfig` 新增 `llm_base_url`/`llm_model`/`llm_api_key` 三字段；`plugin_initializer.py` 在两者均非空时构造 `LMStudioLLMAdapter` 作为深度思考专用 LLM，否则回退 AstrBot 主 LLM；新增 `ENV_DEEP_THINKING_LLM_API_KEY` 环境变量常量，支持 API key 不写入配置文件（`core/config.py`、`core/plugin_initializer.py`）。

### 修复 (Fixed)

- **数据流：编辑配置时自动刷新冲掉输入 + 高级浮层压住连接点（两处修复）**：① 5s 自动刷新会更新 `config` 导致 `useQuickConfigDraft` 因 `fields` 引用变化重置草稿、洗掉正在输入的内容——`FlowNode` 经新增 `onEditingChange(stageId, isDirty)` 上报编辑态，`FlowPageContent` 用 `editingIds`/`editingRef` 跟踪，**有节点处于未保存 dirty 态时暂停 5s 自动刷新**（手动刷新/保存后照常），保存清 dirty 后恢复。② 展开高级时所在 `.flow-node-cell` 抬到 `z-index:30` 会压住相邻节点的连接点圆环（原 `.flow-handle` `z-index:3`）——把 `.flow-handle` 抬到 `z-index:40`，连接点端口始终在高级浮层之上不被压住（`web/frontend/components/panels/FlowPageContent.tsx`、`web/frontend/components/flow/FlowDiagram.tsx`、`FlowNode.tsx`、`web/frontend/styles/tokens.css`）。
- **项目完成度记录闭环**：将历史 `v0.25.3 Milvus 向量库构建进度条` 从 in progress 收口为 completed，并新增 `v0.25.14 Milvus/Data Cleaning 统一进度闭环` 顶部记录；`metadata.yaml` 版本从 `v0.24.3` 对齐到 `v0.25.14`，避免 TODO/CHANGELOG 已推进但 manifest 仍停留在旧版本（`TODO.md`、`metadata.yaml`、`CHANGELOG.md`）。
- **深度思考「部分可支持→全盘否定 + 告警墙」误判修复（三档支持度）**：根因——`parse_verify` 把 `missing/unsupported_claims/missing_citations/citation_mismatches/contradictions` 五个列表拍平进单一 `missing`，再经 orchestrator 与 SEA 软 gap 合并、`api.py` 直接 `len()`，造成告警数虚高（示例 74 项）且语气全盘否定；且合成/校验只有「supported/无证据」二档，问题措辞未被原文逐字命中即退化为「无证据」。改法把支持度扩为三档：`VerifyResult` 重构为硬项（`unsupported_claims+citation_mismatches+contradictions`→`hard_missing`，计入告警/触发未通过）与软项（`partial_claims+info_gaps`→`soft_notes`，仅入「思考过程」展示），`parse_verify` 不再拍平且向后兼容旧 `missing`/`missing_citations`；orchestrator `verify_missing` 只取硬项、新增 `verify_notes` 软项，SEA 非关键 gap 改入软项不再进正文告警；`_SYNTH_SYSTEM_DEEP` 允许证据部分相关时给出带 hedge 的有据推断而非一律判无证据；`_deep_warning_prefix` 按硬项计数、仅软项时给温和提示；前端 `ThinkingTraceView` 区分「未支撑点（硬）」与「部分支持/有限推断（软）」、计数 badge 只用硬项（`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/answer_synthesis.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/domain/deep_thinking.py`、`core/api.py`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- **Rerank auto 解析对显式 `"auto"` 误关 + realtime 前端新鲜度护栏**：① 根因——`get_rerank_config` 的 `explicit_provider` 分支让「配置里显式写入 `provider:"auto"`」被解析为 `noop`（只有 key 缺失时 auto 才启用本地 cross-encoder），一旦 schema 默认 `auto` 被持久化进配置文件即静默关闭 rerank；改为「只要值为 `auto`（默认或显式同义）就按装了 `sentence-transformers`→`cross_encoder`、否则 `noop` 解析」，删除 explicit 误判。② realtime（`run_dev_realtime.py`，端口 6521）只服务 `web/frontend/out`，该产物靠 `npm run build` + `tools/sync_frontend.py` 更新；只改后端、不重建前端时数据流「问答 Ask」模块看不到 rerank 字段（用户「字段根本没出现」即此）。新增 `_warn_if_frontend_stale()`：所服务 chunk 不含 `flow_quick_rerank` 标记时，启动前醒目打印重建前端 + 硬刷新指引，把该坑从玄学变成一行明确提示（`core/config.py`、`tests/mocks/run_dev_realtime.py`）。
- **Deep Thinking 可靠性小步优化**：增强 PLAN/SEA/REFINE/VERIFY prompt 对多论文横向问题、来源约束、可检索补检 query 与 citation mismatch 的要求；收敛条件改为 `SEA.sufficient` 且本轮无 discovered 且无未满足 critical，SEA 未给 gaps 时从未满足 checklist 项反推 REFINE 输入；`_compute_final` 在同一证据角色内按 `doc_id` 交错选择，降低单篇文献垄断 final evidence；最终 `verify_missing` 非空时强制 `verified=False`，避免有关键缺口但答案显示已验证（`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`）。
- **Deep Thinking 跨文档知识串线（来源标注）**：根因——deep thinking 的 SEA / VERIFY / 合成三处 prompt 拼接证据时只带 `[chunk_id]`/`[n]` 前缀、不标注来源论文，当检索（为对比类问题）正常召回多篇论文的 chunk 时，LLM 把它们当作同一无来源文本池，于是把 B 论文的发现张冠李戴成 A 论文的局限（如把 LeanMarathon 的 `goal drift`/`lost-in-the-middle` 缝进 Lean4Agent 的局限性）。修复采用生成侧来源隔离而非检索侧硬过滤（后者会砸掉系统的跨文档对比能力）：`synthesize_answer`/`build_sea_prompt`/`build_verify_prompt` 新增 `source_labels: dict[str,str]|None`，经新增的 `source_tag()` 给每条证据加 `（来源：<文档标题>）` 标注（`[n]` 编号契约不变）；`_SYNTH_SYSTEM_BASE`/`_SYNTH_SYSTEM_DEEP` 追加 `_SOURCE_ISOLATION_RULE`（禁止跨来源张冠李戴、限定单篇时只答该篇）；`VERIFY_SYSTEM` 增加「跨来源归属错误计入 `citation_mismatches`」检查项形成校验兜底。来源标签经新增的 `RetrievalOrchestrator.document_labels()` 批量解析文档标题（空回退 doc_id）：orchestrator 在 SEA 与 verify 闭环（合成/校验同享）构造并传入，`api.ask` deep fallback 据已构造的 `sources`（Zotero 优先「作者 年份」短引）拼 map 传入。全部向后兼容（`source_labels=None` 行为不变）（`core/pipelines/answer_synthesis.py`、`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/retrieval_orchestrator.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`、`tests/backend/test_cross_document_attribution.py`、`tests/backend/test_deep_thinking_orchestrator.py`）。
- **Deep Thinking 证据截断致 VERIFY 系统性误判 + 告警墙 + 预算口径**：① 根因——`synthesize_answer` 用全文 `chunk.text` 合成，但 `build_sea_prompt`/`build_verify_prompt` 写死只看每条证据前 320 字，导致答案中引用第 320 字后内容的断言被 VERIFY 一律判为「证据外断言」（示例对话整段「证据[X]中无此内容」即此假阴性）；改为 SEA `sea_evidence_clip=700`、VERIFY `verify_evidence_clip=1500` 配置化，根除假阴性、并让 SEA 看到机制细节。② 告警与正文分界——`_deep_warning_prefix` 不再把全量 missing 烤进答案正文（前端 `ThinkingTraceView` 本就可折叠并已渲染 `verify_missing`，此前重复渲染成「提示墙」），正文只留一行缺口计数 notice，明细留在折叠的思考过程；前端收起态在 badge 旁补紧凑缺口计数。③ 预算口径——`_over_budget` 由「仅统计 trace 内 SEA 调用」改为全局 `llm_calls_used`（含 PLAN/SEA/REFINE），避免放宽 `call_budget` 后名实不符（`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/i18n.ts`）。
- **扫描件 PDF 阅读面板渲染空白页**：阅读面板对扫描件 PDF（如 Massumi 1995，正文页为「JBIG2 压缩大图 + 不可见 OCR 文本层」）逐页显示全白。根因是 `pdfjs-dist@6` 把 JBIG2/JPEG2000 图像解码器迁到了 WASM，而 `getDocument` 未配置 `wasmUrl`，导致扫描页图像解码失败、整页仅剩不可见文本。修复：新增 `web/frontend/scripts/copy-pdfjs-assets.mjs` 将 pdfjs-dist 自带的 `wasm/cmaps/standard_fonts` 拷到 `public/pdfjs/`（经 next export → `pages/` 由 aiohttp 在 `/pdfjs/...` 提供，`.wasm` 返回 `application/wasm`），并由 `package.json` 的 `prebuild`/`predev` 自动同步；`PdfViewer.tsx` 给 `getDocument` 传入 `wasmUrl`/`cMapUrl`/`cMapPacked`/`standardFontDataUrl`；同时渲染异常只忽略 `RenderingCancelledException`、其余 `console.error`，HiDPI 改用 render `transform` 参数（v6 会忽略预设的 `context.setTransform`）（`web/frontend/components/panels/PdfViewer.tsx`、`web/frontend/scripts/copy-pdfjs-assets.mjs`、`web/frontend/package.json`、`web/frontend/.gitignore`、`metadata.yaml`）。

### 测试 (Tests)

- **插件软重启回归覆盖**：`tests/backend/test_api.py` 新增 `test_restart_plugin_unsupported_without_callback`（无 `reload_callback` 时返回 unsupported）与 `test_restart_plugin_schedules_reload`（注入回调时立即返回 restarting 并在后台延迟触发软重启）；验证命令：`python -m pytest -q` → 398 passed，`npx tsc --noEmit` → passed，`npm run build` → passed，`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`（`tests/backend/test_api.py`）。
- **AstrBot 配置收窄回归覆盖**：新增 schema 顶层顺序断言、WebUI 迁移字段公开断言、运行时配置写入断言，并覆盖新增 `/api/config/update` 可写字段与 deep LLM API key 禁写；验证命令：`python -m pytest tests/backend/test_config.py tests/backend/test_web_server.py -q` → 74 passed，`node node_modules/typescript/bin/tsc --noEmit --incremental false` → passed，`node node_modules/next/dist/bin/next build --webpack` → passed（`tests/backend/test_config.py`、`tests/backend/test_web_server.py`）。
- **Milvus/Data Cleaning 进度回归覆盖**：`tests/backend/test_api.py` 新增 job 合并进度计算、legacy chunk 清洗后再索引、清洗失败跳过 upsert、构建中 capabilities 暴露 `build_stage` 的断言；验证命令：`python -m pytest tests/backend/test_api.py -q -k "milvus"` → 9 passed，`python -m pytest tests/backend/test_api.py -q` → 56 passed，`node node_modules/typescript/bin/tsc --noEmit --incremental false` → passed，`node node_modules/next/dist/bin/next build --webpack` → passed（未同步 `pages/`）（`tests/backend/test_api.py`）。
- **深度思考三档化 / 进度 / 瘦身回归覆盖**：`test_deep_thinking_orchestrator.py` 更新 `parse_verify` 硬/软分离（`test_parse_verify_splits_hard_and_soft`、`test_parse_verify_three_tier_partial_is_soft`）、`verify_missing` 只含硬项 / `verify_notes` 含软项、SEA 非关键 gap 入软项、`select_final_evidence` 改为调用抽出的模块函数，新增 `test_progress_pushes_incremental_round_detail`（逐轮 detail 推送）；`test_ask_progress.py` 新增 `test_detail_roundtrip_and_optional`（detail 透传与可选向后兼容）（`tests/backend/test_deep_thinking_orchestrator.py`、`tests/backend/test_ask_progress.py`）。
- **Rerank 默认、状态、热切换与 UI mock 覆盖**：更新 `test_config.py` 覆盖无 ST 默认 noop、有 ST 默认 cross_encoder、显式 noop 优先、**显式 `auto` 与默认同义（装 ST→cross_encoder / 否则 noop）**、`mmr` 归一 noop、默认 GTE 模型与 0.2 rerank weight；更新 `test_reranker.py` 覆盖 Noop 状态、CrossEncoder idle 状态与加载失败 failed 回退；更新 `test_capabilities.py` 覆盖 Ask 节点 rerank detail、ST 依赖状态和显式 cross_encoder 缺依赖降级；更新 `test_api.py` 覆盖 `/api/config/update` 修改 rerank provider 时 `restart_required=false` 并热替换 Deep Thinking reranker（`tests/backend/test_config.py`、`tests/backend/test_reranker.py`、`tests/backend/test_capabilities.py`、`tests/backend/test_api.py`）。
- **Deep Thinking 深挖/排序/告警测试覆盖**：`test_deep_thinking_orchestrator.py` 新增 7 例——`test_parse_sea_keeps_discovered_separate_from_gaps`（discovered 不混入 gaps）、`test_discovered_absorbed_into_checklist_and_drives_refine_not_warning`（追加非 critical、驱动 REFINE、写 trace、不进告警）、`test_per_aspect_ranking_surfaces_high_rrf_subquery_chunk`（高 rrf sub_query chunk 顶到首位）、`test_reranker_is_passthrough_flags`、`test_verify_prompt_respects_clip_param`、`test_synthesize_answer_deep_style_selects_deep_system`、`test_call_budget_counts_plan_and_sea_not_only_sea`；`test_api.py` 新增 `test_deep_thinking_trace_serializes_discovered_and_origin` 与 `test_deep_thinking_verify_disabled_uses_deep_synth_fallback`，并更新告警瘦身断言（正文仅缺口计数、明细经 `thinking_trace`）；`test_config.py` 更新 deep_thinking 默认值与新字段断言（`tests/backend/test_deep_thinking_orchestrator.py`、`tests/backend/test_api.py`、`tests/backend/test_config.py`）。
- **深度思考降级原因测试覆盖**：`test_deep_thinking_orchestrator.py` 补充所有降级路径的 `degraded_reason` 断言：`test_converges_when_sea_sufficient` 验证正常收敛时为空，`test_llm_unavailable_degrades_to_baseline` 验证 PLAN 阶段异常传递 `str(exc)`，新增 `test_sea_llm_unavailable_degrades_to_baseline` 和 `test_refine_llm_unavailable_degrades_to_baseline` 覆盖 SEA/REFINE 阶段异常，`test_critical_unmet_degrades` 验证 `"关键"` 字样，`test_verify_skipped_when_degraded` 验证非空（`tests/backend/test_deep_thinking_orchestrator.py`）。

- **Deep thinking 前端入口与思考过程可视化**：ChatPanel 查询设置新增「深度思考」检索模式（`deep_thinking`，不依赖 LightRAG、无条件可选）；assistant 消息新增可折叠的「思考过程」区块（默认收起，复用 sources 的轻量样式），展开显示信息点清单（✓ 满足 / ○ 未满足、关键项标 *）、逐轮子查询与缺口、答案校验状态徽章（已验证 / 已降级 / 未验证）与估算 tokens；`actual_retrieval_mode` 的 deep 三态（`milvus_deep` / `astrbot_deep_fallback` / `deep_degraded_to_default`）正确显示标签；前端类型与中英 i18n 同步并重建静态产物（`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`pages/`）。
- **Deep thinking 答案级 verification 闭环 + rerank 去模型依赖 + 内容去重**：(1) rerank 默认改为 `noop`（零模型零部署），cross-encoder 改为显式 `provider=cross_encoder` 才懒加载下载，历史值 `auto`/`mmr` 归一为 `noop`——重排精度改由 verification 承担，不再为重排部署模型（`core/config.py`、`core/repository/reranker/__init__.py`、`_conf_schema.json`）。(2) `retrieve_with_outcome` 在 RRF 融合后按 `content_hash` 去重，剔除「不同 chunk_id 但内容相同」的近重复证据（同段落跨文献 / 分块重叠），避免冗余上下文与误导充分性判断；default 与 deep 路径均受益（`core/pipelines/retrieval_orchestrator.py`）。(3) deep_thinking 新增答案级 verification 完整闭环：orchestrator 收敛后合成 draft → 校验「是否被证据完全支撑 / 是否完整」→ 不合格则把缺失点当作补充检索方向再检一轮并重合成，受 `max_verify_rounds` + budget 限；产出经校验的 `answer` 由 api.ask 直接采用（不再重复合成），合成 LLM 不可用则退回 api.ask 合成、校验 LLM 不可用则用 draft，均不打崩请求；新增 `verify_enabled`/`max_verify_rounds` 配置与 `thinking_trace.verified`/`verify_missing`，新增共享 `core/pipelines/answer_synthesis.py`（`core/pipelines/deep_thinking_orchestrator.py`、`deep_thinking_prompts.py`、`core/domain/deep_thinking.py`、`core/config.py`、`core/api.py`、`_conf_schema.json`）。
- **Deep Thinking 迭代检索（FAIR-RAG + Reranker）**：新增手动 `retrieval_mode="deep_thinking"`（collection 必填）。在不重写 Milvus/SQLite/AstrBot 混合召回内核的前提下，于其上层引入 FAIR-RAG 式迭代：PLAN 把问题分解为带 `id` 的 checklist + 子查询（单次 LLM），多轮「检索 → 结构锚点 pinned 保护 → cross-encoder 重排 + 自适应截断 → SEA 充分性审计 → REFINE 补检」，收敛或达 `max_rounds` 后由 `api.ask` 统一合成（orchestrator 不产 answer，杜绝重复合成）。证据保证「永不比 baseline 差」：baseline 先于 LLM 检索并保底进 evidence；证据为空 / 关键 checklist 未满足 / gaps 占比过阈 / 任一 LLM 调用异常 → 回退 baseline（`actual_retrieval_mode=deep_degraded_to_default`，evidence 严格等于 baseline_floor）；非 pinned 的 conflicting 证据于循环后一次性过滤。返回新增 `thinking_trace`（清单满足情况 + 逐轮 gaps，供前端渲染思考过程）。配套新增 reranker 子系统（`core/repository/reranker/`：base ABC、noop、懒加载 bge_local、`build_reranker` 工厂——缺 sentence-transformers 自动 noop，不影响普通 ask）、`core/utils/cutoff.py`（`adaptive_cutoff` 拐点截断）、`core/domain/deep_thinking.py`、`core/pipelines/deep_thinking_orchestrator.py` 与 `deep_thinking_prompts.py`；`RetrievalOutcome` 增旁路 `per_chunk_signals`（rrf_score/anchor_hit）但不改 RRF 排序与既有 `chunks` 契约；config 增 `RerankConfig`/`DeepThinkingConfig`，`_conf_schema.json` 与 `CONFIG_KEY_POLICY` 最小暴露 `max_rounds`/`max_sub_queries`/`wide_top_k`/`rerank.provider`/`rerank.model`（`core/pipelines/retrieval_orchestrator.py`、`core/config.py`、`core/api.py`、`core/plugin_initializer.py`、`_conf_schema.json`）。
- **通用论文结构识别与召回锚点泛化**：结构化 chunker 收紧数字标题识别，过滤孤立 `0/00`、公式编号、表格数字和句首数字正文误判，同时支持 `**1. Introduction**`、`1 Introduction`、`2.1 Method`、`Appendix A` / `A.1` 等通用论文标题形态；chunk metadata 新增 `section_level` 和列表型 `anchor_labels`，覆盖 chunk 内所有 `Figure/Table/Equation` label；SQLite anchor fast-path 支持 `section 2`、`chapter 3`、`第2节`、`appendix A`、`Fig. 1` / `Figure 1`、`Table 1`、`Eq. 2` / `Equation 2`，并保持单独数字不作为强锚点（`core/managers/chunking.py`、`core/pipelines/retrieval_orchestrator.py`）。
- **文档面板 chunk 标题渲染**：新增轻量 `parseChunkText()` 解析器和 `ChunkText` 展示组件，只在 chunk/段落开头识别 `**T14**`、`**2.** **Title**`、`_2.1._ _Title_` 这类结构标题，并把标题渲染为紧凑标签/标题行；标题后的换行正文和同一行正文继续作为普通段落显示，正文中的普通 `**bold**` 不会被误判；前端静态产物已同步到 `pages/`（`web/frontend/lib/chunkText.ts`、`web/frontend/components/panels/DocumentsPanel.tsx`、`tests/frontend/test_chunk_text_parser.py`、`pages/`）。
- **structural_v3 结构化分块与召回 handle**：新增 `core/managers/chunking.py`，将 clean Markdown 解析为 front matter、章节标题、子标题、段落、figure/table caption、list/equation 等结构块，再按 block 边界打包 chunk；仅当单个 block 超过硬上限时才启用 citation-aware sentence split，避免在 `et al.`、括号引用或普通段落中间硬切。`IngestManager` 改为调用结构化 chunker，并将 schema 升级为 `clean_md_structural_v3`，chunk metadata 增加 `section_type`、`section_label`、`section_path`、`section_title`、`subsection_label`、`block_types` 与精确 section offset；召回编排层新增 SQLite anchor fast-path，支持 query 中的 T 编号、编号章节、figure/table 和 subsection anchor 直达对应 chunk（`core/managers/chunking.py`、`core/managers/ingest_manager.py`、`core/pipelines/retrieval_orchestrator.py`）。
- **PDF 清洗后处理与 paragraph-aware Milvus 分块**：在 PyMuPDF4LLM 输出后增加确定性清洗，去除重复页眉、边缘页码，修复软连字符断词、伪段落空行与异常换行；Milvus chunker 改为按标题 / 段落 / 句末 / 词边界分层切分，避免普通句中硬切和短残片，并在 chunk metadata 写入 `chunk_schema`、`section_label`、`section_start_char`、`section_end_char`。Milvus 索引前会识别旧式 chunk id、缺 `start_char/end_char` 或缺 schema 的 legacy chunks，从现有 `clean.md` 重建 SQLite chunks 并标记 `needs_reindex`；SQLite 词汇召回同步加强中英混排 anchor（如 `T55具体...`）和标题锚点排序，避免优先命中跨引用而非正文标题（`core/managers/markdown_extractor.py`、`core/managers/ingest_manager.py`、`core/api.py`、`core/pipelines/retrieval_orchestrator.py`）。
- **LightRAG 构建暂停/恢复持久化与整体进度修复**：新增 `017_graph_build_pause_state` 迁移并扩展 build job 持久化契约，保存 `pause_requested`、`paused_at`、`paused_seconds`、`progress_current` 与 `progress_total`；后端改为线性单队列，支持 LLM 调用中请求暂停、下一安全点进入 `paused`、同一 `job_id` 恢复、重启后从持久化 paused job 继续未 `indexed` 文档，并让 elapsed 排除真正暂停时间；整体进度覆盖 LRAG chunk、文档收尾与 collection finalize，避免 chunk 完成后提前显示 100%；前端将开始/暂停/等待暂停/继续控制收敛到 FilePanel，ChatPanel 启动构建后关闭确认框并引导到文件面板，移除阻塞聊天区的浮动构建弹窗（`migrations/017_graph_build_pause_state.sql`、`core/api.py`、`core/lightrag_core.py`、`core/plugin_initializer.py`、`core/repository/source_store/base.py`、`core/repository/source_store/memory.py`、`core/repository/source_store/sqlite.py`、`web/frontend/components/panels/FilePanel.tsx`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/app/(console)/layout.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`pages/`）。
- **笔记面板支持本地标签行内编辑**：在文档笔记元信息区新增轻量 `TagEditor`，本地文档可添加/删除标签并通过 `patchDocument(doc_id, { tags })` 保存；Zotero/read_only 文档仅展示只读标签提示，继续由 Zotero 同步维护；同步拆出 `DocumentMeta` 让 `NotePanel` 回到文件大小红线内（`web/frontend/components/panels/NotePanel.tsx`、`web/frontend/components/panels/TagEditor.tsx`、`web/frontend/components/panels/DocumentMeta.tsx`、`web/frontend/lib/i18n.ts`、`pages/`）。
- **Zotero 快速配置改为标签式可切换面板**：数据流 Zotero 节点不再用下拉框切换 access_mode，改为仿文档面板 md/pdf 的分段标签（`本地离线` / `在线 API`）。本地页签含端口、自动解析目录（截断 + hover）、覆盖目录选择 + 诊断行；在线页签含 API key 保存/清除 + 用户徽标。`sync_mode / storage_mode / linked_root / 自动同步` 收进折叠「高级」区；底部新增「立即同步 + 上次同步状态」动作条（`web/frontend/components/flow/ZoteroQuickConfig.tsx`、`web/frontend/components/flow/QuickConfigPanel.tsx`）。
- **Zotero 本地干跑探针**：新增 `ZoteroSyncPipeline.probe_local_read()`（只读 zotero.sqlite 快照、返回条目/集合/附件/PDF 计数，不 mirror/不写库；server 模式跳过），`api.probe_zotero_local()` 合并端口连通性与计数，新增 `GET /api/zotero/probe` 路由（`core/pipelines/zotero_sync_pipeline.py`、`core/api.py`、`web/server.py`）。
- **前端探针客户端**：`lib/api.ts` 新增 `ZoteroProbeResult` 接口与 `probeZoteroLocal()`（含 mock 分支）；`lib/i18n.ts` 中英补齐标签 / 探针 / 同步相关键（`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。

### 修复 (Fixed)

- **质量门禁闭环**：修复 Python `ruff check .` 中的长行、import 排序、未使用变量与类型写法问题；修复 `FlowNode` 条件调用 React hooks 的风险；将 aiohttp app 运行态对象改为 `web.AppKey`，并修复 cookie 测试的 URL deprecation warning（`core/api.py`、`core/managers/chunking.py`、`core/managers/ingest_manager.py`、`core/milvus_build.py`、`core/pipelines/deep_thinking_prompts.py`、`core/repository/source_store/memory.py`、`web/server.py`、`web/frontend/components/flow/FlowNode.tsx`、`tests/backend/test_web_server.py`）。
- **`rebuild.sh` Docker 执行修复**：将 `rebuild.sh` 统一为 LF 换行，并通过 `.gitattributes` 固定 `*.sh text eol=lf`，修复 Linux Bash 下 CRLF 导致的 `$'\r': command not found` 与函数定义解析失败；`bash -n rebuild.sh` 与完整 `bash rebuild.sh` 均已通过，后端 `26618` 与前端 `26619` ready（`rebuild.sh`、`.gitattributes`）。
- **`rebuild.sh` 端口占用误判修复**：启动前按 `26618/26619` 清理监听进程，避免旧的 `astrbot run` 占用 `26618` 时被健康检查误判为新调试后端；等待阶段改为同时检查新启动 PID 存活，后端绑定失败会直接输出日志并失败；前端 dev server 显式注入 `KR_API_PORT` 并允许 `127.0.0.1` dev origin，修复 26619 代理到旧后端导致密码不一致与 HMR 被拦的问题（`rebuild.sh`、`web/frontend/next.config.ts`）。
- **Deep Thinking 缺口率文案修正**：将证据不足降级判定中的「缺口率」从 `len(gaps) / len(checklist)` 改为未满足 checklist 项占比，并且仅在 SEA 明确给出 gap 时应用该降级条件；用户可见原因从「证据缺口率 175%」这类无意义百分比改为「未满足检查项 X/Y（Y% ≥ 阈值 Z%）」；补充多 gap 少 checklist 的回归测试，确保不会再出现超过 100% 的缺口率文案（`core/pipelines/deep_thinking_orchestrator.py`、`tests/backend/test_deep_thinking_orchestrator.py`）。
- **Deep Thinking 证据不足回答警告**：`DeepThinkingOrchestrator.run()` 新增 `answer_question`，检索/PLAN/SEA/REFINE 继续使用 retrieval query，最终合成与 VERIFY 使用用户原始问题，避免开启英语召回后答案围绕翻译 query 生成；deep thinking 降级或未验证时，`api.ask()` 会在最终答案正文开头追加证据不足/未验证警告，并展示降级原因或 `verify_missing`；VERIFY JSON 解析失败不再视为通过，改为保留 draft 但标记 `verified=False`；普通与 deep 合成 prompt 均补充“证据不足必须说明、不用外部知识补齐”的约束（`core/pipelines/deep_thinking_orchestrator.py`、`core/pipelines/answer_synthesis.py`、`core/api.py`、`tests/backend/test_deep_thinking_orchestrator.py`、`tests/backend/test_api.py`）。
- **JSTOR 等 PDF 提取失败与全局深度思考静默退化修复**：(1) 在 `pymupdf4llm.to_markdown()` 中传入 `ignore_alpha=True`，以支持提取带有透明遮罩/水印（如 JSTOR PDF）的学术论文正文，使得 Massumi (1995) 等文档的文本抽取量从 5.5k 字符恢复到正常的 66k 完整文本（`core/managers/markdown_extractor.py`）；(2) 前端 `ChatPanel` 的检索模式下拉框在未选择集合时禁用“深度思考”模式，并增加 `useEffect` 副作用监听，在切换取消集合选择时自动将 `retrievalMode` 重置为 `"default"`，避免向后端发起不带集合参数的深度思考/高精度请求而触发 `ValueError` 报错（`web/frontend/components/panels/ChatPanel.tsx`）。

- **弹窗层级（z-index / 浮层裁切）系统性修复**：浮层（popover / dropdown / tooltip / modal）此前内联渲染（`position:absolute/fixed` + 散乱 z-index），被祖先 stacking context（`fx-glass` 的 `backdrop-filter`、面板 `transform`/`will-change`、`position:relative+z-index`）与 `overflow:hidden/auto` 关住，导致如 ChatPanel 齿轮「设置 popover」被相邻面板盖住 / 在面板边缘裁切。改法：(1) 新增统一 z-index 量表单一真源 `web/frontend/lib/zLayers.ts`（base/raised/widget/dialog/panel/dropdown/tooltip/toast，`dropdown/tooltip>dialog` 以支持 modal 内嵌套），并在 `styles/tokens.css` `:root` 同步 `--z-*` CSS 变量供 `.flow-custom-select`/`.dir-picker-overlay` 引用；(2) 新增锚定浮层原语 `components/ds/Popover.tsx`（`createPortal` 到 `document.body` + `getBoundingClientRect` 定位 + scroll/resize 重算 + outside-click/Escape）；(3) `ds/Tooltip.tsx`、`ds/Select.tsx`、ChatPanel 设置 popover 改用 Popover；`ds/Modal.tsx`、ChatPanel 精度弹窗、`FilePanel` ×3 全屏弹窗统一 portal 到 body 取 `Z.dialog`；`PerfPanel`/`TerminalPanel`/`Toast`/`TopBar`/`BuildWidget`/login 对齐量表（`web/frontend/lib/zLayers.ts`、`components/ds/Popover.tsx`、`ds/Tooltip.tsx`、`ds/Select.tsx`、`ds/Modal.tsx`、`ds/index.ts`、`panels/ChatPanel.tsx`、`panels/FilePanel.tsx`、`ui/PerfPanel.tsx`、`ui/TerminalPanel.tsx`、`ui/Toast.tsx`、`layout/TopBar.tsx`、`build/BuildWidget.tsx`、`app/(console)/layout.tsx`、`styles/tokens.css`）。
- **文档面板 chunk 预览自动刷新**：`list_document_chunks()` 与 `get_chunk_context()` 在读取 SQLite chunks 前会复用当前摄入管理器的 legacy 检测与重建逻辑，发现旧 chunk id、旧 schema 或缺 `start_char/end_char` metadata 时，从制品包 `clean.md` 自动重建 structural_v3 chunks 再返回；Milvus 索引路径同步复用同一个 helper，避免“索引是新版、前端预览仍是旧切片”的分叉（`core/api.py`）。
- **本地 runtime 播种 chunker 对齐**：6521 本地实时测试脚本不再手写固定窗口 chunk，改为使用 clean Markdown extractor 与 structural_v3 chunker 生成 `clean.md`、`pages.json` 和 `_c0000` 风格 chunk id，避免 mock runtime 文档面板继续展示旧切片（`tests/mocks/run_dev_realtime.py`，本地 ignored 脚本）。
- **父章节标题极短 chunk 合并**：结构化 chunker 允许短的父章节标题连续向前合并到第一个子章节正文块，避免 `2` 与 `2.1` 之间产生只有标题的极短 chunk；合并后 metadata 新增 `section_labels` 与 `section_paths`，召回 fast-path 会同时匹配父章节和子章节 anchor，保证 `2` / `2.1` 这类查询都可定位到合并后的正文 chunk（`core/managers/chunking.py`、`core/pipelines/retrieval_orchestrator.py`）。

### 性能优化 (Performance)

- **深度思考每轮子查询检索并行化**：`_gather_round` 把多个 sub_query 的检索由串行 `await` 改为 `asyncio.gather` 并发（gather 保序、去重 `setdefault` 结果一致，纯提速、不改语义、不减轮）（`core/pipelines/deep_thinking_orchestrator.py`）。

### 架构健康 (Refactor)

- **前端 lint 零噪声整理**：忽略 build 生成的 `public/pdfjs/**` vendor 资源，避免 ESLint 扫描 generated WASM fallback；清理未使用 import/变量与废弃 `BuildCard`，并把可安全派生的前端状态从 effect 内同步 `setState` 改为 lazy state、keyed state 或事件驱动更新（`web/frontend/eslint.config.mjs`、`web/frontend/components/flow/DirPickerDialog.tsx`、`QuickConfigPanel.tsx`、`web/frontend/components/modals/SettingModal.tsx`、`web/frontend/components/panels/DocumentsPanel.tsx`、`PdfViewer.tsx`、`TagEditor.tsx`、`FilePanel.tsx`、`ChatPanel.tsx`）。
- **深度思考编排器瘦身（回到 600 行红线内）**：从 `deep_thinking_orchestrator.py` 剥离两个无状态模块——`deep_thinking_evidence.py`（`rank_candidates`/`select_final_evidence`：证据打分与最终选取）与 `deep_thinking_view.py`（`live_detail`/`serialize_outcome`：思考过程序列化，供 orchestrator 实时进度与 `api._serialize_deep_thinking` 共用，杜绝两处各写一份导致的漂移）；orchestrator 由 687 行降至 600 行、只剩控制流（`core/pipelines/deep_thinking_orchestrator.py`、`core/pipelines/deep_thinking_evidence.py`、`core/pipelines/deep_thinking_view.py`、`core/api.py`）。
- **QuickConfigPanel 拆分**：`QuickConfigPanel` 退化为按阶段分发的 dispatcher，Zotero 阶段交给独立的 `ZoteroQuickConfig`；共享字段原语（`FieldControl`、字段构造器、读取辅助）从 `QuickConfigPanel` 导出复用，主文件由 600 行降至约 525 行，回到文件大小红线内（`web/frontend/components/flow/QuickConfigPanel.tsx`、`web/frontend/components/flow/ZoteroQuickConfig.tsx`）。

### 样式 (Style)

- **数据流节点界面美术三轮修正**：① 高级弹窗改回「分离式」浮层卡片——`.flow-quick-advanced-panel` 由紧贴节点底（`top:100%`、只圆下两角、去上边框）回退为带 8px 间隙、四角全圆 `border-radius:12px`、四边边框的独立卡片（仍 `position:absolute` Portal 在节点底部槽位、不挤动其他节点）。② 左侧单条辉光竖条 → 整圈发光薄边框——删除 `.flow-node-stripe`（含 `<span>`、`::after`、`@keyframes stripeFlow`），`.flow-node` 改为 `1px` 随 `--flow-st` 着色的薄边 + `box-shadow` 整圈光晕（边框外不受 `overflow:hidden` 裁剪，把整个 node 包住，比原 3px 竖条更薄）；hover/选中/未保存/待重启/off/dest 各状态光晕统一整合（dirty 蓝 / restart 琥珀 / off 不发彩光）；节点边框静态发光，数据流「流动」感保留在边线 `.flow-conn-live`（`web/frontend/components/flow/FlowNode.tsx`、`web/frontend/styles/tokens.css`）。
- **数据流节点界面美术二轮修正**：① 高级折叠移到节点最底部——`FlowNode` body 末尾新增 `.flow-node-advanced-slot` 槽位，`AdvancedSection` 经 React `createPortal` 渲到该槽位（折叠按钮在节点最底部，slot 为空时回退内联），展开浮层由距底 8px 改为 `top:100%` 紧贴、只圆下两角、无缝衔接节点底，仍 `position:absolute` 不挤动其他节点与边。② 边/连接点改为「发光圆环 + 发光曲线」统一风格——`.flow-handle` 由 11px 实心点改 14px 空心发光圆环（亮色描边 + 外发光，去掉 active 填充以读作镂空）；`.flow-conn-base` 由灰色 mix 改鲜亮状态色 + 双层 `drop-shadow` 光晕（off 边关光晕）；`.flow-conn-live` 由密集蚂蚁线（`5 12`/1.05s）改一段长间隙短亮段（`14 600`/3.2s + `connFlow` 终值 -614）缓慢流过，仅 ready 边；保留「可选来源」靛紫菱形端点（`web/frontend/components/flow/FlowNode.tsx`、`QuickConfigPanel.tsx`、`ZoteroQuickConfig.tsx`、`web/frontend/styles/tokens.css`）。
- 新增 `.flow-quick-modetab`、`.flow-quick-diag`、`.flow-quick-advanced`、`.flow-quick-syncbar` 等 token，统一标签切换 / 诊断行 / 折叠区 / 同步条视觉（`web/frontend/styles/tokens.css`）。

### 测试 (Tests)

- **v0.26.0 质量门禁验证**：Docker 环境中 `ruff check .`、`python -m mypy`、`python -m pytest -q`（398 passed）、`npm run lint`、`node node_modules/typescript/bin/tsc --noEmit --incremental false`、`npm run build`、`python tools/sync_frontend.py --check`、`bash -n rebuild.sh` 与 `bash rebuild.sh` 均通过；`python tools/sync_frontend.py` 同步 362 个前端静态产物到 `pages/`；复验 `26618/26619` 登录链路，`admin / 111111` 登录后 `/api/auth` 均返回 `logged_in: true`。
- **Deep Thinking 可靠性回归覆盖**：`test_deep_thinking_orchestrator.py` 新增 prompt 契约、critical 未满足不误收敛、SEA 无 gaps 时从 checklist 反推 REFINE、doc-aware final evidence、structural anchor 优先级、`VERIFY_OK` 被 soft missing 否决等用例；补跑 `test_api.py`、跨文档来源标注、retrieval/reranker 回归和 compileall（`tests/backend/test_deep_thinking_orchestrator.py`）。
- **PDF 清洗与分块回归覆盖**：新增页眉/页码/断词/伪段落清洗、paragraph-aware chunk 边界、section metadata、legacy chunk 重建、文档面板预览自动重建、通用论文数字标题误判防线、Appendix、Figure/Table/Equation anchor list、T 编号标题锚点召回、citation-aware sentence split、编号章节、父章节短标题合并、图表 caption 和 subsection anchor fast-path 测试；验证命令包括 `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q`、`python -m pytest tests\backend\test_api.py -q` 与 `python -m compileall ...`。私有 PDF 仅做本地手工评估，不在变更记录中保存标题、正文或 chunk 预览（`tests/backend/test_ingest_manager.py`、`tests/backend/test_retrieval_orchestrator.py`、`tests/backend/test_api.py`）。
- **LightRAG 暂停恢复回归覆盖**：补充 SQLite migration 默认值、启动清理保留 paused job、LLM 中 pause_requested 持久化、pause gate 入库 paused、同进程恢复累计 `paused_seconds`、重启后复用原 `job_id` 处理未 `indexed` 文档、finalize 前进度小于 100% 等用例；验证命令包括 `python -m pytest tests\backend\test_build_hardening.py tests\backend\test_sqlite_source_store.py tests\backend\test_api.py tests\backend\test_web_server.py -q`、`node node_modules/typescript/bin/tsc --noEmit`、`node node_modules/next/dist/bin/next build --webpack`、`python tools\sync_frontend.py` 与 `python tools\sync_frontend.py --check`（`tests/backend/test_build_hardening.py`、`tests/backend/test_sqlite_source_store.py`）。
- `test_zotero_sync.py` 新增 `probe_local_read` 三例（计数、缺目录、server 跳过）；`test_web_server.py` 新增 `/api/zotero/probe` 路由 smoke（`tests/backend/test_zotero_sync.py`、`tests/backend/test_web_server.py`）。

## [v0.24.6] — 2026-06-11

### 新增功能 (Added)

- **Milvus Lite 升级为必装依赖**：`requirements.txt` 将 `pymilvus[milvus_lite]>=2.5,<3.0` 从可选升为必装；`core/capabilities.py` 的 `OptionalDependency` 标记 `required=True`，前端依赖状态区区分必需 / 可选语义（`requirements.txt`、`core/capabilities.py`）。
- **AstrBot KB 前端锁定**：`FlowNode.tsx` 在 `vector_store` 阶段 segmented control 中将 `"astr"` 选项设为 locked/disabled，附带锁图标和 i18n tooltip，AstrBot KB 仅保留为后端兜底代码，不可在前端选择（`web/frontend/components/flow/FlowNode.tsx`、`web/frontend/lib/i18n.ts`）。
- **WorkflowModal 全屏**：modal 改为 `fullscreen` 模式，`width: 100vw`、`height: 100vh`，内容区 flex 铺满视口（`web/frontend/components/modals/WorkflowModal.tsx`）。
- **FlowPageContent 5 秒自动刷新，删除 recheck 按钮**：移除手动"重新检测"按钮；面板打开期间每 5 秒自动调用 `recheckDependencies()` + `getEffectiveConfig()` + `getZoteroConfig()`，带 `refreshInFlight` 并发保护与卸载清理（`web/frontend/components/panels/FlowPageContent.tsx`）。
- **状态图例移到 header 右侧**：原 recheck 按钮位置改为 `.flow-topo-status-panel`，展示就绪 / 待处理 / 未启用图例、并联提示和"每 5 秒自动刷新状态"提示（`web/frontend/components/panels/FlowPageContent.tsx`、`web/frontend/styles/tokens.css`）。
- **TopBar 5 秒健康轮询**：TopBar 挂载后每 5 秒调用 `getCapabilities()` + `deriveWorkflowStatus()`，关键环节 degraded 时按钮变红；不再只在挂载时检测一次（`web/frontend/components/layout/TopBar.tsx`）。
- **Zotero 加密密钥存储**：新增 `core/secret_store.py`（`EncryptedSecretStore`）；Zotero API key 以加密形式落盘，API 响应只返回掩码，不返回明文；新增 `POST /api/zotero/server-key`（验证 + 保存）和 `DELETE /api/zotero/server-key`（`web/server.py`、`core/api.py`、`core/secret_store.py`）。
- **Zotero Web API reader**：新增 `core/adapters/zotero/web_api.py`（`ZoteroWebApiClient`、`ZoteroWebApiReader`），按官方 Web API v3 读取个人库文献、附件元数据；同步管线按 `access_mode=local|server` 分支路由（`core/adapters/zotero/web_api.py`、`core/pipelines/zotero_sync_pipeline.py`）。
- **Zotero 快速配置重做**：`QuickConfigPanel.tsx` 中 Zotero 阶段支持 local / server 双模式；local 显示端口（默认 23119）与自动解析目录（截断 + hover 全路径）；server 显示 password 输入、掩码状态、保存 / 清除按钮，带 `?` 角标问号提示（`web/frontend/components/flow/QuickConfigPanel.tsx`）。
- **LightRAG LLM 只读摘要**：LightRAG 快速配置中 LLM 模型改为 `readonlyField`，显示 `<provider - model>` 格式；LLM 地址（base_url）字段已移除（`web/frontend/components/flow/QuickConfigPanel.tsx`）。
- **Zotero 节点横向拉宽**：数据流图 col 1（Zotero 列）从 380px 扩大至 480px；输入框、只读字段、toggle、custom-select 控件 padding / min-height 各降 2–4px；resolved_data_dir 改为 1/3 列宽并添加 hover 全路径 title（`web/frontend/styles/tokens.css`、`web/frontend/components/flow/QuickConfigPanel.tsx`）。

## [v0.24.5] — 2026-06-11

### 新增功能 (Added)

- **设置模态框「通用」Tab**：将原「外观」Tab 改名为「通用」，新增「账户」Card，内含退出登录按钮（`web/frontend/components/modals/SettingModal.tsx`、`web/frontend/lib/i18n.ts`）。
- **TopBar 精简**：语言切换和退出登录 IconButton 移入设置弹窗，TopBar 右侧仅保留「设置」「AstrBot」「数据流」三个触发按键（`web/frontend/components/layout/TopBar.tsx`、`web/frontend/app/(console)/layout.tsx`）。
- **数据流按键状态脉冲**：挂载时拉取 `/api/capabilities` + `/api/zotero/config`，判断管道就绪状态与 R2/Zotero 配置，按钮外层包裹 `wf-pulse-red`（1.2 s 强脉冲）/ `wf-pulse-green`（2.4 s 弱脉冲）/ `wf-pulse-purple`（2.4 s 弱脉冲）CSS class（`web/frontend/app/globals.css`、`web/frontend/components/layout/TopBar.tsx`）。
- **Ask 输入框辉光轨道**：Composer `<div>` 接入已有的 `.ask-card` / `.ask-card--collection` / `.ask-card--loading` CSS class，focus 时出现旋转辉光轨道，加载时切换为强辉光（`web/frontend/components/panels/ChatPanel.tsx`）。
- **查询设置锁定**：`graph_only` 和 `high_precision` 在非 `lr:` 集合时以 38% 透明度不可点击；新增「全文检索」模式（`fulltext`），仅在选中单篇文章时启用，文档上限 60 000 字符（`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。

## [v0.24.3] — 2026-06-11

### 新增功能 (Added)

- **终端日志面板**：将 `TerminalPanel` 从运行目录浏览器完整改造为 terminal 风格日志查看器，复用 `getLogs()` / `/api/logs` 环形缓冲接口。支持首次加载 200 条、每 2.5 s 增量轮询、自动滚到底部（用户手动上滚时暂停）、刷新与清屏按钮（清屏仅清前端显示，不影响后端缓冲）；日志行以 `时间 / level / 来源 / 消息` 四列 grid 布局展示，ERROR/CRITICAL 红色、WARNING 橙色、DEBUG 暗色、INFO 绿色（`web/frontend/components/ui/TerminalPanel.tsx`）。
- **双模挂载保持**：`variant="embedded"` 铺满设置弹窗内容区，`variant="floating"`（默认）从侧边栏触发为浮层；两种模式共用同一日志组件（`web/frontend/components/ui/TerminalPanel.tsx`、`web/frontend/components/rail/Rail.tsx`）。
- **i18n 补齐**：新增中英文键 `terminal_trigger` / `terminal_trigger_title` / `terminal_panel_title` / `terminal_refresh` / `terminal_clear` / `terminal_auto_scroll` / `terminal_auto_scroll_short` / `terminal_loading` / `terminal_empty` / `terminal_unavailable`（`web/frontend/lib/i18n.ts`）。

### 架构健康 (Refactor)

- 移除 `TerminalPanel` 内部的 `SystemInfo`、`FileEntry`、目录钻取等旧文件浏览逻辑；侧边栏入口文案由"运行目录"统一改为"终端日志"，与实际功能一致（`web/frontend/components/ui/TerminalPanel.tsx`、`web/frontend/components/rail/Rail.tsx`）。

## [v0.24.2] — 2026-06-11

### 新增功能 (Added)

- **LightRAG 构建加固 — 并发守卫**：`build_graph()` 在发起新任务前检查同集合是否已有 queued/running 任务，有则抛 RuntimeError（HTTP 409），防止同一 workspace 被并发写入（`core/api.py`）。
- **LightRAG 构建加固 — 干净关闭**：新增 `_build_tasks: dict[str, asyncio.Task]` 字段保存任务句柄；`_run_lightrag_build_job()` 显式 `except asyncio.CancelledError` 将 status 设为 `"interrupted"` 后 re-raise；新增 `cancel_build_tasks()` 方法；`teardown()` 调用它，确保重启时构建状态正确落盘（`core/api.py`、`core/plugin_initializer.py`）。
- **LightRAG 构建加固 — workspace 串行化**：`LightRAGCoreRegistry` 新增 `_collection_locks`，`insert_document`/`delete_doc`/`reset_workspace` 全部通过 per-collection `asyncio.Lock` 串行化，消除构建期间的文件竞争（`core/lightrag_core.py`）。
- **FilePanel 构建状态区**：LightRAG 集合区 SectionHead 下方新增 `ActiveBuildCard` 内部组件，统一展示所有集合的实时构建进度（进度条 + 百分比 + 集合名）；构建中断后展示「图谱构建中断」标签与「继续构建」按钮（`web/frontend/components/panels/FilePanel.tsx`）；同步 i18n key：`file_build_interrupted` / `file_build_resume` / `file_build_queued`（`web/frontend/lib/i18n.ts`）。

### 测试 (Tests)

- 新增 `tests/backend/test_build_hardening.py`（5 个测试）：并发构建守卫（同集合 → RuntimeError，跨集合 → 成功，已完成任务 → 可重建）、CancelledError → status=interrupted、`cancel_build_tasks()` 清理句柄。

## [v0.24.4] — 2026-06-11

### 修复 (Fixed)

- **Docker 内 26619 前端预览启动链路加固**：devcontainer 镜像定义从 NodeSource `setup_18.x` 升级到 `setup_20.x`，并在 Docker 层发布 `26619:26619` 与 `26618:26618`，避免 `next@16.2.6` 在 Node 18 中直接失败，以及 26619/26618 依赖编辑器端口转发导致的不稳定（`D:\dev-workspace\.devcontainer\Dockerfile`, `D:\dev-workspace\.devcontainer\devcontainer.json`）。
- **devcontainer Dockerfile 编码修复**：将 `D:\dev-workspace\.devcontainer\Dockerfile` 与 `devcontainer.json` 重写为 UTF-8 无 BOM，修复 Dev Containers 生成 `Dockerfile-with-features` 后在 `FROM` 前出现隐藏字符，导致 Docker 报 `unknown instruction: FROM` 的问题。
- **`rebuild.sh` Docker 运行自检与固定监听地址**：脚本启动第 0 步校验 Node `>=20.9.0`，Node 或 lockfile 变化时自动刷新 `node_modules`，并在缺少 `aiohttp` 或 `requirements.txt` 更新时自动安装轻量后端依赖；后端以 `0.0.0.0:26618` 启动，前端 dev server 以 `0.0.0.0:26619` 启动，健康检查和输出统一使用 `http://127.0.0.1:*`，避免 `localhost` 命中宿主机 IPv6 旧进程（`rebuild.sh`）。
- **Next dev manifest 500 修复**：生产 build 继续保留 `NEXT_TEST_WASM=1` 规避 Windows bind mount lock 问题，但 dev server 不再设置该变量；Node 20/Linux 容器下强制 WASM 会导致 `.next/dev/routes-manifest.json` 与 `middleware-manifest.json` 缺失并使 26619 返回 500（`rebuild.sh`）。
- **`rebuild.sh` 一键重建失败、26619 端口无前端内容**：根因是 stale TS 增量缓存 `web/frontend/tsconfig.tsbuildinfo` 仍记录已删除的 `app/api/[...proxy]/route.ts`，生产构建读取该缓存时 `ENOENT` 失败；脚本 `set -e` 在第 3 步即中断，dev server 永远不启动。修复：
  - `web/frontend/package.json` 的 `dev` / `build` 脚本在编译前追加清理 `tsconfig.tsbuildinfo`（`rm -rf .next tsconfig.tsbuildinfo`），令二者自愈。
  - `rebuild.sh` 第 3 步构建前再显式 `rm -f tsconfig.tsbuildinfo`（防 `package.json` 被回退）。
- **`rebuild.sh` 进程清理抓不到旧 dev server**：`next dev` 启动后进程名变为 `next-server`，原 `pkill -f "next dev"` 无法命中，旧进程残留占用 26619 端口与文件 watcher 致启动假死。改为一并清理 `next-server` / `next/dist/bin/next` / `npm run dev`（`rebuild.sh`）。

### 构建与工程 (Build/CI)

- devcontainer 必须重建后才会应用 Node 20 与 `26619/26618` Docker 端口发布；当前旧容器验证结果为 `bash -n rebuild.sh` 通过，`bash rebuild.sh` 在 Node `18.20.8` 下按预期输出版本不兼容并退出 `1`（`rebuild.sh`）。
- `docker buildx build --check -f D:\dev-workspace\.devcontainer\Dockerfile D:\dev-workspace\.devcontainer` → passed，确认 Dockerfile 解析层已恢复。
- 处理 devcontainer 启动时 `ports are not available: 0.0.0.0:26619`：确认宿主机旧 `node` PID `30940` 占用 26619，停止后删除失败遗留的 Created 容器 `316ddf1cea6c`；`docker run --rm -p 6186:6185 -p 26619:26619 -p 26618:26618 --entrypoint /bin/true ...` → passed。
- devcontainer slim 镜像补装 `procps`，确保后续镜像中 `pkill` 可用；`rebuild.sh` 同时提供 `/proc` Python fallback 以兼容当前未重建的容器（`D:\dev-workspace\.devcontainer\Dockerfile`, `rebuild.sh`）。
- `bash rebuild.sh` → passed，Node `20.20.2`，Next build 11 static routes，`python3 tools/sync_frontend.py --check` → passed；宿主机 `curl.exe -I http://127.0.0.1:26619/` 与 `curl.exe -I http://127.0.0.1:26618/` 均 `200 OK`。
- `rebuild.sh` 保留生产 build 阶段的 `NEXT_TEST_WASM=1` 以规避 Windows bind mount lock 问题；dev 阶段改回原生 Next.js 启动以保证 `.next/dev` manifest 完整生成；前端就绪等待超时由 60s 放宽到 120s 以容忍首次冷编译（`rebuild.sh`）。
- 端到端验证：`bash rebuild.sh` → exit 0，后端 26618 与前端 dev 26619 均 `200`，`/api/*` 经 `next.config.ts` rewrites 正常代理到后端（aiohttp 401 鉴权门）。

## [v0.24.1] - 2026-06-11

### 修复 (Fixed)

- **SettingModal 终端面板嵌入**：补齐 `TerminalPanel variant="embedded"` 调用与内容区 `minHeight: 0` / 条件 padding，设置弹窗"终端日志"Tab 现直接渲染运行目录面板（`web/frontend/components/modals/SettingModal.tsx`）。
- **BuildJob 响应缺失 `type` 字段**：`BuildJob.to_dict()` 补加 `"type": "lightrag_build"`，前端 FilePanel BuildCard 可正确区分进度条来源（`core/lightrag_core.py`）。
- **`metadata.yaml` 版本号落后**：修正 `version` 字段从 `v0.23.6` 到 `v0.23.9`（`metadata.yaml`）。
- **前端构建失败**：删除遗留的 `app/api/[...proxy]/route.ts` 开发代理路由（该文件与 `output: "export"` 不兼容），改为在 `next.config.ts` 使用 `rewrites()` 仅在开发模式下代理 `/api/*` 请求（`web/frontend/next.config.ts`）。

### 架构健康 (Refactor)

- **删除 9 个零引用前端组件**：`components/ds/{Card,Input,QuotaBar,StatusChip}.tsx` 及 `components/fx/{Atmosphere,GrainOverlay,RetrievalProgress,DotField,SunBloom}.tsx`；同步更新 `components/ds/index.ts` 移除对应 re-export 行，减少构建产物体积。
- **TODO.md 状态修正**：补标 v0.23.0 P1/P3/P4 为 `[x]`（后端路由已实现）；v0.23.4 P1/P2/P3 全部标为 `[x]`（终端双模式已完整落地）；v0.23.0 P6 标为 `[x]`。

### 构建与工程 (Build/CI)

- `node node_modules/typescript/bin/tsc --noEmit` → passed, 0 errors
- `node node_modules/next/dist/bin/next build --webpack` → passed, 13 static routes generated
- `python tools/sync_frontend.py` → synced 167 files to `pages/`
- `python tools/sync_frontend.py --check` → passed
- `python -m pytest -q` → 270 passed, 316 warnings

---

## [v0.24.0] - 2026-06-11

### 新增功能 (Added)

- **Zotero-shaped 文档/集合笔记持久化**：新增 `ScopedNote` domain 模型、SQLite 迁移和仓储契约，补齐 `GET|POST|PATCH /api/documents/{doc_id}/notes`，并新增 `GET|POST|PATCH /api/collections/{name}/notes`；笔记保留 `note_html`、`parentItem`、tags、collections 与 `raw_zotero_json`，当前只写本地 SQLite，后续可接 Zotero 写回（`core/domain/models.py`, `core/repository/source_store/{base,memory,sqlite}.py`, `migrations/013_scoped_notes.sql`, `core/api.py`, `web/server.py`）。
- **聊天回答锁定持久化**：为 `chat_history` 增加 `locked/locked_at/updated_at`，实现 `PATCH /api/chat/history/{convId}/messages/{msgIdx}/lock`；清空聊天记录支持 `preserve_locked=true` 保留已固定回答（`migrations/014_chat_history_lock.sql`, `core/repository/source_store/{base,memory,sqlite}.py`, `core/api.py`, `web/server.py`）。
- **控制台右侧 scope state 持久化**：新增 `ConsoleScopeState` 与 `/api/console/scope-state`，前端 `ConsoleContext` 会恢复 global/collection/document 层级的右侧文档与笔记面板选择（`migrations/015_console_scope_state.sql`, `web/frontend/lib/ConsoleContext.tsx`, `web/frontend/lib/api.ts`）。
- **前端接线落地**：`NotePanel` 改用类型化 notes/annotations API；`ChatPanel` 将 lock、save note、clear preserved history 接到后端；保存聊天笔记优先写当前文档，其次写当前 collection（`web/frontend/components/panels/{NotePanel,ChatPanel}.tsx`, `web/frontend/lib/api.ts`）。

### 修复 (Fixed)

- **Windows SQLite 快照临时文件占用**：修复 SQLite backup helper 中连接未显式关闭的问题，避免 R2 数据库快照备份在 Windows 上因临时文件仍被占用失败（`core/pipelines/sync_pipeline.py`）。

### 测试 (Tests)

- `python -m pytest tests/backend/test_source_store.py tests/backend/test_sqlite_source_store.py tests/backend/test_api.py tests/backend/test_web_server.py tests/backend/test_sync_pipeline.py -q` -> passed, 110 passed / 1 skipped（本机缺少可选 `boto3`/`botocore`）。
- `node node_modules/typescript/bin/tsc --noEmit` -> passed。
- `node node_modules/next/dist/bin/next build --webpack` -> passed，13 static routes generated。
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`；`python tools/sync_frontend.py --check` -> passed。

---

## [v0.23.9] - 2026-06-11

### 修复 (Fixed)

- **三段控制台中英文映射收敛**：新增 File/Documents/Chat/Note/TopBar/Modal 相关 i18n 键，中文界面统一使用“文件/集合/分块/文档/问答”等普通术语，保留 LightRAG、Milvus、Zotero、R2 等技术专名；修复左侧文件栏中文模式仍显示 Collection 的问题（`web/frontend/lib/i18n.ts`, `web/frontend/components/panels/{FilePanel,DocumentsPanel,ChatPanel,NotePanel}.tsx`, `web/frontend/components/layout/TopBar.tsx`, `web/frontend/components/modals/{SettingModal,WorkflowModal,AstrBotModal}.tsx`, `web/frontend/components/ds/Modal.tsx`）。
- **控制台面板布局对齐**：调整通用 `Panel` header 的面包屑分隔符与溢出宽度策略，避免无标题阅读态出现前导 `/`，并修正 Documents 面板标题重复；左侧分区标题按当前语言调整字距和大小，中文界面不再强制 uppercase 间距（`web/frontend/components/ds/Panel.tsx`, `web/frontend/components/panels/{DocumentsPanel,FilePanel}.tsx`）。

### 构建与工程 (Build/CI)

- `node node_modules/typescript/bin/tsc --noEmit` -> passed。
- `node node_modules/next/dist/bin/next build --webpack` -> passed，13 static routes generated。
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`；`python tools/sync_frontend.py --check` -> passed。
- Browser smoke on `http://localhost:26619/?mock=true` -> passed，中文/英文切换与三栏 header 对齐检查通过，无浏览器 console error。

---

## [v0.23.8] - 2026-06-11

### 新增功能 (Added)

- **PDF.js 受控阅读面板**：用 `pdfjs-dist` 替换 DocumentsPanel 中的 iframe PDF 预览，支持页码跳转、缩放、适合宽度、loading/error 状态与 annotation 侧栏点击跳页（`web/frontend/components/panels/PdfViewer.tsx`, `web/frontend/components/panels/DocumentsPanel.tsx`, `web/frontend/package.json`）。
- **文档阅读后端接口补齐**：新增 `GET /api/documents/{doc_id}/content?format=md`、`GET /api/documents/{doc_id}/chunks`、`GET /api/documents/{doc_id}/annotations`，并为 `/raw` 增加 `?disposition=inline`，默认下载行为仍保持 `attachment`（`web/server.py`, `core/api.py`）。
- **Zotero Local API 只读桥接**：新增只读 `ZoteroLocalApiClient` 与 annotation 归一化 helper，仅使用 `GET` 读取 Local API，不向 Zotero 写回数据（`core/adapters/zotero/local_api.py`）。

### 测试 (Tests)

- `python -m pytest tests/backend/test_web_server.py tests/backend/test_zotero_local_api.py -q` -> passed, 46 passed。
- `node node_modules/typescript/bin/tsc --noEmit` -> passed。
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated。
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`；`python tools/sync_frontend.py --check` -> passed。
- Browser smoke 未执行：当前工具发现未暴露可用的 in-app Browser 控制工具。

---

## [v0.23.7] - 2026-06-11

### 架构健康 (Refactor)

- **前端冗余 `ui/` 组件清理**：删除 5 个已被 `ds/` 设计系统取代、零引用的旧组件：`Btn.tsx`（→`ds/Button`）、`HelpTip.tsx`（→`ds/Tooltip`）、`Select.tsx`（→`ds/Select`）、`Tag.tsx`（→`ds/Tag`）、`Toggle.tsx`（→`ds/Toggle`）（`web/frontend/components/ui/`）。
- **删除空占位目录 `core/repository/graph_store/`**：三个实现文件（`base.py`、`memory.py`、`sqlite.py`）在 commit `ac05dfe` 中已移除，仅余空 `__init__.py`，本次一并清除（`core/repository/graph_store/`）。

---

## [v0.23.6] - 2026-06-11

### 修复 (Fixed)

- **Flow 面板按钮行为调整**：`sync` 节点与 `zotero` 节点的"进入同步设置"链接由 `/sync` 改为 `/settings`，与设置页实际位置对齐（`web/frontend/components/flow/model.ts`）。
- **Flow 面板"进入问答界面"改为关闭弹窗**：`ask` 节点的链接按钮在 WorkflowModal 上下文中改为调用 `onClose()` 关闭弹窗而非导航至 `/ask`；通过 `WorkflowModal → FlowPageContent → FlowDiagram → FlowNode` 链路传递可选 `onClose` prop；standalone `/flow` 页未传入时仍保留原 `<Link>` 行为（`web/frontend/components/modals/WorkflowModal.tsx`, `components/panels/FlowPageContent.tsx`, `components/flow/FlowDiagram.tsx`, `components/flow/FlowNode.tsx`）。

### 构建与工程 (Build/CI)

- `node node_modules/typescript/bin/tsc --noEmit` -> passed, 0 errors
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 158 files to `pages/`

---

## [v0.23.5] - 2026-06-11

### 新增功能 (Added)

- **一键构建重启开发工具**：在项目根目录新增 `rebuild.sh` 脚本，支持一键停止旧服务、自动清理 `.next` 缓存、构建/编译前端页面、同步静态资源产物并于后台重启前后端开发服务。

### 修复 (Fixed)

- **前端开发模式白屏刷新崩溃**：修改 `web/frontend/package.json` 中的 `dev` 和 `build` 脚本，在运行前运行 `rm -rf .next` 清除缓存，避免由于生产静态导出后的 `.next` 缓存与开发模式冲突导致的 `missing required error components` 白屏循环刷新崩溃问题。
- **前端打包时的 rewrites 警告**：修改 `web/frontend/next.config.ts`，将 `rewrites` 配置改为仅在开发模式（`isDev`）下注入，避免 Next.js 在打包为静态导出（`output: 'export'`）时抛出 rewrites 不兼容的编译警告。

## [v0.23.3] - 2026-06-11

### 修复 (Fixed)

- **WorkflowModal 数据流图退化为原生白底文本**：在 `web/frontend/app/globals.css` 中恢复引入 `web/frontend/styles/tokens.css`，并置于 `ds-tokens.css` 之前，确保 `.flow-*` 样式与 `--flow-*` 变量进入全局样式，同时保留新 DS token 的后加载覆盖顺序。

### 构建与工程 (Build/CI)

- `node .\node_modules\typescript\bin\tsc --noEmit` -> passed。
- `node .\node_modules\next\dist\bin\next build --webpack` -> passed，13 static routes generated。
- `python tools/sync_frontend.py` -> synced 160 files to `pages/`。
- `python tools/sync_frontend.py --check` -> passed。
- `http://localhost:26619` -> HTTP 200，当前由 Next dev preview 提供预览。

---

## [v0.23.2] - 2026-06-10

### 修复 (Fixed)

- **WorkflowModal 数据流图只显示头部/图例**：补齐 `WorkflowModal` content、`FlowPageContent` 根节点与 `.flow-viewport` 的 flex 高度链路，确保 FlowDiagram 在弹窗内占满剩余空间并保留拖拽/缩放交互（`web/frontend/components/modals/WorkflowModal.tsx`, `web/frontend/components/panels/FlowPageContent.tsx`, `web/frontend/styles/tokens.css`）。
- **Terminal 浮层过小且侧边栏误走 `/terminal` redirect**：`TerminalPanel` 新增触发文案/图标 props，修正 portal 内点击被外部点击处理器关闭的问题，浮层放大为面板尺寸并使用两列系统信息布局；`Rail` 直接挂载该浮层入口，设置页入口继续复用默认运行目录按钮（`web/frontend/components/ui/TerminalPanel.tsx`, `web/frontend/components/rail/Rail.tsx`）。

### 构建与工程 (Build/CI)

- `node .\node_modules\typescript\bin\tsc --noEmit` -> passed。
- `node .\node_modules\next\dist\bin\next build --webpack` -> passed，13 static routes generated。
- `python tools/sync_frontend.py` -> synced 160 files to `pages/`。

---

## [v0.23.1] - 2026-06-10

### 修复 (Fixed)

- **WorkflowModal 数据流界面不可用**：`FlowPageContent` 根元素 CSS class `.flow-topo-page` 定义了 `height: 100vh`，嵌入 Modal flex 容器后强制撑开至视口高度导致图谱无法交互。通过行内 style 覆盖为 `height: 100%` 修复（`web/frontend/components/panels/FlowPageContent.tsx`）。

### 新增功能 (Added)

- **Local Collection 删除按钮与确认弹窗**：FilePanel Local Collection 选中行右侧新增红色垃圾桶 `IconButton`（仅选中时显示）。点击弹出全屏遮罩确认对话框：含危险操作警告、需用户完整输入 collection 名称方可激活"确认删除"按钮（输入错误时边框高亮 `--danger`）、支持 Escape 取消及 Enter 快捷确认。删除成功后调用 `deleteCollection()` API、刷新列表并清空 `selectedCollection`（`web/frontend/components/panels/FilePanel.tsx`, `web/frontend/lib/api.ts`）。

### 构建与工程 (Build/CI)

- `npx next build` → Compiled successfully, 13 static pages generated。
- `python tools/sync_frontend.py` → 同步 144 个文件到 `pages/`。

---

## [v0.23.0] - 2026-06-10

### 新增功能 (Added)

- **三段式控制台 UI（Heptabase 风格）**：将原 Rail 侧栏 + 多页路由结构全面替换为 File | Documents | Chat 三段式集成控制台。左侧 FilePanel（264px）展示 Zotero Sync / Local Collection / LightRAG Collection 三分区集合树；中间 DocumentsPanel（flex）支持文献列表视图与阅读视图双模式切换；右侧 ChatPanel（360px）整合 Research Agent 对话、引用跳转、锁定回答功能（`web/frontend/app/(console)/layout.tsx`, `web/frontend/components/panels/FilePanel.tsx`, `web/frontend/components/panels/DocumentsPanel.tsx`, `web/frontend/components/panels/ChatPanel.tsx`）。
- **NotePanel**：点击文献 Note 图标时替换 FilePanel，展示文献元数据、Zotero 注释占位（501 降级）、本地笔记 CRUD（localStorage 降级）、摘要（`web/frontend/components/panels/NotePanel.tsx`）。
- **三个全屏弹窗**：TopBar 三个按钮各打开一个全屏弹窗——SettingModal（外观/同步备份/后端配置/终端日志）、AstrBotModal（Embedding/向量库/LightRAG/Research Agent 四卡片单页滚动）、WorkflowModal（包裹现有 Flow 点阵图 FlowDiagram，面积扩大至 `calc(100vw - 32px) × calc(100vh - 32px)`）（`web/frontend/components/modals/SettingModal.tsx`, `web/frontend/components/modals/AstrBotModal.tsx`, `web/frontend/components/modals/WorkflowModal.tsx`, `web/frontend/components/panels/FlowPageContent.tsx`）。
- **设计系统 Token（ds-tokens.css）**：合并白灰 Heptabase 风格 Token，替换暖橙色调；字体切换为 Inter + JetBrains Mono；新增 `branchPulse`、`citeFlash`、`overlayIn`、`modalIn`、`dotDrift` 关键帧动画；新增 LightRAG 模式紫色调（`[data-mode="lightrag"]`）（`web/frontend/styles/ds-tokens.css`, `web/frontend/app/globals.css`, `web/frontend/app/layout.tsx`）。
- **设计系统组件库（`components/ds/`）**：新增 15 个组件——`Button`、`IconButton`、`Badge`、`Card`、`StatusChip`、`QuotaBar`、`Input`、`Select`、`Tag`、`Toggle`、`Panel`、`Modal`、`Eyebrow`、`Tooltip`、`Icon`（30+ 命名 SVG 路径）（`web/frontend/components/ds/*.tsx`）。
- **ConsoleContext**：新增 React Context 共享 `selectedCollection`、`selectedDocId`、`highlightedChunk`、`noteDocId`、三个弹窗开关状态；引用跳转（Chat → Documents）通过 `setHighlightedChunk` + `setSelectedDocId` 实现（`web/frontend/lib/ConsoleContext.tsx`）。
- **lib/api.ts 后端能力 stub**：新增 7 个类型化 stub 函数（`getDocumentContent`、`getDocumentNotes`、`createDocumentNote`、`updateDocumentNote`、`getDocumentAnnotations`、`lockChatAnswer`、`listDocumentChunks`），对应待实现的后端端口（`web/frontend/lib/api.ts`）。

### 架构健康 (Refactor)

- **旧路由清理**：将 `/ask`、`/documents`、`/flow`、`/graph`、`/quota`、`/search`、`/settings`、`/sync`、`/terminal` 全部替换为 `redirect("/")` 全重定向（`web/frontend/app/(console)/*/page.tsx`）。
- **FlowPageContent 提取**：将 `flow/page.tsx` 的组件逻辑提取为 `FlowPageContent.tsx`，供 WorkflowModal 引用，同时保留 `components/flow/` 文件不变（`web/frontend/components/panels/FlowPageContent.tsx`）。
- **BuildWidget 更新**：将原 `/graph` 路由跳转改为 `setWorkflowOpen(true)` 调用（`web/frontend/components/build/BuildWidget.tsx`）。

### 构建与工程 (Build/CI)

- `npx tsc --noEmit` → 0 errors（全量类型检查通过）。
- `npx next build` → 编译成功，13 个静态路由生成。
- `python tools/sync_frontend.py` → 同步 143 个文件到 `pages/`。
- `python -m pytest -q` → 256 passed, 281 warnings（后端测试全部通过，无新增失败）。

---

## [v0.22.1] - 2026-06-09

### 新增功能 (Added)

- **Flow 节点目录选择器（DirPickerDialog）**：Zotero 数据目录字段新增文件夹图标按钮，点击弹出风格统一的暗色目录浏览弹窗，支持上下级导航、选中后回填输入框；后端新增 `GET /api/fs/browse` 接口返回指定路径的子目录列表（`web/server.py`, `web/frontend/components/flow/DirPickerDialog.tsx`, `web/frontend/components/flow/QuickConfigPanel.tsx`, `web/frontend/lib/api.ts`, `web/frontend/lib/i18n.ts`, `web/frontend/styles/tokens.css`）。
- **Flow 节点自定义下拉组件（FlowSelect）**：QuickConfigPanel 内所有 `<select>` 均替换为与 Flow 节点风格一致的自定义浮层下拉（包括同步模式、存储模式、图谱检索模式、LightRAG LLM 来源）；同步页 `⚙ Zotero 配置` 折叠区的下拉也替换为全局 `Select` 组件（`web/frontend/components/flow/QuickConfigPanel.tsx`, `web/frontend/app/(console)/sync/page.tsx`, `web/frontend/styles/tokens.css`）。
- **全局 Toggle 开关组件**：新增 `components/ui/Toggle.tsx`，替换同步页与设置页的原生 `<input type="checkbox">`，视觉与整体设计语言统一；`Select` 组件补充 `disabled` prop（`web/frontend/components/ui/Toggle.tsx`, `web/frontend/components/ui/Select.tsx`, `web/frontend/app/(console)/sync/page.tsx`, `web/frontend/app/(console)/settings/page.tsx`）。

### 修复 (Fixed)

- **Zotero 节点启用但未探测到数据目录时状态错误**：`CapabilitiesApiMixin` 新增 `_overlay_zotero_availability()`，在 Zotero 为 `ready` 但 `is_available()` 返回 `false` 时将状态降为 `degraded`（黄色），避免误显示绿色就绪（`core/api_capabilities.py`, `core/pipelines/zotero_sync_pipeline.py`）。
- **去除 QuickConfigPanel 中的「文档字符上限」字段**：该字段为只读内部参数，不应暴露给用户修改（`web/frontend/components/flow/QuickConfigPanel.tsx`）。
- **文档列表新增「索引/状态」列**：Milvus 索引覆盖、LRAG 索引状态（已建立/需重构/未建立）、生命周期脱管状态（detached）直接在列表中展示，无需打开文档检查器（`web/frontend/app/(console)/documents/page.tsx`）。

### 架构健康 (Refactor)

- **Flow 网格行间距收紧**：`flow-diagram-grid` 的 `row-gap` 由 42px 降至 18px，使 LightRAG 图谱与检索编排节点在视觉上更紧凑（`web/frontend/styles/tokens.css`）。
- **设置外观栏增加滚动**：外观 sticky 区添加 `maxHeight: 50vh; overflowY: auto`，避免小屏幕下内容溢出（`web/frontend/app/(console)/settings/page.tsx`）。

- **Milvus 运行态覆盖状态与手动重建入口**：`/api/capabilities` 的 vector_store/retrieval/ask 环节现在叠加 Milvus 运行态信息（`compatible`、`rebuild_required`、`pending_reindex_count`、`document_count`、`chunk_count`、`reason`）；Flow 在待重建时显示 degraded 和“重建索引”按钮，Documents 工具栏增加“重建 Milvus 索引”入口，均复用 `/api/documents/rebuild-index` 并展示失败摘要（`core/api_capabilities.py`, `web/server.py`, `web/frontend/components/flow/{FlowDiagram,FlowNode,model}.tsx`, `web/frontend/app/(console)/{flow,documents}/page.tsx`, `web/frontend/lib/{api,i18n}.ts`）。
- **Ask 页知识库选中高亮边与发送键灰态**：选中集合时输入卡片显示橙色高亮边（`--accent-border`）；加载期间边框退回普通色、仅保留旋转辉光；图谱检索模式下未选有效集合时发送键变灰，点击仍触发已有 toast 提示（`web/frontend/app/globals.css`, `web/frontend/app/(console)/ask/page.tsx`）。
- **Milvus 自动索引开关说明文案优化**：label 改为「上传后立即建立 Milvus 向量索引」，说明文字补充延迟索引 / 批量重建工作流说明（`web/frontend/app/(console)/settings/page.tsx`）。

### 修复 (Fixed)

- **Milvus ready 语义不再只等于依赖可用**：当 compatibility 缺失/不匹配或 SQLite 仍有 `needs_reindex=1` 文档时，capabilities 会把 Milvus 标为需重建，Ask 的 `fallback_reason` 会携带 Milvus 未覆盖/需重建原因，避免 UI 只显示 AstrBot 回退而隐藏真实问题（`core/api.py`, `core/api_capabilities.py`）。
- **Milvus 索引失败自动重试**：上传自动索引、Zotero 索引回调、collection move、待重建索引和全量重建统一走 retry helper，覆盖 embedding 生成与 Milvus upsert；全部失败后才保留/标记 `needs_reindex=1` 并返回失败统计与错误摘要（`core/api.py`, `tests/backend/test_api.py`）。
- **单元测试更新**：修复 `tests/backend/test_api.py` 中因 `embedding.max_token_size` 被移出 `CONFIG_KEY_POLICY` 导致的配置项更新校验测试失败（`tests/backend/test_api.py`）。

### 架构健康 (Refactor)

- **简化用户配置项，隐藏 9 个内部/多余配置字段**：从 `_conf_schema.json` 移除 9 个不必要或仅供内部/高级使用的字段（如 Notion 的限速、LightRAG 重试退避等字段），并将它们在 `core/config.py` 中硬编码为常数或保留在 dataclass 中但从 Schema 移除，减少配置界面的认知负担（`_conf_schema.json`, `core/config.py`）。
- **重写配置项描述和提示**：更新了 `_conf_schema.json` 所有剩余配置字段的 `description` 和 `hint` 文案，重构为更简练易懂的中文说明（`_conf_schema.json`）。

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
- **本地集成测试脚本**：新增 `tests/mocks/run_dev_realtime.py`，使用真实 Milvus Lite + LightRAG + Deepseek API 在端口 6521 启动测试 WebUI，直接从用户本地私有 mock_data 目录读取 PDF 播种数据，绕开 IngestManager；新增 `tests/mocks/reset_dev_realtime.py` 一键归档/清理测试数据；新增 `tests/mock_data/Config/config.example.py` 配置模板；相关文件全部入 `.gitignore`（`tests/mocks/`, `tests/mock_data/Config/config.example.py`, `.gitignore`）。

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
- `web/frontend/next.config.ts`：`output: 'export'`（生产）/ dev rewrite → `:26618`（开发），`images.unoptimized: true`。
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
