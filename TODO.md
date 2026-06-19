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

## v0.26.3 统一多归属集合树 (in progress)

### User constraints / 约束

- 把本地持久化重构成与 Zotero 一致的「树形 + 多归属」结构（统一 local 与 zotero）。
- 仅本地集合可编辑（建子集合/重命名/移动/删除）；Zotero 集合只读、仅树形展示，不回写 Zotero。
- ask 与 lightrag 的范围 = 选中集合 + 所有子目录（含后代）。
- lightrag 选中父集合 build 时，父+所有后代文档合并为单一 workspace（以选中集合命名）。
- DocumentsPanel 选中父集合时只显示本级文档（不递归），与 ask/lightrag 的含后代范围故意不同。
- 版本只 bump patch（v0.26.2 → v0.26.3）。

### Technical implementation path

- [x] **Phase 1 - schema：migration 018 + domain**：`collections` 加 `coll_key`(稳定逻辑主键)/`parent_key`/`library_id`；新建 `document_collections(doc_id, coll_key)` 多对多表替代单值归属，保留 `documents.collection` 作冗余 primary；同 migration 内回填 + 数据迁移。domain `Collection`/`SourceDocument` 加对应字段。为支持 Zotero 同名子集合（name 非唯一），重建 collections（coll_key 主键）、documents/scoped_notes（去掉对 collections(name) 的外键）。
- [x] **Phase 2 - repository base 接口先行 + sqlite/memory 双实现**：base.py 集合契约改按 coll_key，新增 `get_collection`/`get_collection_by_name`/`get_local_collection_descendants`/`delete_collection_by_key`/`set_document_collections`/`list_document_collection_keys`/`list_documents_by_collection_key(descendants)`；add/update_document 自动同步多归属、get/list 回填 collection_keys。
- [x] **Phase 3 - `.collection` 单值→多对多 全触点改造**：归属真相由 store 层 `_sync_doc_memberships` 自动维护（add/update_document）；primary 标签（R2/Notion/milvus）保持不变；classify_document 重分类时清空旧多归属跟随新 primary。
- [x] **Phase 4 - Zotero 同步去压扁 + 树派生进统一 collections**：`_sync_documents` 写 item 全部所属集合（多归属）+ unfiled home 兜底；`_sync_zotero_tree_into_collections` 把 zotero 树整体 upsert 进统一 collections（coll_key=lib:zkey、parent_key=lib:父zkey、只读）并清理陈旧/迁移临时行。
- [x] **Phase 5 - ask 含后代 + lightrag 合并单 workspace**：`resolve_scope` 的 SCOPE_COLLECTION 改走统一树（`list_documents_by_collection_key(descendants=True)`）→ allowed_document_ids；`_resolve_ask_collections` 在 collection scope 下扩展为「父+后代」name 列表覆盖 milvus tag；`_lightrag_docs_for_build`/`get_lightrag_readiness` 按 name→coll_key→后代合并（workspace 仍按 name，同名集合为已知限制）。
- [x] **Phase 6 - 本地集合编辑后端 API + REST + 前端真树形**：api 新增 create_subcollection/rename_collection/move_collection(防环)/delete_collection_by_key(子集合提升+文档迁 _uncategorized)，zotero 一律 ReadOnlyError；REST 加 `PATCH/DELETE /api/collections/by-key/{coll_key}`、create 支持 parent_key、`GET /api/documents?collection_key`（本级）；FilePanel 递归树渲染（真展开）+ 本地新建子集合/重命名/删除 UI；ask 默认含后代（由选中集合 coll_key 派生 scope）。
- [ ] **Phase 7 - 端到端集成测试 + 全量回归**：pytest 414 通过 / ruff / mypy 通过；前端 npm build + sync_frontend 待确认。
- [x] **Phase 8 - bump v0.26.3 + CHANGELOG/TODO 收尾**：`metadata.yaml` 已 bump 到 `v0.26.3`，`CHANGELOG.md` 已追加 v0.26.3 条目；等待 Phase 7 前端构建/同步确认后再整体标 completed。

### Verification

- `python -m pytest tests/backend/` → 414 passed。
- `ruff check .` → All checks passed；`mypy` → Success。
- `npm run build` + `python tools/sync_frontend.py` → 待确认。
- `CHANGELOG.md` + `metadata.yaml` → v0.26.3 收尾完成。

## v0.26.2 调试端口迁移 (completed)

### User constraints / 约束

- 将项目内调试/测试 WebUI 端口统一为后端 `26618`、前端 `26619`。
- 使用 Docker 环境验证；`pages/` 只能通过 `tools/sync_frontend.py` 生成，不手工编辑。
- 业务毫秒阈值或非端口数值不改。

### Technical implementation path

- [x] **Phase 1 - 仓库内端口默认值更新**：更新 `rebuild.sh`、`tests/run_webui.py`、`core/config.py`、`_conf_schema.json`、`web/frontend/next.config.ts`、mock config 与设计说明中的调试端口默认值。技术理由：确保脚本、后端配置、前端 dev proxy 和文档同源。
- [x] **Phase 2 - devcontainer 端口发布同步**：将 Docker `appPort`/`EXPOSE` 同步为 `26619/26618`。技术理由：宿主机要访问新端口，容器发布端口必须同步。
- [x] **Phase 3 - 构建同步与运行验证**：运行前端类型检查、Next build、`tools/sync_frontend.py`、`rebuild.sh`，并 smoke 测试 `26618/26619` 登录链路。技术理由：确认新端口不仅配置正确，而且当前 Docker 运行态可用。

### Verification

- [x] `bash -n rebuild.sh` → passed
- [x] `python -m pytest tests/backend/test_config.py -q` → 26 passed
- [x] `node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed
- [x] `npm run build`（`web/frontend`）→ passed（Next build 生成 13 个静态路由）
- [x] `python tools/sync_frontend.py && python tools/sync_frontend.py --check` → passed（同步 362 个文件，`pages/` 一致）
- [x] `bash rebuild.sh` → passed（Docker 内后端 `26618`、前端 `26619` 就绪）
- [x] `26618/26619 auth smoke` → passed（`/api/auth` 200、前端首页 200、`admin/111111` 登录后 `logged_in=true`）
- [x] 全仓旧端口扫描 → old port clean；旧前端端口数字仅剩非端口毫秒阈值。

## v0.26.1 统一进度面板 + Zotero Pull 修复 + Terminal 日志 (completed)

### User constraints / 约束

- 仅 patch 版本（v0.26.1）。
- 进度面板：文件面板侧左下角浮动停靠，可收起/展开，空闲时完全隐藏，层级 Modal 之上、Toast 之下。
- 综合面板：整合 Zotero 同步 / Milvus 构建 / LightRAG 图谱 / 文档上传摄入四源，加载时全部显示。
- Terminal 日志只改后端输出内容，**完全不改前端 UI**。
- 运行中的 `astrbot-data-docker/` 实例全程只读。

### Technical implementation path

- [x] Phase 1 — Zotero Pull 改异步任务 + 进度/状态/错误可见：新增 `core/zotero_sync_job.py`；`zotero_sync_pipeline.pull(progress=)` 逐阶段/逐文档更新 + 索引失败进 `result.errors`；`api.sync_zotero_pull` 后台化 + `get_active_zotero_sync_job`；`GET /api/sync/zotero/active`；前端 `getActiveZoteroSyncJob` + `ZoteroQuickConfig` 轮询。
- [x] Phase 2 — 统一 ProgressDock：`components/progress/ProgressDock.tsx` + `useProgressJobs` 四源轮询；`Z.progressDock=1350`；挂载于 console layout；移除 FilePanel 内 Milvus 卡片去重。
- [x] Phase 3 — 上传/摄入进度：`core/ingest_job.py:IngestJob`，`register_document` 编排层跟踪，`GET /api/documents/ingest/active` + 前端 `getActiveIngestJob`。
- [x] Phase 4 — Terminal 日志聚焦补强：Zotero 全链路 + `search_kb`/`ask` 入口出口 + 关键 `logger.error(exc_info=True)`。
- [x] Phase 5 — 版本/测试/构建：bump v0.26.1；新增 `test_zotero_sync_job.py` + pipeline 回归；前端 `npm run build` → `tools/sync_frontend.py`。

### Verification

- `python -m pytest` → 398 + 6 新增全过；`ruff check` 触改文件 → clean；`mypy` → Success。
- `cd web/frontend && npm run build` → Compiled successfully + TS 通过；`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。

## v0.26.0 质量门禁与构建同步闭环 (completed)

### User constraints / 约束

- 执行已批准的质量修复：`ruff`、前端 lint、React hooks 风险、generated vendor lint、版本/CHANGELOG 对齐、aiohttp warnings、`pages/` 同步。
- 暂不执行大型文件拆分：`core/api.py`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`、`web/frontend/styles/tokens.css` 仅保留为后续重构建议。
- 使用 Docker 环境验证；`pages/` 只能通过 `tools/sync_frontend.py` 生成，不手工编辑。

### Technical implementation path

- [x] **Phase 1 - Python 质量门禁**：修复 `ruff check .` 报出的长行、import 排序、未使用 import/变量和现代类型写法问题；同时处理 aiohttp `AppKey` 与测试 deprecation warning。
- [x] **Phase 2 - 前端 lint 与 hooks 稳定性**：修复 `FlowNode.tsx` 条件 hooks 调用；忽略 generated `public/pdfjs/**`；清理无用 import/变量；仅对明显派生状态改造 effect 内同步 `setState`。
- [x] **Phase 3 - 文档版本与产物同步**：统一 `metadata.yaml`、`TODO.md`、`CHANGELOG.md` 版本状态；build 后运行 `tools/sync_frontend.py`，确保 `pages/` 与 `web/frontend/out/` 一致。
- [x] **Phase 4 - rebuild.sh 换行修复**：将 `rebuild.sh` 统一为 LF，并在 `.gitattributes` 固定 `*.sh` 为 LF，修复 Docker/Linux Bash 下 CRLF 导致的 `$'\r': command not found` 与函数解析失败。
- [x] **Phase 5 - rebuild.sh 端口占用与 dev origin 修复**：启动前清理 `26618/26619` 监听者，等待新启动 PID 存活而不是误判旧服务；为 Next dev 允许 `127.0.0.1` origin，修复 HMR 被拦导致的 26619 访问异常。

### Verification

- [x] `ruff check .` → passed
- [x] `python -m mypy` → passed (`Success: no issues found in 3 source files`)
- [x] `python -m pytest -q` → 398 passed
- [x] `npm run lint` → passed
- [x] `node node_modules/typescript/bin/tsc --noEmit --incremental false` → passed
- [x] `npm run build` → passed（13 static routes）
- [x] `python tools/sync_frontend.py` → synced 362 files to `pages/`
- [x] `python tools/sync_frontend.py --check` → passed
- [x] `bash -n rebuild.sh` → passed
- [x] `bash rebuild.sh` → passed；Next build 与 `tools/sync_frontend.py` 完成，后端 `26618` 与前端 `26619` ready
- [x] `node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed（覆盖 `next.config.ts`）
- [x] `26618/26619 auth smoke` → `admin / 111111` 登录均返回 `{"ok": true}`，登录后 `/api/auth` 均为 `logged_in: true`

## v0.25.16 数据流节点界面美术与配置统一重构 (completed)

### User constraints / 约束

- 美术参考用户截图：node 左侧 mark 改辉光（数据流质感、非转圈），保留显色；边末端连接点对齐辉光上沿；icon 与状态徽章圆角统一；节点横向间距加大。
- 「可选来源」文字气泡改用非圆圈端点表达，换色（不用绿黄）→ 选定靛紫菱形。
- 配置统一为「模块切换 + 必要配置 + 高级折叠」三段式，高级区可调该节点全部设置；高级窗口可展开/收起且**不影响节点对齐**。
- 节点状态徽章合并为唯一保存入口：未保存→变色变「保存」；保存后「待重启」；顶部新增全局「重启插件」按钮（用户确认每节点「待重启」+ 顶部统一重启）。
- 版本只 patch；`pages/` 为产物经 build+sync 生成，不手改。

### Technical implementation path

- [x] **Phase 1 美术**：`tokens.css` 新增 `--flow-st-optional/-dirty/-restart`；`.flow-node-stripe` 改辉光带 + `stripeFlow` 高亮；`.flow-handle--optional` 靛紫菱形 + `.flow-conn-group.is-optional` 描边；icon/状态徽章统一 R9；`column-gap` 68px；`FlowDiagram.tsx` 为 dashed 边 from 端打 optional 标记并停渲文字气泡（`model.ts` 边定义不变）。
- [x] **Phase 2 配置三段式 + 全量可写键**：`QuickConfigPanel.tsx` 抽出 `computeUpdates`/`useQuickConfigDraft`/`QuickConfigFieldGrid`/`AdvancedSection`，`buildQuickConfig` 拆 required/advanced 并补 graph LightRAG LLM 三项、`source_store.default_collection`、Ask 节点 `deep_thinking` 全部调参（`number` 字段支持 `min`/`step`，rerank_weight 允许 0/小数）；`ZoteroQuickConfig.tsx` 复用共享 hook 与 `AdvancedSection`；高级浮层绝对定位（`.flow-quick-advanced-panel` + `.flow-node.is-advanced-open{overflow:visible}` + `:has` 抬升 cell z-index），不计入测量高度。后端无需改（`api_writable_keys()`/`to_public_dict()` 已含全部字段）。
- [x] **Phase 3.1 徽章三态 + 单一保存入口**：`QuickConfigPanel`/`ZoteroQuickConfig` 改 `forwardRef` 暴露 `save()`、经 `onDirtyChange` 上报草稿态、移除面板内独立 Save；`FlowNode.tsx` 头部徽章 dirty 时变「保存」按钮（点击经 ref 提交）、`restartPending` 时显示「待重启」，节点加 `is-dirty/is-restart-pending/is-advanced-open` 类；`FlowPageContent.tsx` 维护 `restartPendingIds` 并经 `FlowDiagram` 下发。
- [x] **Phase 3.2 全局重启**：`FlowPageContent` 顶部新增「重启插件」按钮（待重启计数）；`lib/api.ts` 新增 `restartPlugin()`；后端 `web/server.py` 新增 `POST /api/plugin/restart` → `core/api.py::restart_plugin()`（注入 `reload_callback`，后台延迟触发，避免拆掉当前响应连接）→ `core/plugin_initializer.py::reload()`（teardown→重读持久化配置重建 Config→initialize），进程内软重启不杀 AstrBot。
- [x] **i18n**：`lib/i18n.ts` 中英补 `flow_quick_advanced`、`flow_quick_default_collection`、`flow_quick_graph_working_dir(_help)`、`flow_quick_dt_*`、`flow_status_pending_restart`、`flow_restart_*`。
- [x] **Round 2 修正（用户看效果后反馈）**：① 高级折叠移到节点最底部——`FlowNode` body 末尾加 `.flow-node-advanced-slot`，`AdvancedSection` 经 `createPortal` 渲到该槽位（slot 空回退内联），浮层 `top:100%` 紧贴节点底、只圆下两角、去上边框，仍 absolute 不挤动其他节点（`.flow-node-advanced-slot:empty{display:none}`）。② 边美术按参考图改发光风格——`.flow-handle` 11px 实心点→14px 空心发光圆环；`.flow-conn-base` 灰 mix→鲜亮状态色 + 双层 `drop-shadow`（off 关光晕）；`.flow-conn-live` 蚂蚁线→`14 600`/3.2s 长间隙短亮段缓慢流过（`connFlow` 终值 -614）；保留可选来源靛紫菱形。
- [x] **Round 3 修正（用户看 R2 后反馈）**：① 高级弹窗改回「分离式」浮层——`.flow-quick-advanced-panel` 回退为 `top:calc(100%+8px)`、四角全圆 `border-radius:12px`、四边边框（仍 absolute Portal 在底部槽位、不挤动）。② 左侧单条辉光竖条 → 整圈发光薄边框——删 `.flow-node-stripe`（含 `<span>`/`::after`/`@keyframes stripeFlow`），`.flow-node` 改 `1px` 随 `--flow-st` 着色薄边 + `box-shadow` 整圈光晕（包住整个 node、比原 3px 更薄）；hover/选中/dirty/restart/off/dest 各态光晕整合；节点边框静态发光，流动感保留在边线。
- [x] **Round 4 修正（用户反馈）**：① 编辑配置时 5s 自动刷新冲掉输入——`FlowNode` 经 `onEditingChange` 上报 dirty 态，`FlowPageContent` 用 `editingRef` 跟踪，有节点 dirty 时暂停自动刷新（`FlowDiagram` 透传）。② 高级浮层展开压住相邻节点连接点——`.flow-handle` `z-index` 3→40，端口始终在浮层之上。

### Verification

- `python -m pytest -q` → 398 passed（含新增 `test_restart_plugin_*`）。
- `npx tsc --noEmit` → passed；`npm run build` → passed（13 路由全静态生成）；`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。
- 人工核对（开发态 `/flow`）：辉光 mark + 端点对齐、靛紫菱形可选来源、圆角统一、间距变宽；改配置→徽章变「保存」→「待重启」；展开/收起高级浮层不位移其他节点与边；graph LLM / default_collection / deep_thinking 均可调；顶部「重启插件」软重启后状态复检回就绪。
- Round 2 复验：`npx tsc --noEmit` → passed；`npm run build` → passed；`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。人工核对：高级折叠按钮在节点最底部、展开浮层紧贴节点底且其他节点/边不位移；边为发光圆环 + 发光曲线、ready 边有缓慢流动亮点无蚂蚁线、可选来源仍靛紫菱形。
- Round 3 复验：`npx tsc --noEmit` → passed；`npm run build` → passed；`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。人工核对：展开高级 → 分离式浮层卡片（带间隙四角圆）；节点整圈薄边框发光包住整个 node、随状态/未保存/待重启变色、无左侧单条竖条。
- Round 4 复验：`npx tsc --noEmit` → passed；`npm run build` → passed；`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。人工核对：编辑某节点（蓝色）时输入不再被 5s 刷新冲掉、保存后恢复刷新；展开高级浮层时相邻节点连接点圆环不被压住。

## v0.25.15 AstrBot 配置收窄与 WebUI 设置迁移 (completed)

### User constraints / 约束

- AstrBot 插件配置面板只保留 5 组，并按固定顺序：`web_console`、`r2_sync`、`notion_sync`、`embedding`、`ask`。
- 从 AstrBot schema 移除其他配置组；不影响 WebUI 内部继续展示或编辑更多高级配置。
- 被移除且未在其他 WebUI 窗口暴露的设置，先迁移到 WebUI 设置弹窗；本轮不重设计设置页结构。

### Technical implementation path

- [x] **Phase 1 - AstrBot schema 收窄**：`_conf_schema.json` 只保留指定 5 组并按用户指定顺序排列。技术理由：把 AstrBot 原生配置面板收敛为启动/外部集成核心项，降低主面板噪声。
- [x] **Phase 2 - 后端配置公开与写入策略补齐**：`Config.to_public_dict()` 暴露 WebUI 迁移所需字段，`CONFIG_KEY_POLICY` 开放非机密、非结构字段的运行时写入。技术理由：WebUI 设置弹窗不能只读展示，必须通过既有安全写接口持久化。
- [x] **Phase 3 - WebUI 设置迁移入口**：在 `SettingModal` 后端配置区域加入临时高级配置编辑区，补齐未在其他窗口暴露的迁移项，并保持机密字段 env-only。技术理由：不改变数据流页现有入口，只兜住从 AstrBot schema 移除后的配置可达性。
- [x] **Phase 4 - 测试与治理收口**：补 schema 顺序、有效配置公开、配置写入测试；运行后端聚焦测试、前端类型检查和 Next build；更新 `metadata.yaml` 与 `CHANGELOG.md`。技术理由：确保配置入口迁移后可保存、可验证、可追溯。

### Verification

- `python -m pytest tests/backend/test_config.py tests/backend/test_web_server.py -q` → 74 passed。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed。
- `node node_modules/next/dist/bin/next build --webpack`（`web/frontend`）→ passed，13 static routes。未运行 `tools/sync_frontend.py`，因为 `pages/` 为构建产物禁手改区且工作树已有既有产物改动。

---

## v0.25.14 Milvus/Data Cleaning 统一进度闭环 (completed)

### User constraints / 约束

- 检查并闭环 v0.25.3 Milvus 构建进度条：确认已有后台任务、轮询接口和 FilePanel 卡片。
- 在同一条 Milvus 进度条中加入 data cleaning 阶段，不新增分散卡片。
- data cleaning 默认只基于现有 `clean.md/pages.json` 重新清洗并重建 structural chunks，不强制批量 PDF re-extract。
- 修复项目完成度记录：TODO、metadata、CHANGELOG 必须与当前实现对齐。

### Technical implementation path

- [x] **Phase 1 - Job 模型扩展**：`MilvusBuildJob` 新增 `stage`、`stage_label`、`total_clean_docs/processed_clean_docs`、`total_index_docs/processed_index_docs`，`progress_percent` 改为 cleaning + indexing 合并进度，同时保留旧 `total_docs/processed_docs` 字段兼容。技术理由：前端可在同一进度条展示阶段细分，不破坏既有 API。
- [x] **Phase 2 - 后端清洗阶段接入**：`rebuild_vector_store()` / `rebuild_index_pending()` 在索引前预扫描 legacy chunks，调用 `IngestManager.rebuild_document_chunks_from_artifact()`；清洗失败文档计入 `failed_docs` 并跳过 upsert，保留 `needs_reindex=True`。技术理由：避免旧 chunks 进入 Milvus，并让失败可重试。
- [x] **Phase 3 - 能力状态与前端展示**：`core/api_capabilities.py` 在构建中暴露 `build_stage/build_progress_percent`，reason 区分数据清洗、向量索引和收尾；`MilvusBuildCard` 使用同一进度条展示 stage 与 `cleaned/indexed/failed` 明细。技术理由：数据流黄态与文件页进度保持同一事实源。
- [x] **Phase 4 - 测试与治理收口**：补 Milvus job 进度、cleaning 成功、cleaning 失败跳过索引、capabilities stage 断言；更新 v0.25.3 历史段落、`metadata.yaml` 与 `CHANGELOG.md`。技术理由：证明功能不是“记录已写但实现未闭环”。

### Verification

- `python -m pytest tests/backend/test_api.py -q -k "milvus"` → 9 passed / 47 deselected。
- `python -m pytest tests/backend/test_api.py -q` → 56 passed。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed。
- `node node_modules/next/dist/bin/next build --webpack`（`web/frontend`）→ passed，13 static routes。未运行 `tools/sync_frontend.py`，因为本轮明确不改 `pages/`。

---

## v0.25.13 Deep Thinking 召回整合 + 实时进度 + 并行提速 + 瘦身 (completed)

### User constraints / 约束

- 召回修复用「新增部分支持层级」：允许带 hedge 的有据推断进答案，只有真无证据/矛盾/跨来源张冠李戴才计入告警与降级。
- 实时进度走轮询，复用现有 `ProgressStore` + `/api/ask/progress/{cid}`，体积最小。
- 耗时优化仅并行子查询检索、不减轮（保留 4 轮深度，不改语义）。
- 最终答案与「思考过程」区块格式保持与现状一致（仅告警前缀措辞更诚实）。
- 版本只 patch（v0.25.12 → v0.25.13）。

### Technical implementation path

- [x] **Phase 1 - 召回质量（A）**：`_SYNTH_SYSTEM_DEEP` 加「有据推断」档；VERIFY prompt/`VerifyResult`/`parse_verify` 三档化（硬=unsupported+citation_mismatch+contradiction，软=partial+info_gap，不再拍平进单一 missing）；orchestrator `verify_missing` 只取硬项、新增 `verify_notes` 软项；`_deep_warning_prefix` 按硬项计数、无硬项仅软项时温和提示；序列化与 `ThinkingTraceView` 硬/软分行。理由：根除「部分可支持→全盘否定」与「74 项虚高」。
- [x] **Phase 2 - 代码瘦身（D）**：新建 `core/pipelines/deep_thinking_evidence.py`（`rank_candidates`/`select_final_evidence`）与 `deep_thinking_view.py`（`live_detail`/`serialize_outcome`，实时进度与最终 trace 共用序列化），orchestrator 降到 600 行红线内。理由：满足 CONVENTIONS §4 单文件红线 + 单一职责。
- [x] **Phase 3 - 调用提速（C）**：`_gather_round` 子查询检索改 `asyncio.gather` 并发，去重/合并不变。理由：纯提速、不改语义、不减轮。
- [x] **Phase 4 - 实时进度（B）**：`ProgressStore.set/get` 增可选 `detail`；orchestrator `progress` 回调扩为带 detail 并逐轮增量推送（形状复用 round 结构）；前端预生成 `conversation_id` + 轮询 `getAskProgress` 增量渲染，返回后替换为最终 trace。理由：让推演过程逐轮可见、最终格式不变。

### Verification

- [x] `python -m pytest tests/backend -q` → 390 passed（含新增 `test_progress_pushes_incremental_round_detail`、`test_detail_roundtrip_and_optional`、`parse_verify` 三档用例）。
- [x] `ruff check`（新增/改动文件全通过；剩余 E501/F401 为未触及区域既有债务）、`mypy` → domain 3 文件 0 issue；orchestrator = 600 行（红线内）。
- [x] `npx tsc --noEmit` exit 0；`npm run build` exit 0；`python tools/sync_frontend.py` 同步 360 文件。

## v0.25.12 本地 rerank 模型集成与 AB Test (completed)

### User constraints / 约束

- 只在 Deep Thinking 路径启用 rerank，普通 Ask / high_precision 不变。
- 不新增依赖包，复用现有可选依赖 sentence-transformers。
- 未安装 sentence-transformers 时保持 noop；安装后缺省自动启用 gte-reranker-modernbert-base。
- 数据流 Ask 节点开关与模型选择需要即时生效，支持 AB test。
- tests/mocks/run_dev_realtime.py 同步兼容默认 GTE rerank 与开关对照。

### Technical implementation path

- ✅ **Phase 1 - 后端默认与热应用**：调整 RerankConfig 默认模型、provider 自动解析、Deep Thinking reranker 热替换与状态暴露。
- ✅ **Phase 2 - 数据流 UI**：在 Ask 快速配置中增加 rerank 开关、模型配置与状态提示，复用现有 flow-quick 样式。
- ✅ **Phase 3 - realtime 与测试**：更新 realtime mock 配置入口、补充后端/前端 mock 测试并跑聚焦验证。

### Verification

- ✅ `python -m pytest tests/backend/test_config.py tests/backend/test_reranker.py tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_capabilities.py tests/backend/test_api.py -q`（140 passed）。
- ✅ `node node_modules/next/dist/bin/next build --webpack`（Windows 下 `npm run build` 被 PowerShell 执行策略与 Unix `rm` 阻断，已用等价 Next build 入口验证）。

## v0.25.11 Deep Thinking 可靠性小步优化 (completed)

### User constraints / 约束

- 按已确认计划实施，重点放在 Deep Thinking 整体优化：prompt 约束、循环控制、证据选择、校验状态修正。
- 尽量减少代码增加数量，不新增生产模块、不改外部 API schema、不新增前端页面、不引入新检索后端。
- 优先提升多论文问题的证据可靠性：减少关键文献漏召回、跨文档张冠李戴、引用不支撑断言、关键缺口被隐藏和答案过度自信。

### Technical implementation path

- [x] **Phase 1 - prompt 与循环控制**：精修 PLAN/SEA/REFINE/VERIFY prompt；修正收敛条件，未满足 critical 或 coverage 缺口时继续 REFINE。技术理由：减少 LLM 漂移与“sufficient 误收敛”。
- [x] **Phase 2 - 证据选择与校验状态**：在 `_compute_final` 中增加轻量 doc-aware 交错选择；最终 `verify_missing` 非空时强制 `verified=False`。技术理由：降低同源证据垄断，并避免有缺口但显示已验证。
- [x] **Phase 3 - 回归测试**：补充收敛/补检、证据多样性、校验状态、prompt 契约测试。技术理由：锁住本次可靠性行为，不依赖人工判断。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py -q` → passed，36 passed。
- `python -m pytest tests/backend/test_api.py -q` → passed，52 passed。
- `python -m pytest tests/backend/test_cross_document_attribution.py -q` → passed，6 passed。
- `python -m pytest tests/backend/test_retrieval_orchestrator.py tests/backend/test_reranker.py -q` → passed，22 passed / 1 skipped。
- `python -m compileall core/pipelines/deep_thinking_prompts.py core/pipelines/deep_thinking_orchestrator.py tests/backend/test_deep_thinking_orchestrator.py` → passed。
- `python -m ruff check core/pipelines/deep_thinking_prompts.py core/pipelines/deep_thinking_orchestrator.py tests/backend/test_deep_thinking_orchestrator.py` → 未执行：当前 Python 环境无 `ruff` 模块。
- `python -m pytest tests/backend -q` → blocked：收集 `tests/backend/test_r2_target.py` 时当前环境缺 `botocore`。
- `python -m pytest tests/backend -q --ignore=tests/backend/test_r2_target.py` → 367 passed / 2 skipped / 2 failed；失败为当前环境缺 `boto3`（`test_lifecycle_and_cli.py`）与 Windows 路径分隔符断言（`test_zotero_sync.py`），均不在本次改动文件范围内。

## v0.25.10 Deep Thinking 跨文档知识串线修复（来源标注）(completed)

### User constraints / 约束

- 问题：deep thinking 在「Lean4Agent 这篇文章的局限性」一题把 LeanMarathon 论文的 `goal drift / lost-in-the-middle` 当作 Lean4Agent 自身局限输出（跨文档串线）。罕见但危害高。
- 根因在**生成侧**：SEA/VERIFY/合成三处 prompt 拼接证据时只带 `[chunk_id]`/`[n]`，**不标注来源论文**，模型把多篇视为同一文本池。
- **只修生成侧**：给每条证据加来源标注 + system prompt 加反张冠李戴约束。不动检索召回，**保留跨文档对比能力**（不做硬过滤）。
- 向后兼容（`source_labels` 默认 `None` 时行为不变）；版本号 **patch v0.25.10**，未经允许不 bump minor/major。

### Technical implementation path

- [x] **Phase 1 - 证据来源标注**：`synthesize_answer` 加 `source_labels: dict[str,str]|None` + 复用 `source_tag()` 拼 `[{n}]（来源：{label}）`；`build_sea_prompt`/`build_verify_prompt` 同加 `source_labels` 并标注证据行。技术理由：让模型在拼接的证据池里能区分每条来自哪篇论文（`core/pipelines/answer_synthesis.py`、`core/pipelines/deep_thinking_prompts.py`）。
- [x] **Phase 2 - 反串线 system 约束**：抽 `_SOURCE_ISOLATION_RULE` 追加到 `_SYNTH_SYSTEM_DEEP`/`_SYNTH_SYSTEM_BASE`（禁止跨来源张冠李戴）；`VERIFY_SYSTEM`/verify prompt 加跨来源归属检查项计入 `citation_mismatches`。技术理由：双侧（生成 + 校验）兜住串线（`core/pipelines/answer_synthesis.py`、`core/pipelines/deep_thinking_prompts.py`）。
- [x] **Phase 3 - doc_id→label 映射**：`RetrievalOrchestrator.document_labels()` 批量经 `_source_store.get_document()` 解析 title（空回退 doc_id）；orchestrator SEA + verify 闭环（合成/校验同享）构造并传入；`api.ask` deep fallback 据已构造的 `sources`（Zotero 优先 citation）拼 map 传入。技术理由：`DocumentChunk` 不带 title，需在调用点解析（`core/pipelines/retrieval_orchestrator.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`）。
- [x] **Phase 4 - 回归测试**：新增 `test_cross_document_attribution.py`（6 例）——混两篇论文证据集断言三个 prompt 每条证据带正确来源标签且 `[n]` 序不变；`document_labels` 解析与回退；`source_labels=None`/`source_tag` 向后兼容。MockRetrieval/SequenceRetrieval 补 `document_labels` 替身。

### Verification

- `python -m pytest tests/backend/test_cross_document_attribution.py -q` → passed，6 passed。
- `python -m pytest -q`（全量回归）→ passed，374 passed。
- `python -m ruff check`（本次改动文件）→ All checks passed（api.py 仅余既有长行，非本次引入）；`mypy`（改动文件）→ 本次代码 0 error（余项为 lightrag/config/base 既有 repo-wide 噪声）。

---

## v0.25.9 Deep Thinking 深挖 + 答案质量 + 告警分界 (completed)

### User constraints / 约束

- deep thinking 要「从 loop 里发现更多相关内容深挖、优化论点」，不能只围预设 checklist 收敛填空；答案要达到 NotebookLM 式机制级、分维度、跨实体对比的深度。
- **rerank 模型未必引入，其权重应可调到很低甚至为 0**；无 rerank 时排序不能退化为候选插入顺序。
- **告警与真实答案要有明确分界**：正文表面只留一行 notice，完整缺口明细折叠在思考过程里。
- 新增字段/prompt 字段一律向后兼容；版本号沿用 patch；不改 `/api/ask` 对外响应结构语义、不改 Milvus/SQLite/LightRAG/reranker 接口签名。

### Technical implementation path

- [x] **Phase 4a - 后端告警瘦身**：`_deep_warning_prefix` 正文只留一行 notice（含缺口计数），移除全量 missing 列表；明细保留在 `thinking_trace.verify_missing`（`core/api.py`）。
- [x] **Phase 1a - 证据可见度**：`DeepThinkingConfig` 加 `sea_evidence_clip=700`/`verify_evidence_clip=1500`，`build_sea_prompt`/`build_verify_prompt` 加 `clip` 形参，orchestrator 分别传入。技术理由：SEA/VERIFY 只看前 320 字、合成用全文，造成系统性假阴性（`core/config.py`、`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`）。
- [x] **Phase 3 - 预算口径 + 调参**：`_over_budget` 改用全局 `llm_calls_used`（PLAN/SEA/REFINE；VERIFY/合成另由 max_verify_rounds 限界）；`wide_top_k`24、`deep_keep`12、`max_rounds`4、`max_final_evidence`18、`token_budget`36000、`call_budget`18（`core/pipelines/deep_thinking_orchestrator.py`、`core/config.py`）。
- [x] **Phase 1b - per-aspect 排序**：以每个 sub_query 的 `rrf_score` 为主排序信号；`rerank_weight=0` 默认纯 rrf，>0 时按 query 分池 rerank 混合；新增 `Reranker.is_passthrough` 自动置零失效 reranker 权重（`core/pipelines/deep_thinking_orchestrator.py`、`core/repository/reranker/*`、`core/config.py`）。
- [x] **Phase 1c - 开放式发现**：SEA 输出 `discovered_aspects`（独立于 gaps，不进告警），追加非 critical checklist + 驱动 REFINE + 写入 `RoundTrace.discovered` 并序列化（`core/pipelines/deep_thinking_prompts.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/domain/deep_thinking.py`、`core/api.py`）。
- [x] **Phase 1d - PLAN enumerate-then-cover**：对比/共享类问题要求 sub_queries 按实体并行铺机制探针 + 跨维度对比探针（`core/pipelines/deep_thinking_prompts.py`）。
- [x] **Phase 2 - deep 合成 prompt**：`synthesize_answer` 加 `style`，新增 `_SYNTH_SYSTEM_DEEP`；verify 闭环与 api.ask fallback 两条路径都走 `style="deep"`（`core/pipelines/answer_synthesis.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`）。
- [x] **Phase 4b - 前端折叠告警**：`ThinkingTraceView` 收起态显示紧凑缺口计数、展开区加「本轮发现」行；类型补 `discovered`/`origin`（`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- [x] **Phase T - 测试**：新增 orchestrator 7 例（discovered 分离/吸收、per-aspect 排序、is_passthrough、clip 透传、deep 合成、全局 calls 计数）+ api 2 例（discovered/origin 序列化、verify 关闭走 deep fallback 合成）；更新 config 默认值与告警瘦身断言。

### Verification

- `python -m pytest tests/ -q` → passed，368 passed。
- `ruff check`（改动文件）→ 新增代码 0 error（仅余既有 api.py/test 长行，非本次引入）；`mypy` → Success（core/domain/ 3 files）。
- `web/frontend` `tsc --noEmit` → passed（EXIT 0）；`npm run build` → passed，`python tools/sync_frontend.py` → 同步 360 文件到 `pages/`。

---

## v0.25.8 Deep Thinking 展开召回与软降级 (completed)

### User constraints / 约束

- deep thinking 应尽量散开子查询并保留更多 chunk，而不是证据不完美就固定降级到 5 个 baseline chunk。
- 常规证据缺口、critical 未满足、VERIFY 未通过应作为未验证/部分充分返回；只有硬失败才 `degraded=True`。
- 不改变 `/api/ask` 对外响应结构，不改 Milvus/SQLite/LightRAG/reranker 接口。

### Technical implementation path

- [x] **Phase 1 - 软降级策略**：将 SEA gap、未满足 checklist、critical 未满足从硬降级条件移除；这些情况保留探索 evidence，并通过 `verify_missing`/trace 暴露缺口。技术理由：deep thinking 的价值在于累积多轮证据，不能因部分缺口丢弃探索结果。
- [x] **Phase 2 - final evidence 上限**：新增内部 `max_final_evidence=16`，final evidence 按 structural anchor、baseline floor、rerank score 优先级截断。技术理由：允许超过 5 个 chunk，同时避免上下文无限膨胀。
- [x] **Phase 3 - 回归测试**：覆盖 gap/critical 不再降级、硬失败仍降级、final cap 生效、verification 补检证据进入 final、API partial warning 不显示 degraded mode。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py -q` → passed，24 passed。
- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py -q` → passed，74 passed。
- `python -m compileall core/config.py core/pipelines/deep_thinking_prompts.py core/pipelines/deep_thinking_orchestrator.py tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py` → passed。
- `python -m ruff check core\config.py core\pipelines\deep_thinking_prompts.py core\pipelines\deep_thinking_orchestrator.py tests\backend\test_deep_thinking_orchestrator.py tests\backend\test_api.py` → 未执行：当前 Python 环境无 `ruff` 模块（`No module named ruff`）。

---

## v0.25.7 Deep Thinking 缺口率文案修正 (completed)

### User constraints / 约束

- 前端展示「证据缺口率 175%」不可理解，缺口率不应超过 100%。
- 不改变 deep thinking 对外响应结构，只修正降级判定指标与文案。

### Technical implementation path

- [x] **Phase 1 - 缺口指标修正**：把降级判定从 `len(gaps) / len(checklist)` 改为未满足 checklist 项占比，并将展示文案改为「未满足检查项 X/Y」而非超过 100% 的缺口率。技术理由：一个检查项可能产生多个 gap，按 gap 数量除以 checklist 数量会产生无意义百分比。
- [x] **Phase 2 - 回归测试**：新增多 gap 少 checklist 的回归用例，确认降级原因不出现超过 100% 的百分比。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py -q` → passed，22 passed。
- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py -q` → passed，72 passed。
- `python -m compileall core\pipelines\deep_thinking_orchestrator.py tests\backend\test_deep_thinking_orchestrator.py` → passed。

---

## v0.24.3 扫描件 PDF 阅读面板空白页修复 (completed)

### User constraints / 约束

- 仅修前端 PDF 渲染空白问题（如 Massumi 1995 扫描件），chunk/文本抽取已正常，不动后端。
- 只做 patch 版本升级（0.24.2 → 0.24.3）。
- 不改动现有 worker 加载方式（生产构建里工作正常）。

### Technical implementation path

- [x] **Phase 1 - 暴露 pdfjs-dist 运行时资源**：新增 `web/frontend/scripts/copy-pdfjs-assets.mjs`，把 `node_modules/pdfjs-dist/{wasm,cmaps,standard_fonts}` 拷到 `public/pdfjs/`；`package.json` 加 `prebuild`/`predev` 自动执行；`.gitignore` 忽略 `public/pdfjs/`。技术理由：`output: "export"` 下 public/ → out/ → pages/ 是唯一一处 dev 与 prod 都能在 `/pdfjs/...` 访问的位置。
- [x] **Phase 2 - getDocument 指向资源**：`PdfViewer.tsx` 给 `getDocument` 传 `wasmUrl`/`cMapUrl`/`cMapPacked`/`standardFontDataUrl`，并扩展本地类型签名。技术理由：pdfjs v6 把 JBIG2/JPEG2000 解码器迁到 WASM，缺 `wasmUrl` 导致扫描页图像解码失败、整页全白。
- [x] **Phase 3 - 渲染健壮性**：渲染异常只忽略 `RenderingCancelledException`，其余 `console.error`；HiDPI 改用 render `transform` 参数而非预设 `context.setTransform`（v6 会忽略预设变换）。技术理由：避免空白页无线索，并修高 DPR 屏内容缩到左上角。

### Verification

- `cd web/frontend && node scripts/copy-pdfjs-assets.mjs` → passed，生成 `public/pdfjs/wasm/jbig2.wasm`（104852 B）等。
- `npx tsc --noEmit` → passed，无类型错误。
- `npm run build` → passed（prebuild 自动拷贝，`out/pdfjs/wasm/jbig2.wasm` 存在）。
- `python tools/sync_frontend.py` → passed，`pages/pdfjs/wasm/jbig2.wasm` 存在，mimetype `application/wasm`。
- `python -m pytest -q` → passed，356 passed。
- 离线复现（排查阶段）：`@napi-rs/canvas` + pdfjs 渲染第 2 页，配置 `wasmUrl` 后 `nonwhite` 由 `0.00%` 升至 `6.06%`（第 3 页 `13.42%`）。

---

## v0.25.6 Deep Thinking prompt 协议与数据流图 (completed)

### User constraints / 约束

- 实施 deep thinking prompt/data-flow 优化，保持 `/api/ask` 对外响应结构不变。
- PLAN/SEA/REFINE/VERIFY 增强结构化控制信号，旧 JSON 输出必须继续兼容。
- 输出 `docs/deep_thinking_flow.png`，并保留 Mermaid 源方便审阅。
- 不新增运行时依赖；PNG 使用当前环境已有的 Pillow 生成。

### Technical implementation path

- [x] **Phase 1 - prompt 协议增强**：扩展 PLAN/SEA/REFINE/VERIFY prompt，加入 evidence plan、coverage matrix、typed gap queries 与 claim-level audit。技术理由：让 LLM 输出更可控的检索/审计信号。
- [x] **Phase 2 - 解析与领域模型兼容扩展**：扩展 `ChecklistItem` 和 prompt 解析 dataclass，所有新增字段带默认值；解析器同时兼容旧格式与新格式。技术理由：不改变对外 API 和主流程契约。
- [x] **Phase 3 - orchestrator 数据流接入**：SEA 结果派生 satisfied/gaps/conflicts，REFINE 使用 typed gaps，VERIFY claim-level 问题合并到 `verify_missing`。技术理由：提升补检命中率和未验证原因质量。
- [x] **Phase 4 - 文档图输出**：新增 Mermaid 源 `docs/deep_thinking_flow.md` 与 PNG `docs/deep_thinking_flow.png`。技术理由：让数据流可审阅、可复现。
- [x] **Phase 5 - 回归测试**：补充新旧 JSON 兼容、coverage matrix、typed gaps、claim-level verify 与现有 API 行为测试。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py -q` → passed，71 passed。
- `python -m compileall core/domain/deep_thinking.py core/pipelines/deep_thinking_prompts.py core/pipelines/deep_thinking_orchestrator.py tests/backend/test_deep_thinking_orchestrator.py` → passed。
- `python -c "from PIL import Image; p='docs/deep_thinking_flow.png'; im=Image.open(p); print(p, im.size, im.mode)"` → passed，`(1800, 1500) RGB`。
- `python -m ruff check core\domain\deep_thinking.py core\pipelines\deep_thinking_prompts.py core\pipelines\deep_thinking_orchestrator.py tests\backend\test_deep_thinking_orchestrator.py` → 未执行：当前 Python 环境无 `ruff` 模块（`No module named ruff`）。

---

## v0.25.5 Deep Thinking 证据不足回答警告 (completed)

### User constraints / 约束

- deep thinking 在证据不足或未验证时仍可保留回答，但答案正文开头必须明确提示证据不足/未验证。
- 开启英语召回时，检索可使用翻译 query，最终合成与 verification 必须使用用户原始问题。
- 不改变 `/api/ask` 响应结构，复用现有 `thinking_trace` 字段。

### Technical implementation path

- [x] **Phase 1 - 问题源与合成约束对齐**：`DeepThinkingOrchestrator.run()` 新增 `answer_question`，检索/PLAN/SEA/REFINE 保持用 `query`，最终合成与 VERIFY 改用 `answer_question or query`；`api.ask()` deep_thinking 调用传入原始 `question`；同步增强普通与 deep 合成 prompt 的证据不足约束。技术理由：避免英语召回翻译污染最终回答意图。
- [x] **Phase 2 - 证据不足/未验证答案前缀**：在 `api.ask()` 对 deep outcome 生成的答案统一加警告前缀：degraded 展示降级原因，unverified 展示 missing 或通用未验证提示；警告语言跟随 `answer_language`/原问题。技术理由：保留草稿答案但不伪装成已充分支撑结论。
- [x] **Phase 3 - verification 语义收紧**：VERIFY JSON 解析失败不再视为通过，改为返回当前 draft 且 `verified=False`。技术理由：校验失败应暴露为未验证，而不是误标通过。
- [x] **Phase 4 - 回归测试**：覆盖英文召回原问题合成、degraded 警告、unverified missing 警告、VERIFY 解析失败未通过，以及 verified 通过路径不加警告。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py -q` → passed，66 passed。
- `python -m ruff check core\api.py core\pipelines\answer_synthesis.py core\pipelines\deep_thinking_orchestrator.py tests\backend\test_deep_thinking_orchestrator.py tests\backend\test_api.py` → 未执行：当前 Python 环境无 `ruff` 模块（`No module named ruff`）。

---

## v0.25.4 深度思考降级原因暴露 + PDF 重提取 + 独立 LLM 配置 (completed)

### User constraints / 约束

- 深度思考模式静默降级到 baseline 时，前端无法得知原因；用户无法区分「LLM 不可用」还是「证据不足」。
- 已摄入的 PDF（如 Massumi 1995）因 `ignore_alpha=True` 修复前摄入，`clean.md` 只含首页内容，需要重新提取而无需重新上传。
- `cmd_config.json` 的 `provider: []` 导致 AstrBot LLM 接口不可用；深度思考应能配置独立 OpenAI-compat endpoint 绕过此限制。
- 版本号为 **patch v0.25.4**，未经允许不 bump minor/major。

### Technical implementation path

- [x] **Phase 1 - 降级原因链路**：`DeepThinkingOutcome` 新增 `degraded_reason: str = ""`；`_degraded()` 增加 `reason` 参数；各 `except Exception` 传 `str(exc)`；证据不足路径拼接人类可读原因；`_serialize_deep_thinking()` 暴露字段；`ThinkingTraceView` 在 badge 下展示（`core/domain/deep_thinking.py`、`core/pipelines/deep_thinking_orchestrator.py`、`core/api.py`、`web/frontend/components/panels/ChatPanel.tsx`、`web/frontend/lib/api.ts`）。
- [x] **Phase 2 - PDF 重提取**：`IngestManager.reextract_document()` 定位原件 PDF、重跑修复后提取代码、覆写 `clean.md`/`pages.json`、重新分块写库并标 `needs_reindex`；新增 `POST /api/documents/{doc_id}/reextract` 路由；前端 `DocumentsPanel` 对 PDF 文档显示「重新提取」按钮（`core/managers/ingest_manager.py`、`core/api.py`、`web/server.py`、`web/frontend/components/panels/DocumentsPanel.tsx`、`web/frontend/lib/api.ts`、`web/frontend/lib/i18n.ts`）。
- [x] **Phase 3 - 深度思考独立 LLM**：`DeepThinkingConfig` 新增 `llm_base_url`/`llm_model`/`llm_api_key`；`plugin_initializer.py` 条件选择 `LMStudioLLMAdapter` 或回退 AstrBot 主 LLM；`ENV_DEEP_THINKING_LLM_API_KEY` 常量支持环境变量（`core/config.py`、`core/plugin_initializer.py`）。
- [x] **Phase 4 - 测试补全**：`test_deep_thinking_orchestrator.py` 为所有降级路径补 `degraded_reason` 断言；新增 `test_sea_llm_unavailable_degrades_to_baseline` 与 `test_refine_llm_unavailable_degrades_to_baseline` 用例。

### Verification

- `python -m pytest tests/backend/test_deep_thinking_orchestrator.py -v` → 14 passed（含 4 个新/更新断言）。
- `python -m pytest -q` → 344 passed（全量回归）。
- `cd web/frontend && npm run build` + `python tools/sync_frontend.py` → 构建并同步产物。

---

## v0.25.3 Milvus 向量库 + data cleaning 统一进度条 (completed)

### User constraints / 约束

- 参考 LightRAG 进度条：Milvus 构建/更新（`rebuild_vector_store` 全量 / `rebuild_index_pending` 增量）也要有实时进度条。
- **位置**：统一一条放在 file 页面（FilePanel）左下角/底部，**无任务时不显示**（不按 Zotero/本地分区分散）。
- **无暂停功能**（必须构建成功，与 LightRAG 不同）。
- **失败处理**：构建结束若有 `failed_docs>0`，进度条转红色 + 「重试」按钮；向量库节点保持黄色不可用直到全部成功。
- 构建未成功前，数据流呈 pending 色、向量库节点黄色，示意功能暂不可用。
- 在同一条 Milvus 进度条中加入 data cleaning 阶段：先基于现有 `clean.md/pages.json` 重新清洗并重建 structural chunks，再进入向量索引；不在该流程中强制批量 PDF re-extract。
- 版本号为 **patch v0.25.3**，未经允许不 bump minor/major。

### Technical implementation path

- [x] **Phase 1 - 后端任务对象 + 后台执行**：新增/扩展 `core/milvus_build.py`（`MilvusBuildJob` dataclass + `to_dict()` 含 `progress_percent`、`stage`、cleaning/indexing counters）；`core/api.py` 加 `self._milvus_build_job/_task` 状态、`start_milvus_rebuild()`（后台 `create_task`、立即返回、防并发）、`_run_milvus_rebuild()`、`get_active_milvus_build_job()`；给 `rebuild_vector_store/rebuild_index_pending` 加可选 `job` 进度钩子（保持原签名/返回兼容）。技术理由：复用现有逐文档循环作进度源，最小侵入。
- [x] **Phase 2 - data cleaning 阶段接入**：Milvus rebuild 先预扫描需要 legacy chunk 修复的文档，调用 `IngestManager.rebuild_document_chunks_from_artifact()` 清洗并重建 chunks；清洗失败的文档计入 `failed_docs` 并跳过索引。技术理由：避免旧 chunks 被写入 Milvus，并让同一进度条覆盖清洗阶段。
- [x] **Phase 3 - 构建中保持黄色**：`core/api_capabilities.py:_milvus_runtime_health()` 在存在 running 的 `_milvus_build_job` 时强制 `rebuild_required=True` + `building=True`，reason 包含当前 stage。技术理由：避免最后一个文档清除 `needs_reindex` 后过早变绿。
- [x] **Phase 4 - HTTP 路由**：`web/server.py` 改 `handle_rebuild_index_pending` 为后台触发即返回 `{status:"started", job}`；新增 `GET /api/documents/rebuild-index/active`。技术理由：前端需轮询进度。
- [x] **Phase 5 - 前端 API + 进度卡片**：`api.ts` 加 `MilvusBuildJob` 类型 + `getActiveMilvusBuildJob()`；`FilePanel.tsx` 加轮询 + 底部 `MilvusBuildCard`（复用 `BuildCard` 视觉、同一进度条显示 data cleaning / vector indexing stage、无暂停、失败转红 + 重试）；`FlowPageContent.tsx:handleRebuildIndex` 改触发即返回；`i18n.ts` 补 `file_milvus_build_*` 中英文案。技术理由：UI 与 LightRAG 体验一致。
- [x] **Phase 6 - 测试与验证**：补后端单测（进度推进、data cleaning counters、构建中保持黄、partial_failure）；保持现有 rebuild 测试绿；前端 typecheck/build 通过。技术理由：用自动化验证完成进度条闭环。

### Verification

- `python -m pytest tests/backend/test_api.py -q -k "milvus"` → 9 passed / 47 deselected。
- `python -m pytest tests/backend/test_api.py -q` → 56 passed。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false`（`web/frontend`）→ passed。
- `node node_modules/next/dist/bin/next build --webpack`（`web/frontend`）→ passed，13 static routes。未运行 `tools/sync_frontend.py`，因为本轮明确不改 `pages/`。

---

## v0.25.2 弹窗层级（z-index / 浮层裁切）系统性修复 (completed)

### User constraints / 约束

- 现象：ChatPanel 齿轮「设置 popover」等浮层被相邻面板盖住 / 在面板边缘被裁切，多处复现。
- 根因：浮层内联渲染（`position:absolute/fixed` + 散乱 z-index），被祖先 stacking context（`fx-glass` 的 `backdrop-filter`、面板 `transform`/`will-change`、`position:relative+z-index`）与 `overflow:hidden/auto` 关住——单纯调大 z-index 修不好。
- 修法：统一 z-index 量表（单一真源）+ 浮层 portal 到 `document.body`，复用仓库已有 portal 范式（`TerminalPanel`/`PerfPanel`）。
- 版本号为 **patch v0.25.2**，未经允许不 bump minor/major。

### Technical implementation path

- [x] **Phase 1 - 统一 z-index 量表**：新增 `web/frontend/lib/zLayers.ts` 导出语义化 `Z`（base/raised/widget/dialog/panel/dropdown/tooltip/toast，单调递增，`dropdown/tooltip > dialog` 以支持嵌套）；`styles/tokens.css` `:root` 同步 `--z-*` CSS 变量，`.flow-custom-select`/`.dir-picker-overlay` 改引用。
- [x] **Phase 2 - 锚定浮层原语**：新增 `components/ds/Popover.tsx`（headless，`createPortal` 到 body + `getBoundingClientRect` 定位 + scroll/resize 重算 + outside-click/Escape），并入 `ds/index.ts`。
- [x] **Phase 3 - 锚定型改造**：`ds/Tooltip.tsx`、`ds/Select.tsx`、`ChatPanel` 设置 popover 改用 Popover；移除 Select/ChatPanel 各自重复的 outside-click effect。
- [x] **Phase 4 - 全屏 modal portal 化**：`ds/Modal.tsx`、`ChatPanel` 精度弹窗、`FilePanel` ×3 统一 `createPortal` 到 body + `Z.dialog`。
- [x] **Phase 5 - 对齐量表**：`PerfPanel`/`TerminalPanel`/`Toast`/`TopBar`/`BuildWidget`/login 取 `Z.*`。（`Rail.tsx` 未被任何页面引用且无 zIndex，跳过不动死代码。）

### Verification

- `cd web/frontend && node_modules/.bin/tsc --noEmit` → passed（本任务改动文件零错误）。
- `cd web/frontend && npm run build` → ✓ Compiled successfully（基于本任务改动；随后 sync 162 文件到 `pages/`）。
- `python tools/sync_frontend.py`（out/ → pages/，未手改 pages/）→ done。
- ⚠️ 注：之后并行进行中的 v0.25.3（Milvus 进度条）在 `FilePanel.tsx` 引入了 7 个尚未补的 `file_milvus_build_*` i18n key（其 Phase 4 仍 `[ ]`），会使**当前** `tsc`/`npm run build` 失败；该报错全部位于 v0.25.3 新代码，与本任务无关，待其补齐文案后即恢复绿。
- 手测：齿轮 popover / Select / Tooltip 不再被裁切遮挡；modal 内 Select 盖在 modal 之上；Toast 最顶 → 待用户手测确认。

---

## v0.25.1 Rerank 去模型依赖 + 内容去重 + Answer Verification 闭环 (completed)

### User constraints / 约束

- rerank 默认退到零模型零部署（`provider=noop`）；cross-encoder 改为显式 `cross_encoder` 才下载，不再自动；**不做 MMR**（复用 bge-en embedding 算 relevance 是重复 dense 召回 + 继承语言偏差）。
- 多路召回的内容重复：同 `chunk_id` 已由 RRF 去重；新增**零模型 `content_hash` 去重**处理「不同 chunk_id 内容相同」。
- verification 做**完整再检索闭环**（答案不合格→未支撑点当 gap 回 orchestrator 补检→再合成），成为精度主承担者；LLM verify 异常不打崩。
- 版本号为 **patch v0.25.1**，未经允许不 bump minor/major。

### Technical implementation path

- [x] **Phase 1 - rerank 去模型依赖 + 内容去重**：`RerankConfig.provider` 默认 `noop`、枚举 `{noop, cross_encoder}`（旧 `auto`/`mmr`→`noop`）；`build_reranker` 仅 `cross_encoder` 时懒加载，去掉自动下载；`retrieve_with_outcome` RRF 后按 `content_hash` 去重。技术理由：rerank 在 loop+verification 下降为收敛加速器，精度交给 verification；内容去重避免冗余上下文误导 SEA/verify。
- [x] **Phase 2 - Answer verification 完整闭环**：新增 `answer_synthesis.py` 共享合成；`DeepThinkingOutcome` 增 `answer`；orchestrator finalize `合成 draft→VERIFY→missing 当 gap 再检索` 循环（`max_verify_rounds` + budget 限）；`DeepThinkingConfig` 增 `verify_enabled`/`max_verify_rounds`；api.ask 优先用 `outcome.answer`。技术理由：答案级闭环让精度由「答案是否被证据支撑」驱动，调整决策10（orchestrator 承担合成）。

### Verification

- `python -m pytest tests/backend/test_reranker.py tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_api.py tests/backend/test_config.py tests/backend/test_retrieval_orchestrator.py -q` → passed，99 passed。
- `python -m pytest -q`（全量回归）→ passed，340 passed。
- `ruff check`（新增/改动文件）→ All checks passed；`mypy`（strict `core/domain/`）→ Success, no issues。

---

## v0.25.0 Deep Thinking 迭代检索（FAIR-RAG + Reranker）(completed)

### User constraints / 约束

- `retrieval_mode="deep_thinking"` 手动触发，`collection` 必填；不污染 `default` / `high_precision` / `graph_only`。
- 不重写 Milvus/SQLite/AstrBot 混合召回内核；只在其上层加 rerank、迭代编排。
- 不碰 LightRAG；不改 `LLMAdapter` 接口（token 用字符近似估算）。
- 精度优先：deep thinking 内部不为省钱取舍；但 LLM 不可用/异常必须优雅回退 baseline，绝不打崩请求。
- 无 `enabled` 双开关：手动 mode 即开关；reranker 单开关 `provider: auto|noop`，缺依赖自动 noop 不影响普通 ask。

### Technical implementation path

- [x] **Phase 1 - Reranker 组件 + RetrievalOutcome 信号扩展**：新增 `core/repository/reranker/`（base ABC + noop + bge_local 可选依赖 + `build_reranker` 工厂）与 `core/utils/cutoff.py`（`adaptive_cutoff` 纯函数）；扩展 `RetrievalOutcome` 旁路字段 `per_chunk_signals`（rrf_score/anchor_hit），不改 RRF 排序与既有 `chunks` 契约。技术理由：reranker 作独立组件供单轮与迭代复用；pinned 结构命中需 `anchor_hit` 信号支撑。
- [x] **Phase 2 - domain 模型 + 类型化配置 + 治理**：新增 `core/domain/deep_thinking.py`（Checklist/EvidenceItem/RoundTrace/DeepThinkingOutcome，无 answer）；config 新增 `RerankConfig`/`DeepThinkingConfig` + getter；最小暴露 `_conf_schema.json` 与 `CONFIG_KEY_POLICY`。技术理由：checklist 带 `id` 供 SEA 按 id 引用，避免字符串匹配误判。
- [x] **Phase 3 - DeepThinkingOrchestrator 迭代循环**：新增 `core/pipelines/deep_thinking_orchestrator.py` + `deep_thinking_prompts.py`；baseline 先于 PLAN（无 LLM）、pinned+baseline_floor 保底、conflicting 循环后过滤、LLM 调用异常→degraded 回退 baseline、JSON 不合格按步降级。技术理由：保证「永不比 baseline 差」可判定，LLM 全挂仍优雅降级。
- [x] **Phase 4 - api.ask 集成 + 组合根装配**：`ask()` 加 deep_thinking 分支（collection 必填校验、复用现有 sources/generate 合成、三态 `actual_mode`、`thinking_trace` 返回）；`plugin_initializer` 装配 reranker + orchestrator 并注入 api。技术理由：合成唯一归 api.ask 杜绝重复合成；向后兼容（新参数默认 None）。

### Verification

- `python -m pytest tests/backend/test_reranker.py tests/backend/test_deep_thinking_orchestrator.py tests/backend/test_config.py tests/backend/test_api.py tests/backend/test_retrieval_orchestrator.py -q` → passed，89 passed。
- `python -m pytest -q`（全量回归）→ passed，330 passed。
- `ruff check`（本次新增文件）→ All checks passed；`mypy`（strict 范围 `core/domain/` 含 deep_thinking.py）→ Success, no issues。

---

## v0.24.15 通用论文结构识别与召回优化 (completed)

### User constraints / 约束

- 用户私有样本仅作为例子，结构识别和召回应面向通用论文，不做私有论文专用逻辑。
- 私密论文标题、正文、`clean.md` 或 chunk 预览不得写入可提交文件；测试只使用合成样例。
- 保持 `clean_md[start_char:end_char] == chunk.text` offset 不变量。

### Technical implementation path

- [x] **P1 - 收紧标题识别**：降低纯数字、公式编号、表格数字被误判为 `section_heading` 的概率，同时保留 `1 Introduction`、`2.1 Method`、`Appendix A`、References 等通用结构。技术理由：arXiv 复杂版式中数字误判会制造短 chunk 与错误 section metadata。
- [x] **P2 - 通用锚点 metadata**：为 chunk 保存覆盖范围内的 `anchor_labels`，包含 figure/table/equation/caption label，并补 `section_level`。技术理由：caption 被合并进正文 chunk 后仍应可被结构召回命中。
- [x] **P3 - 召回 anchor 泛化**：支持 `section 2`、`section 2.1`、`chapter 3`、`第2节`、`appendix A`、`Figure/Table/Eq`；单独数字仍不作为强锚点。技术理由：避免为某一论文体例写死，同时降低页码/公式编号误召回。
- [x] **P4 - 合成回归与验证**：补通用论文结构 fixture，运行目标后端测试与编译检查，通过后补 CHANGELOG。技术理由：覆盖普通论文标题、图表锚点和误判防线，不暴露私密内容。

### Verification

- `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q` → passed，21 passed / 1 skipped。
- `python -m pytest tests\backend\test_api.py -q` → passed，38 passed。
- `python -m compileall core\managers\chunking.py core\pipelines\retrieval_orchestrator.py tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py` → passed。
- 公开 arXiv smoke（临时目录，不写入仓库）→ `1706.03762`、`1512.03385`、`1602.07261`、`1602.03837` 均无 suspicious numeric heading；Figure/Table anchor probe 可命中；私密论文未写入测试或文档。

---

## v0.24.14 文档面板 chunk 标题渲染 (completed)

### User constraints / 约束

- 前端 chunk 预览需要把 `**T14**`、`**2.** **Title**`、`_2.1._ _Title_` 这类结构标记渲染为标题样式。
- 标题后的换行正文或同一行正文必须继续显示，不丢内容。
- 这是纯展示层优化，不改变后端 API、SQLite chunk、Milvus 索引、检索逻辑和 offset 不变量。
- 不把私密论文标题、正文、`clean.md` 或 chunk 预览写入可提交文件；测试只使用合成样例。

### Technical implementation path

- [x] **P1 - 轻量 parser**：新增纯 TypeScript chunk 文本解析函数，只识别 chunk/段落开头的结构标题。技术理由：避免引入完整 Markdown renderer，也避免正文中的普通 `**bold**` 被误判。
- [x] **P2 - DocumentsPanel 渲染接入**：用 `ChunkText` 组件替换原始 `{c.text}` 直出，标题用紧凑标签样式，正文保留段落和换行。技术理由：只改 UI 展示，不影响数据层。
- [x] **P3 - 验证与收口**：用合成样例验证 parser，运行前端 typecheck/build/sync，通过后补充 CHANGELOG。技术理由：保证静态产物与源码一致。

### Verification

- `python -m pytest tests\frontend\test_chunk_text_parser.py -q` → passed，1 passed。
- `node node_modules/typescript/bin/tsc --noEmit` → passed。
- `node node_modules/next/dist/bin/next build --webpack` → passed，13 static routes。
- `python tools\sync_frontend.py` → synced 164 files to `pages/`。
- `python tools\sync_frontend.py --check` → passed，`pages/` 已与 `web\frontend\out` 一致。

---

## v0.24.13 文档面板 chunk 预览自动刷新 (completed)

### User constraints / 约束

- 前端文档面板应显示当前 structural_v3 chunking，而不是旧 SQLite legacy chunks。
- 不写入私有论文标题、正文、`clean.md` 或 chunk 预览；测试使用合成数据。

### Technical implementation path

- [x] **P1 - 读接口接入 legacy rebuild**：`list_document_chunks()` 在返回前复用 `chunk_needs_rebuild()` / `rebuild_document_chunks_from_artifact()`。技术理由：文档面板是读 SQLite chunks，不走 Milvus 索引路径，必须在读接口处保证 schema 新鲜。
- [x] **P2 - chunk context 同步**：`get_chunk_context()` 也先确保 chunks 当前化。技术理由：引用跳转或上下文窗口不能继续围绕旧 chunk id/ordinal 展示。
- [x] **P3 - runtime seed 对齐**：本地 6521 runtime 播种脚本改为直接生成 structural_v3 chunks 与 `pages.json`。技术理由：mock runtime 之前绕过 IngestManager 手写旧 chunk，导致前端预览仍是旧切片。
- [x] **P4 - API 回归测试**：补合成测试验证旧 chunk 在前端读取路径会自动替换为新版 chunk。技术理由：避免以后只修索引路径、忘记管理端预览路径。

### Verification

- `python -m pytest tests\backend\test_api.py -q` → passed，38 passed。
- `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q` → passed，16 passed / 1 skipped。
- `python -m compileall core\api.py tests\backend\test_api.py` → passed。
- `python -m py_compile tests\mocks\run_dev_realtime.py` → passed。

---

## v0.24.12 parent heading chunk 合并修复 (completed)

### User constraints / 约束

- 只做小修，修复父章节标题独立成极小 chunk 的问题。
- 不把私有论文标题、正文、`clean.md` 或 chunk 预览写入可提交文件；测试只使用合成 fixture。

### Technical implementation path

- [x] **P1 - 合并策略修复**：允许短的父章节标题 chunk 合并到第一个子章节 chunk，例如 `2` 合并到 `2/2.1`。技术理由：父章节标题本身不是可检索语义正文，单独进入向量库会制造极短噪声 chunk。
- [x] **P2 - metadata 保真**：合并后保留 chunk 覆盖到的全部 `section_labels` / `section_paths`，让父章节和子章节 anchor 都能命中。技术理由：不能为了消除小 chunk 牺牲 `2.1` 一类精确召回。
- [x] **P3 - 合成回归测试**：补 synthetic numbered-section fixture，断言父标题不会独立成短 chunk，且 `2` 与 `2.1` metadata 都存在。技术理由：复现结构形态，不写入私有论文内容。

### Verification

- `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q` → passed，16 passed / 1 skipped。
- `python -m pytest tests\backend\test_api.py -q` → passed，37 passed。
- 私有 PDF 手工验证 → 本地临时目录重建 chunk 预览，匿名指标为 `chunks=53`、`MIN_LEN=439`、`SHORT_UNDER_160=0`、`HEADING_ONLY_SHORT=0`；不记录论文标题、正文或 chunk 预览。

---

## v0.24.11 structural_v3 分块与召回 handle (completed)

### User constraints / 约束

- 私有论文内容、导出的 `clean.md`、chunk 预览和长摘录不得进入可提交文件；私有样本只允许本地手工验证。
- 分块链路按 `clean → chunk → handle` 分层：clean 只做文本规范化，chunk 只做结构切分，handle 负责召回友好性。
- chunk 边界优先依据章节、段落、caption、list/equation/reference entry 结尾；普通段落不因接近字符目标而硬切。
- `chunk_size` 作为软目标，不破坏结构边界；只有单个 block 极端超长时才启用 citation-aware 句子兜底。
- 继续保持 offset 不变量：`clean_md[start_char:end_char] == chunk.text`。

### Technical implementation path

- [x] **P1 - chunking 模块拆分**：新增 `core/managers/chunking.py`，定义 `TextBlock` / `SectionSpan` / `ChunkSpan` 与 parse / pack / validate 流程；`IngestManager` 只负责调用。技术理由：把结构解析从摄入流程中解耦，避免继续堆私有 helper。
- [x] **P2 - block parser**：识别 front matter、章节标题、子标题、段落、figure/table caption、equation/list/reference entry，并保留每个 block 的精确字符区间。技术理由：chunk 必须建立在结构块上，而不是裸字符位置上。
- [x] **P3 - section tree metadata**：生成 `section_type`、`section_label`、`section_path`、`section_title`、`subsection_label`、`section_start_char/end_char` 与 `block_types`。技术理由：让 T 编号、编号章节、图表和 introduction 能被召回层稳定定位。
- [x] **P4 - structural packer**：仅在 block 边界打包 chunk，短 heading/thesis 向同 section 后续正文合并，超长单 block 才走 citation-aware sentence split。技术理由：解决引用缩写、括号引用和段落中途断裂。
- [x] **P5 - retrieval handle**：基于 query 中的 T 编号、section path、figure/table anchor 和 subsection label 做 fast-path，并对短 chunk 自动扩展同 section 相邻内容。技术理由：结构化 chunk 需要结构化召回兜底，降低非对称 chunk 对向量召回的影响。
- [x] **P6 - legacy rebuild 与 schema 升级**：将新分块 schema 标记为 `clean_md_structural_v3`，旧 schema 或缺 metadata 的文档从现有 `clean.md` 重建并标记 Milvus reindex。技术理由：已有库需要从 v2 边界平滑迁移到 structural_v3。
- [x] **P7 - 测试与收口**：补合成 fixture 覆盖引用缩写、括号引用、introduction、T 编号、小节、图表 caption、offset invariant 和召回 fast-path；通过后追加 CHANGELOG。技术理由：测试不得包含私有论文正文，同时要复现已发现的边界类型。

### Verification

- `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q` → passed，14 passed / 1 skipped。
- `python -m pytest tests\backend\test_api.py -q` → passed，37 passed。
- `python -m compileall core\managers\chunking.py core\managers\ingest_manager.py core\managers\markdown_extractor.py core\api.py core\pipelines\retrieval_orchestrator.py tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py` → passed。
- `python -m ruff check ...` → blocked，本环境未安装 `ruff`（`No module named ruff`）。
- `git diff --check -- TODO.md CHANGELOG.md core\managers\chunking.py core\managers\ingest_manager.py core\managers\markdown_extractor.py core\api.py core\pipelines\retrieval_orchestrator.py tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py` → passed。
- 私有内容扫描 → 本轮新增代码、测试与文档只保留匿名描述，未写入私有论文标题、正文、`clean.md` 或 chunk 预览。

---

## v0.24.10 数据清洗与 Milvus 分块优化 (completed)

### User constraints / 约束

- `clean.md` 允许作为检索文本做确定性规范化清洗；PDF 原件不改。
- 修复页眉、页码、软连字符断词与异常空白，保留段落结构。
- Milvus chunk 需优先按段落 / 句末 / 标题边界切分，避免句中硬切和短残片。
- 不新增独立 `document_sections` 表，先把 section 信息写入 chunk metadata。
- 既有 legacy chunks 需要可重建为新分块，并标记 Milvus 需重建。

### Technical implementation path

- [x] **P1 - 清洗后处理**：在 PyMuPDF4LLM 输出后增加 deterministic post-clean，去除重复页眉与边缘页码，修复软连字符换行和异常空白。技术理由：先降低输入噪声，避免页眉页码进入 chunk 与向量索引。
- [x] **P2 - paragraph-aware chunker**：重写 clean.md 分块策略，按标题 / 段落 / 句末 / 词边界分层切分，保留 offset 不变量并补 section metadata。技术理由：Milvus chunk 应保持语义完整，不能在普通句子中间硬截断。
- [x] **P3 - legacy chunk rebuild path**：为已有 `clean.md` 文档提供重建 chunks 的路径，识别旧式 chunk / 缺 metadata / converter 缺失并标记 `needs_reindex`。技术理由：已有库需要可从脏分块迁移到新分块。
- [x] **P4 - 回归测试与收口**：补清洗、分块、T55/paragraph fixture 测试，运行目标 pytest；通过后标记完成并追加 CHANGELOG。技术理由：锁住 offset、分块边界和 legacy 检测契约。

### Verification

- `python -m pytest tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py -q` → passed，11 passed / 1 skipped。
- `python -m pytest tests\backend\test_api.py -q` → passed，37 passed。
- `python -m compileall core\managers\markdown_extractor.py core\managers\ingest_manager.py core\api.py core\pipelines\retrieval_orchestrator.py tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py` → passed。
- `python -m ruff check core\managers\markdown_extractor.py core\managers\ingest_manager.py core\api.py core\pipelines\retrieval_orchestrator.py tests\backend\test_ingest_manager.py tests\backend\test_retrieval_orchestrator.py` → blocked，本环境未安装 `ruff`（`No module named ruff`）。
- 用户私有 PDF 手工评估 → 仅本地验证，确认 chunk 生成耗时为毫秒级且无词中断裂；不记录论文标题、正文或 chunk 预览。

---

## v0.24.9 LightRAG 暂停持久化与进度修复 (completed)

### User constraints / 约束

- LightRAG 构建保持线性单队列，同一时间只允许一个活动构建。
- 暂停状态必须持久化可恢复；重启后仍能看到 paused / pause_requested，并可从文件面板继续。
- 暂停不打断当前 LLM 请求，等待当前回答完成后停在下一次 LLM / 下一步构建前，并明确提示用户“等待当前 LLM 完成后暂停”。
- 构建进度统一放在文件面板；聊天面板不再显示构建中的阻塞弹窗。
- 进度条必须覆盖 LRAG chunks 之后的文档收尾与 finalize，不允许 6/6 chunks 后提前显示完成。

### Technical implementation path

- [x] **P1 - 构建任务持久化模型**：扩展 `graph_build_jobs` 与 SourceDocumentStore build job 契约，保存 pause_requested / paused_at / paused_seconds / progress_current / progress_total，并保留 paused job 不被启动清理改成 interrupted。技术理由：暂停状态必须可跨刷新/重启恢复。
- [x] **P2 - 后端 pause gate 与恢复**：将 pause 拆成 request 与 actual pause；当前 LLM 不取消，下一次 LLM / 文档边界 / finalize 前进入真正 paused；resume 可取消 pause_requested 或恢复 paused，并复用原 job_id。技术理由：兼顾不浪费当前 LLM 与可控暂停。
- [x] **P3 - 整体进度口径**：后端输出 progress_percent/current/total/label，进度覆盖 chunk、文档收尾、finalize。技术理由：避免 chunk 计数完成但构建仍在继续时 UI 误判 100%。
- [x] **P4 - 前端文件面板控制与聊天弹窗收敛**：FilePanel 行内提供开始 / 暂停 / 等待暂停 / 继续；ChatPanel 启动构建后关闭确认框，仅 toast 引导去文件面板。技术理由：不阻塞知识库提问面板。
- [x] **P5 - 测试、构建与收口**：补后端状态机测试，运行目标 pytest、tsc、next build、sync_frontend；通过后标记完成并追加 CHANGELOG。技术理由：覆盖持久化、暂停恢复与 UI 类型安全。

### Verification

- `python -m pytest tests\backend\test_build_hardening.py tests\backend\test_sqlite_source_store.py tests\backend\test_api.py tests\backend\test_web_server.py -q` → passed，109 passed / 330 warnings。
- `node node_modules/typescript/bin/tsc --noEmit` → passed。
- `node node_modules/next/dist/bin/next build --webpack` → passed，13 static routes。
- `python tools\sync_frontend.py` → synced 164 files to `pages/`。
- `python tools\sync_frontend.py --check` → passed。
- `python -m pytest -q` → blocked by missing optional `botocore` in this environment；`python -m pytest -q --ignore=tests/backend/test_r2_target.py` → 278 passed / 2 skipped / 2 failed，剩余失败为既有环境/平台问题：`boto3` 缺失与 Zotero Windows path separator 断言。

---

## v0.24.8 笔记面板本地标签编辑 (completed)

### User constraints / 约束

- 在前端「笔记」面板规划并落地本地文档标签编辑窗口。
- 保持整体美术水平平衡：不做重型弹窗，使用轻量行内编辑，视觉密度与现有笔记元信息区一致。
- Zotero 同步来源的标签保持只读，不允许从本系统改写。

### Technical implementation path

- [x] **P1 - NotePanel 标签编辑组件**：在文档元信息区新增轻量 `TagEditor`，普通态展示 tag chips，本地文档进入行内编辑态后可添加/删除标签；同步拆出 `DocumentMeta` 保持 `NotePanel` 回到文件大小红线内。技术理由：标签是文档上下文元数据，放在笔记面板可就地维护，不打断阅读/笔记流。
- [x] **P2 - API 接线与只读保护**：调用 `patchDocument(doc_id, { tags })` 整体替换标签；`origin=zotero` 或 `read_only=True` 时隐藏编辑入口并显示只读提示。技术理由：复用既有后端契约，并让前端约束与 service 层只读保护一致。
- [x] **P3 - i18n 与验证收口**：补齐中英文文案，运行前端类型检查与构建；通过后标记完成并追加 CHANGELOG。技术理由：保证 UI 双语完整、静态构建可交付。

### Verification

- `node node_modules/typescript/bin/tsc --noEmit` → passed，0 errors。
- `node node_modules/next/dist/bin/next build --webpack` → passed，13 static routes。
- `python tools/sync_frontend.py` → synced 164 files to `pages/`。
- `python tools/sync_frontend.py --check` → pages/ 已与 `web/frontend/out` 一致。

---

## v0.24.7 Zotero 快速配置标签式面板与本地探针 (completed)

### User constraints / 约束

- 数据流 Zotero 节点的快速配置改为像文档面板 md/pdf 那样的**标签式可切换面板**（local / server），而非下拉框。
- 本地页签提供「连接测试 + 干跑计数」探针：测本地 API 连通性并干读 zotero.sqlite 返回条目/附件数（不写库、不同步）。
- 把「立即同步 + 上次同步状态」从设置弹窗整合进快速面板。
- `sync_mode / storage_mode / linked_root / 自动同步` 收进折叠「高级」区，优化面板视觉密度。
- 自动解析目录截断 + hover 全路径。

### Technical implementation path

- [x] **P1 - 后端干跑探针**：`ZoteroSyncPipeline.probe_local_read()`（只读快照计数，server 模式跳过）；`api.probe_zotero_local()` 合并端口连通性 + 计数；`GET /api/zotero/probe`。
- [x] **P2 - 前端 API 客户端**：`lib/api.ts` 新增 `ZoteroProbeResult` 与 `probeZoteroLocal()`（含 mock）。
- [x] **P3 - 拆分独立组件**：`QuickConfigPanel` 退化为 dispatcher，Zotero 阶段交给新 `ZoteroQuickConfig.tsx`（标签切换 + 高级折叠 + 诊断行 + 同步条），共享字段原语从 `QuickConfigPanel` 导出复用，主文件降至 ~525 行（红线内）。
- [x] **P4 - 样式与 i18n**：`tokens.css` 新增 `.flow-quick-modetab/-diag/-advanced/-syncbar`；`i18n.ts` 中英补齐标签 / 探针 / 同步键。
- [x] **P5 - 验证与收口**：后端 pytest 绿（probe 单测 + web 路由 smoke）；ruff/mypy 我方新增行无新增告警；next build 通过；sync_frontend 同步到 pages/。

### Verification

- `python -m pytest tests/backend/test_zotero_sync.py tests/backend/test_web_server.py` → probe 用例 + 路由 smoke 通过。
- `npm run build` → 编译成功，TypeScript 通过，13 静态路由。
- `python tools/sync_frontend.py` → 已同步；`grep flow_quick_zotero_tab_local pages/_next` 命中。
- 已知遗留（非本次引入）：`test_lifecycle_and_cli.py::test_default_initializer_starts_without_optional_feature_packages` 因分支内 `plugin_initializer`/`requirements-additional.txt` 既有改动失败，与本计划无关。

---

## v0.24.6 数据流与 Zotero 服务器模式 (completed)

### User constraints / 约束

- Milvus Lite 升级为必装依赖并保持默认；AstrBot KB 代码保留为后端兜底，但前端选项锁定不可选。
- 数据流面板全屏展示；打开期间每 5 秒自动刷新状态，删除”重新检测”按钮并重排状态说明。
- Zotero 快速配置重做为本地 / 服务器模式：本地端口默认 23119 并显示自动解析目录；服务器使用 API key，后端加密存储且不回显明文。
- LightRAG LLM 在数据流中只读展示当前配置摘要，不再暴露 endpoint/model 自定义输入。
- 数据流按钮状态必须跟随关键环节 degraded 变化，不能继续显示绿色。
- Zotero 节点横向拉宽、控件降低高度。

### Technical implementation path

- [x] **P1 - 配置与依赖能力**：新增 Zotero access_mode 与 public config 字段；Milvus 依赖标记 required；能力探针补充 LightRAG LLM 摘要与必需依赖语义。
- [x] **P2 - Zotero server reader 与 secret 存储**：新增加密密钥存储、API key 验证接口、个人库 Web API reader，并让同步管线按 local/server 分支读取。
- [x] **P3 - 前端数据流 UI**：WorkflowModal 全屏；FlowPageContent 自动刷新并移除 recheck；TopBar 与面板共用健康状态推导；锁定 AstrBot KB。
- [x] **P4 - Zotero 与 LightRAG 快速配置**：Zotero 本地/服务器紧凑布局、提示角标、密钥保存/清除；LightRAG LLM 改为只读摘要。
- [x] **P5 - 验证与收口**：前端类型检查通过、next build 通过、sync_frontend --check 一致。

### Verification

- `npx tsc --noEmit` → 无类型错误。
- `npm run build` → 11 静态路由，exit 0。
- `python3 tools/sync_frontend.py --check` → pages/ 已与 out/ 一致。

---

## v0.24.5 主界面 UI 优化（5项）✅ (completed)

### User constraints / 约束

- 语言切换与退出登录移入设置模态框（外观 tab 改名为通用）。
- Ask 输入框还原辉光轨道效果（CSS 已存在，接入 className）。
- 数据流按键加状态脉冲 glow：红（管道未就绪）/ 绿（就绪）/ 紫（配置了 Zotero 或 R2）。
- 查询设置面板锁定当前集合不可用的检索项（低饱和度）；新增全文检索选项（仅单篇文章时启用，字符上限 60,000）。
- 遵循 CLAUDE.md 闭环协议。

### Technical implementation path

- [x] **P1 - 设置模态框重组**：SettingModal `onLogout` prop；外观→通用 tab；加退出按钮；TopBar 删除语言/退出 IconButton；layout.tsx 重新接线。
- [x] **P2 - Ask 输入框辉光**：ChatPanel composer div 接入 `.ask-card` / `.ask-card--collection` / `.ask-card--loading` className。
- [x] **P3 - 数据流按键脉冲**：globals.css 新增 3 色 pulse keyframe；TopBar 获取 capabilities + zotero config 判断状态并应用 class。
- [x] **P4 - 查询设置锁定 + 全文检索**：ChatPanel 检索项加 disabled 视觉；新增 fulltext 模式（仅 selectedDocId 存在时启用）；api.ts 类型扩展。

### Verification

- `cd web/frontend && npm run build` → 零 TS 错误（tsc --noEmit 通过）

---

## v0.24.4 Docker dev preview hardening (completed)

### User constraints / 约束

- 大部分开发环境在 Docker 中，26619 前端预览必须从 Docker 内稳定启动。
- 无论当前前后端状态如何，都能通过 `rebuild.sh` 重新构建并启动后端 `26618` 与前端 `26619`。
- 浏览器固定使用 `http://127.0.0.1:26619` 查看最新前端；Docker 固定发布 `26619`，不自动换端口。
- devcontainer 位于仓库外 `D:\dev-workspace\.devcontainer`，本轮按用户明确批准修改。

### Technical implementation path

- [x] **P0 - 治理记录**：新增本计划条目。技术理由：遵循先 TODO 后改代码的项目闭环。
- [x] **P1 - devcontainer Node 与端口修复**：将 devcontainer NodeSource 升级到 20.x，并发布 `26619:26619`、`26618:26618`，保留 `6186:6185`。技术理由：`next@16.2.6` 要求 Node `>=20.9.0`，且 Docker 层端口发布比编辑器转发稳定。
- [x] **P2 - rebuild.sh Docker 化加固**：启动前校验 Node 版本；Node 或 lockfile 变化时自动刷新依赖；自动安装轻量后端 `requirements.txt`；后端监听 `0.0.0.0:26618`；前端监听 `0.0.0.0:26619`；健康检查统一使用 `127.0.0.1`。技术理由：让脚本在容器内自诊断、可重入，并避免 `localhost` 命中宿主机 IPv6 旧进程。
- [x] **P3 - 重建后端到端验证**：重建 devcontainer 后运行 Next build、静态同步校验、`bash rebuild.sh` 与宿主机 26619/26618 curl。技术理由：验证 Docker 内 rebuild 可稳定拉起前后端，并能从宿主机固定端口访问。

### Verification

- `docker exec gifted_williams bash -lc 'cd /root/Astrbot_Knowledge_Repository && chmod +x rebuild.sh && bash -n rebuild.sh && bash rebuild.sh; code=$?; echo REBUILD_EXIT:$code; exit 0'` -> passed for syntax; expected guard failure with Node `18.20.8`, `REBUILD_EXIT:1`
- `docker inspect gifted_williams --format "{{json .NetworkSettings.Ports}}"` -> current old container only publishes `6186:6185`; `26619:26619` and `26618:26618` require devcontainer rebuild
- `Get-Content -Encoding Byte -TotalCount 8 D:\dev-workspace\.devcontainer\Dockerfile` -> starts with `46 52 4F 4D`, UTF-8 no BOM
- `docker buildx build --check -f D:\dev-workspace\.devcontainer\Dockerfile D:\dev-workspace\.devcontainer` -> passed, Dockerfile parse check complete
- `netstat -ano -p tcp | Select-String ':26619'` -> found stale host `node` PID `30940`; `Stop-Process -Id 30940 -Force` released port `26619`
- `docker rm 316ddf1cea6c` -> removed failed Created devcontainer from previous port bind error
- `docker run --rm -p 6186:6185 -p 26619:26619 -p 26618:26618 --entrypoint /bin/true vsc-dev-workspace-558f8f1763b9de33a57c7ce734c75d008cd0fdc29b369b381d19ee4d1c8cc780` -> passed, fixed host ports are bindable
- `bash rebuild.sh` -> first Node 20 run reached backend startup, then failed because `aiohttp` was missing from fresh devcontainer Python site-packages; `rebuild.sh` now installs `requirements.txt` when `aiohttp` is absent
- Manual Next dev restart without `NEXT_TEST_WASM=1` -> `http://127.0.0.1:26619/` returned `200`; `.next/dev/routes-manifest.json` and `.next/dev/server/middleware-manifest.json` generated
- `bash rebuild.sh` -> passed; Node `20.20.2` OK, Python deps OK, Next build generated 11 static routes, synced 163 files, backend `26618` ready, frontend `26619` ready
- `python3 tools/sync_frontend.py --check` -> passed, `pages/` matches `web/frontend/out`
- `curl.exe -I --max-time 10 http://127.0.0.1:26619/` -> `200 OK`, `X-Powered-By: Next.js`
- `curl.exe -I --max-time 10 http://127.0.0.1:26618/` -> `200 OK`, `Server: Python/3.12 aiohttp/3.14.1`

---

## v0.24.3 Terminal logs panel (completed)

### User constraints / 约束

- 将设置页和侧边栏入口的”终端日志”从运行目录浏览器改为 terminal 风格日志查看器。
- 本轮只显示日志，不保留运行目录浏览功能，不实现命令输入或 shell 执行。
- 复用现有 `/api/logs`，不新增后端 API；保持 UI 风格与现有 DS token、弹窗、侧边栏一致。

### Technical implementation path

- [x] **P1 - 前端日志面板重构**：`TerminalPanel` 改为读取 `getLogs()` 并渲染日志流，支持刷新、清屏、自动滚动、加载/空/错误状态。技术理由：让”终端日志”文案与实际行为一致，并复用已有日志缓冲接口。
- [x] **P2 - 入口文案与 i18n 对齐**：补齐中英文日志面板文案，移除侧边栏入口中的”运行目录”语义。技术理由：避免 UI 误导，同时保持中英文界面一致。
- [x] **P3 - 验证与收尾**：运行前端类型检查、Next build、同步 `pages/` 与同步校验，测试通过后标记完成并追加 `CHANGELOG.md`。技术理由：保证源码与静态产物一致。

### Verification

- `node node_modules/typescript/bin/tsc --noEmit` -> passed, 0 errors
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 11 static routes
- `python tools/sync_frontend.py` -> synced 161 files to `pages/`
- `python tools/sync_frontend.py --check` -> passed

---

## v0.24.2 LightRAG 构建加固 (completed)

### User constraints / 约束

- 重启后端时，正在构建的 LightRAG 任务须被正确打断并将状态持久化为 interrupted，下次启动后前端可一键继续构建。
- 同一集合不允许并发构建，前端发起第二次构建时须收到错误。
- 构建期间删除/插入文档不能与正在写入的 LightRAG workspace 产生竞争。
- 「继续构建」入口放在 FilePanel 文件界面的 LightRAG 集合区——紧跟 SectionHead 之下、第一条集合行之上；同一位置也展示实时进度条。
- 遵循 Plan-First；执行前已更新 TODO，测试通过后才勾选完成并追加 CHANGELOG。

### Technical implementation path

- [x] **P0 - 治理记录**：新增本计划条目。
- [x] **P1 - 并发构建守卫**：`core/api.py:build_graph()` 在 `create_task` 前检查同集合是否已有 queued/running 任务，有则抛 RuntimeError（HTTP 409）。
- [x] **P2 - 任务句柄 + CancelledError 处理**：新增 `_build_tasks: dict[str, asyncio.Task]`；`create_task` 后保存句柄；`_run_lightrag_build_job()` 在 `except Exception` 前插入 `except asyncio.CancelledError` 将 status 设为 interrupted 后 re-raise；新增 `cancel_build_tasks()` 方法；`plugin_initializer.py:teardown()` 调用它。
- [x] **P3 - workspace 级 asyncio.Lock**：`core/lightrag_core.py:LightRAGCoreRegistry` 新增 `_collection_locks`；`insert_document`/`delete_doc`/`reset_workspace` 均用 per-collection lock 串行化。
- [x] **P4 - 前端 interrupted UI**：`FilePanel.tsx` 新增 `ActiveBuildCard` 内部组件（活跃进度 + 中断恢复两态）；置于 LightRAG SectionHead 后、集合列表前；移除 per-collection `BuildCard`；`lib/i18n.ts` 新增 `file_build_interrupted`/`file_build_resume`/`file_build_queued`。
- [x] **P5 - 测试与验证**：新增 `tests/backend/test_build_hardening.py`（并发守卫 + CancelledError）；`pytest -q` 全绿；`tsc --noEmit` 0 错误；`next build` 13 routes；同步 `pages/`。
- [x] **P6 - 收尾记录**：标完成，追加 CHANGELOG。

### Verification

- `python -m pytest -q` → 275 passed
- `node node_modules/typescript/bin/tsc --noEmit` → 0 errors
- `node node_modules/next/dist/bin/next build --webpack` → 13 static routes
- `python tools/sync_frontend.py` → 161 files synced to `pages/`
- `python tools/sync_frontend.py --check` → pages/ 已与 web/frontend/out 一致

---

## v0.24.0 Scoped notes + chat lock persistence (completed)

### User constraints / 约束

- 每一篇文章 / 每一个 collection 只要在右侧上下文中被选中，都需要持久化，重新打开该层级时应恢复对应面板状态。
- 文档笔记要和 Zotero note 形态对齐，便于后续接入 Zotero；当前仍不向 Zotero 写回。
- 笔记必须成为 R2 备份的一部分，优先复用现有 SQLite 快照备份路径。
- 遵循 Plan-First；执行前先更新 TODO，测试通过后才能标完成并追加 CHANGELOG。

### Technical implementation path

- [x] **P0 - 治理记录与范围确认**：新增本计划条目，限定改动为 notes/chat lock/UI scope state 的持久化链路、前端接线、测试与闭环文档。
- [x] **P1 - 持久化契约与迁移**：新增 Zotero-shaped `ScopedNote` 与 `ConsoleScopeState` domain/仓储契约，追加 SQLite 迁移；给 `chat_history` 增加 `locked` 字段。技术理由：把用户笔记、锁定回答和右侧选择状态放入同一 SQLite，天然纳入 R2 DB 快照。
- [x] **P2 - Repository 实现与 API 门面**：补齐 SQLite / memory 实现，并在 `KnowledgeRepositoryApi` 暴露 list/create/update notes、collection notes、chat lock、scope state 方法。技术理由：保持 web 层只做 HTTP 翻译，业务语义沉到门面和仓储契约。
- [x] **P3 - Web 路由接线**：实现 `GET|POST|PATCH /api/documents/{doc_id}/notes`、collection notes、`PATCH /api/chat/history/{convId}/messages/{msgIdx}/lock` 与 scope state 路由。技术理由：补齐新版前端已预留的缺口，并为 collection 层级和 UI state 提供稳定接口。
- [x] **P4 - 前端持久化接线**：NotePanel 使用类型化 API 读取/创建/更新笔记；ChatPanel 调用 lock API 并加载 `locked`；ConsoleContext 按 scope 恢复/保存右侧状态。技术理由：移除 localStorage 作为主存储，仅保留 mock/offline fallback。
- [x] **P5 - R2 备份与回归验证**：补充后端契约、web 路由和 SQLite 快照恢复测试；运行前端类型检查/构建。技术理由：验证 notes/locks/state 确实随 `knowledge_repository.db` 快照进入 R2 备份。
- [x] **P6 - 收尾记录**：测试通过后将本计划标完成，并在 `CHANGELOG.md` 顶部追加变更记录。

### Verification

- `python -m pytest tests/backend/test_source_store.py tests/backend/test_sqlite_source_store.py tests/backend/test_api.py tests/backend/test_web_server.py tests/backend/test_sync_pipeline.py -q` -> passed, 110 passed / 1 skipped（本机缺少可选 `boto3`/`botocore`，R2 restore mock 测试跳过）。
- `node node_modules/typescript/bin/tsc --noEmit` -> passed。
- `node node_modules/next/dist/bin/next build --webpack` -> passed，13 static routes generated。
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`。
- `python tools/sync_frontend.py --check` -> passed。

---

## v0.23.9 Frontend i18n panel alignment (completed)

### User constraints / 约束

- 修复前端语言切换后面板内中英文混用问题，尤其是中文界面下左侧 File 栏仍出现 Collection 等英文标签。
- 重新梳理中英文映射，保证面板上的语言一致；技术/产品专名如 LightRAG、Milvus、Zotero、R2 可保留英文。
- 对齐三栏控制台布局，保持面板标题、面包屑、操作按钮和内容区基线一致。
- 遵循先 TODO 后修；测试通过后才勾选完成，收尾追加 `CHANGELOG.md`。

### Technical implementation path

- [x] **P0 - 治理记录与范围确认**：新增本计划条目，限定改动范围为 `web/frontend/` 源码、构建同步产物和闭环文档。
- [x] **P1 - i18n 字典重分组**：扩展 `web/frontend/lib/i18n.ts`，新增三段控制台、面板标题、操作提示、空状态和构建状态相关键值，中文界面使用中文术语，英文界面使用英文术语。
- [x] **P2 - 面板硬编码文案替换**：改造 `FilePanel`、`DocumentsPanel`、`ChatPanel`、`NotePanel`、`TopBar`、`SettingModal`、`WorkflowModal`，将可见 UI 文案统一走 `useI18n()`。
- [x] **P3 - 布局对齐微调**：收敛 `Panel` 标题/面包屑/action 区域、三栏容器和侧栏分区标题的对齐与文本溢出策略，避免切换语言后错位。
- [x] **P4 - 验证与发布记录**：运行前端类型检查、Next build、同步 `pages/`，验证通过后更新本计划与 `CHANGELOG.md`。

### Verification

- `node node_modules/typescript/bin/tsc --noEmit` -> passed
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`
- `python tools/sync_frontend.py --check` -> passed
- Browser smoke on `http://localhost:26619/?mock=true` -> passed; zh/en toggle verified, Chinese panel labels show 文件/本地集合/LightRAG 集合/文档/问答, three panel headers align at 38px height, no browser console errors.

---

## v0.23.8 PDF reader + Zotero read-only API bridge (completed)

### User constraints / 约束

- Zotero 交互只读，只调用 Local API `GET`；不向 Zotero 写回 notes、annotations 或 metadata。
- 先打通 PDF reader 相关前后端接口，再替换当前 iframe 预览。
- 遵循先 TODO 后修；测试通过后才勾选完成，收尾追加 `CHANGELOG.md`。

### Technical implementation path

- [x] **P1 - 文档阅读接口补齐**：实现 `GET /api/documents/{doc_id}/content?format=md`、`GET /api/documents/{doc_id}/chunks`，并为 `/raw` 增加 `?disposition=inline`，默认下载行为保持兼容。
- [x] **P2 - Zotero Local API 只读桥接**：扩展 `core/adapters/zotero/local_api.py`，提供 status/schema、`list_items(itemType)`、`get_item(key)`、`get_file_view_url(key)` 只读 helper；`/annotations` 以文档 `attachment_key` 匹配 Zotero annotation `parentItem`。
- [x] **P3 - PDF.js 阅读面板**：修正前端 API wire shape，使用 `pdfjs-dist` 渲染 `/raw?disposition=inline`，提供页码、缩放、fit width、loading/error、annotation 点击跳页。
- [x] **P4 - NotePanel 边界保持**：Zotero notes 仅只读展示预留；本轮不新增 notes 持久化迁移，保留 localStorage fallback。
- [x] **P5 - 验证与发布记录**：补后端路由/解析测试、前端类型检查和构建，构建通过后同步 `pages/` 并追加 `CHANGELOG.md`。

### Verification

- `python -m pytest tests/backend/test_web_server.py tests/backend/test_zotero_local_api.py -q` -> passed, 46 passed
- `node node_modules/typescript/bin/tsc --noEmit` -> passed
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 163 files to `pages/`
- `python tools/sync_frontend.py --check` -> passed
- Browser smoke -> skipped; Browser plugin control tool unavailable in current tool discovery.

---

## v0.23.7 前端冗余组件清理 (completed)

### User constraints / 约束

- 仅删除零引用的旧 `ui/` 组件；保留仍在使用的 `Toast`、`TerminalPanel`、`PerfPanel`。
- 不删除 `tests/mocks/` 下的两个脚本（待后续重构一并处理）。
- 不修改 `pages/` 构建产物。

### Technical implementation path

- [x] **P1 — 删除 5 个冗余 `ui/` 组件**：`Btn.tsx`、`HelpTip.tsx`、`Select.tsx`、`Tag.tsx`、`Toggle.tsx`（均被 `ds/` 版取代，零 import 验证）。
- [x] **P2 — 删除空占位目录 `core/repository/graph_store/`**：三个实现文件在 commit `ac05dfe` 中已删，仅剩空壳，一并清除。
- [x] **P3 — 更新 TODO.md + CHANGELOG.md**。

### Verification

- `grep -rn "ui/Btn\|ui/HelpTip\|ui/Select\|ui/Tag\|ui/Toggle" web/frontend/` → 0 matches
- `ls core/repository/graph_store/` → directory not found

---

## v0.23.6 Flow 面板按钮行为调整 (completed)

### User constraints / 约束

- "进入同步设置"按钮（sync 节点、zotero 节点）跳转到设置页 `/settings`，而非同步页 `/sync`。
- "进入问答界面"按钮（ask 节点）改为关闭 WorkflowModal（回主页），而非导航到 `/ask`。
- 不改变图节点/连线逻辑；不修改 `pages/` 构建产物。

### Technical implementation path

- [x] **P0 — 更新 TODO.md**：修正三个计划标题 `(in progress)` → `(completed)`；新增本条目。
- [x] **P1 — model.ts href 更新**：`zotero.link.href` 与 `sync.link.href` 由 `"/sync"` 改为 `"/settings"`。
- [x] **P2 — onClose 链路传递**：`WorkflowModal` → `FlowPageContent` → `FlowDiagram` → `FlowNode`；ask 节点在有 `onClose` 时渲染 `<button>` 而非 `<Link>`，确保 standalone `/flow` 页也不报错。
- [x] **P3 — 验证与构建**：`tsc --noEmit` + `next build --webpack` + `sync_frontend.py`。

### Verification

- `node node_modules/typescript/bin/tsc --noEmit` -> passed, 0 errors
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 158 files to pages/

## v0.23.5 Fix frontend build warnings and dev server startup crash (completed)

### User constraints / 约束
- 修复 `npm run build` 的 `rewrites` 警告。
- 修复 `npm run dev` 启动后可能出现的 `missing required error components` 白屏循环刷新问题。
- 不影响主程序代码。

### Technical implementation path
- [x] **P1 - 调整配置与脚本**：修改 `web/frontend/next.config.ts` 避免导出时注入 rewrites；修改 `web/frontend/package.json` 在开发与构建命令执行前自动删除 `.next` 缓存文件夹。
- [x] **P2 - 验证**：运行 `npm run build` 和 `npm run dev`，并使用 `python tools/sync_frontend.py` 验证同步。

### Verification
- `npm run build` -> passed without warnings
- `npm run dev` -> passed, server ready and cache cleared
- `python tools/sync_frontend.py` -> synced 145 files successfully

## v0.23.4 Terminal 设置页嵌入面板修复 (completed)

### User constraints / 约束

- 设置弹窗的”终端日志”页不能只显示一个”运行目录”按钮并再弹出全局浮层；应直接在设置弹窗内容区展示运行目录面板。
- 侧边栏 Terminal 入口继续保留放大的浮层形态。
- 不新增后端 API，不删除文件。

### Technical implementation path

- [x] **P1 - TerminalPanel 双模式**：为 `TerminalPanel` 增加 `variant`，默认 `floating` 兼容 Rail；新增 `embedded` 模式直接渲染面板内容并自动加载系统信息与文件列表。
- [x] **P2 - SettingModal 嵌入终端面板**：设置页 terminal tab 使用 `variant=”embedded”`，内容区补齐 `minHeight: 0` 与条件 padding，避免空白区域和二次浮层。
- [x] **P3 - 验证与同步**：运行前端类型检查、Next build、同步 `pages/`，并确认 `localhost:26619` 可查看最新前端。

### Verification

- `node node_modules/typescript/bin/tsc --noEmit` -> passed, 0 errors
- `node node_modules/next/dist/bin/next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 167 files to pages/
- `python tools/sync_frontend.py --check` -> passed

## v0.23.3 Workflow 样式加载修复 (completed)

### User constraints / 约束

- Workflow 面板打开后仍然显示为原生白底文本，需恢复 FlowDiagram 节点、画布、图例、缩放控件等完整样式。
- 修复后重新构建，并确保 `localhost:26619` 可查看最新前端。
- 不修改 `components/flow/` 内部图节点/连线逻辑。

### Technical implementation path

- [x] **P1 - 恢复 Flow 专用 CSS 加载**：在 `app/globals.css` 中引入 `styles/tokens.css`，并置于 `ds-tokens.css` 之前，避免旧主题变量覆盖新 DS 主题，同时恢复 `.flow-*` class 与 `--flow-*` 变量。
- [x] **P2 - 构建与本地预览**：运行 TypeScript 检查、Next build、同步 `pages/`，并重启/确认 26619 端口预览服务。

### Verification

- `node .\node_modules\typescript\bin\tsc --noEmit` -> passed
- `node .\node_modules\next\dist\bin\next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 160 files to `pages/`
- `python tools/sync_frontend.py --check` -> passed
- `rg "flow-topo-page|flow-viewport|flow-node" .\web\frontend\out\_next\static\css` -> passed, Flow CSS present in built bundle
- `http://localhost:26619` -> HTTP 200, serving Next dev preview on port 26619

## v0.23.2 UI 修复：WorkflowModal 数据流 + Terminal 浮层 (completed)

### User constraints / 约束

- 修复数据流弹窗只显示标题、说明和图例的问题，FlowDiagram 必须在 WorkflowModal 内完整显示并可拖拽/缩放。
- Terminal 保留浮层形态，但从 300px 小弹窗放大为接近面板的运行目录视图；侧边栏 Terminal 直接打开浮层，设置页入口继续可用。
- 本轮只输出前端冗余候选清单，不删除文件；不手改 `pages/` 构建产物，不修改 `components/flow/` 内部图节点/连线逻辑。

### Technical implementation path

- [x] **P1 - WorkflowModal flex 高度链路修复**：补齐 modal content、`FlowPageContent` 根节点与 `.flow-viewport` 的 `flex: 1`、`minHeight: 0`、`overflow: hidden`，避免图表 viewport 被压成 0 高。
- [x] **P2 - Terminal 浮层放大与侧边栏触发**：扩展 `TerminalPanel` 的触发文案/图标 props，修正 portal 内点击关闭判断，放大浮层尺寸并优化系统信息两列布局；`Rail` 直接使用该组件替代 `/terminal` redirect 链接。
- [x] **P3 - 冗余清单与验证**：运行前端类型检查、构建和同步命令；输出 legacy/template/未引用资源与旧 UI 组件候选清单，不执行删除。

### Verification

- `node .\node_modules\typescript\bin\tsc --noEmit` -> passed
- `node .\node_modules\next\dist\bin\next build --webpack` -> passed, 13 static routes generated
- `python tools/sync_frontend.py` -> synced 160 files to `pages/`

## v0.23.1 UI 修复：WorkflowModal 布局 + Local Collection 删除按钮 (completed)

### User constraints / 约束

- WorkflowModal（数据流界面）目前打开后不可用（布局问题）。
- Local Collection 选中后右侧应有删除按钮，点击弹出确认对话框（需用户再次输入 collection 名称才能删除）。
- 保持整体设计风格一致；不修改 `pages/`；不修改 `components/flow/` 文件。

### Technical implementation path

- [x] **P1 — 修复 WorkflowModal 布局问题**
  `.flow-topo-page` 使用 `height: 100vh`，在 Modal 内嵌时溢出整个 modal 容器导致无法交互。
  修复：在 `FlowPageContent` 改用 `height: 100%` 替代 `height: 100vh`，使其作为 modal flex 子元素正确撑满。
  涉及文件：`web/frontend/components/panels/FlowPageContent.tsx`（行内 style 覆盖）或修改 CSS class。

- [x] **P2 — Local Collection 删除按钮 + 确认弹窗**
  在 `FilePanel` Local Collection section 中，选中的 collection 行右侧显示删除 `IconButton`（`trash` 图标，`var(--danger)` 色，hover 才可见）。
  点击后弹出内联确认对话框：显示警告文案 + 输入框（用户需完整输入 collection name）+ 取消/确认删除按钮。
  确认后调用 `deleteCollection(name)`，成功后刷新列表并清空 `selectedCollection`。
  涉及文件：`web/frontend/components/panels/FilePanel.tsx`。

### Verification

- `npx tsc --noEmit` → 0 source errors
- `npx next build` → Compiled successfully, 13 static pages generated
- `python tools/sync_frontend.py` → 同步 144 个文件到 `pages/`
- WorkflowModal 打开后 FlowDiagram 正常渲染、可拖拽/交互 ✓
- Local Collection 选中后出现删除按钮，输入错误名称无法删除，输入正确后成功删除并刷新列表 ✓

## v0.23.0 三段式控制台 UI 重构——后端能力缺口 (completed)

### User constraints / 约束

- 新三段式控制台（File | Documents | Chat）已在前端落地，部分功能依赖后端端口尚未实现。
- 前端已用 localStorage 或 fetch 优雅降级（501 → 忽略），本节记录完整实现所需的 6 项后端能力。
- 不修改 `pages/`（构建产物），不修改 `components/flow/` 文件。

### Technical implementation path

- [x] **P1 — `GET /api/documents/{doc_id}/content?format=md|pdf`**
  阅读视图内容流（DocumentsPanel ReadingView 占位"加载中"）。
  降级状态：前端显示"详细内容加载中"占位。
  规格：`format=md` 返回 Markdown 文本；`format=pdf` 以 `application/pdf` 流返回文件。
  已实现：`web/server.py` 中已注册路由，`core/api.py` 中已实现相应方法。

- [x] **P2 — `GET|POST|PATCH /api/documents/{doc_id}/notes`**
  文档本地笔记 CRUD（NotePanel 与 ChatPanel "Add to Linked Notes" 按钮）。
  降级状态：前端已降级到 `localStorage`（key = `kr_notes_doc_{doc_id}`）。
  规格：`GET` 返回 `DocumentNote[]`；`POST { content }` 新建；`PATCH /{note_id} { content }` 更新。
  已实现：v0.24.0 引入 `ScopedNote` + migration 013，同时支持 `/api/collections/{name}/notes`（`web/server.py`, `core/api.py`）。

- [x] **P3 — `GET /api/documents/{doc_id}/annotations`**
  Zotero 注释高亮同步（NotePanel Annotations 分区）。
  降级状态：显示"连接 Zotero 后同步注释"占位 + 五色图例。
  规格：返回 `ZoteroAnnotation[]`（id, text, comment?, color, page?）。
  已实现：`web/server.py` 中已注册路由，桥接 `core/adapters/zotero/local_api.py`。

- [x] **P4 — `GET /api/documents/{doc_id}/chunks`**
  阅读视图有序分块列表（DocumentsPanel ReadingView 分块原文区）。
  降级状态：显示"详细内容加载中"占位（当前 `chunks=[]`）。
  规格：返回 `{ chunk_id, ordinal, page?, text }[]`，按 `ordinal` 升序排列。
  已实现：`web/server.py` 中已注册路由，`core/api.py` 中已实现相应方法。

- [x] **P5 — `PATCH /api/chat/history/{conv_id}/messages/{idx}/lock`**
  锁定回答持久化（ChatPanel "锁定回答" 按钮服务端持久化）。
  降级状态：前端已降级到 `message.pinned` React 状态（刷新后丢失）。
  规格：body `{ "locked": true|false }`；服务端标记 `locked=true`，`clear_chat_history` 支持 `preserve_locked=true` 跳过。
  已实现：v0.24.0 引入 migration 014（`locked/locked_at/updated_at`），`set_chat_message_locked()` 方法（`web/server.py`, `core/api.py`）。

- [x] **P6 — GraphBuildJob 响应新增 `type` 字段**
  区分 LightRAG 图谱构建 job 与 Zotero 同步进度（FilePanel 进度条来源判断）。
  降级状态：FilePanel BuildCard 当前对所有 job 类型显示相同进度条。
  规格：`type: "lightrag_build" | "zotero_sync" | "milvus_rebuild"` 字段加入 `GraphBuildJob` 响应。

### Verification

- 每项完成后：前端相关占位替换为真实 API 调用；`npx tsc --noEmit` 通过；`python -m pytest` 通过。

## v0.22.2 Milvus index coverage status and rebuild retry (completed)

### User constraints / 约束

- Flow 不能只因为 Milvus 依赖可用就显示完全 ready；必须反映索引覆盖、兼容性文件、collection 与待重建文档状态。
- 前端需要补回手动“重建 Milvus 索引”入口，复用现有 `/api/documents/rebuild-index`。
- Milvus 自动索引失败时后端需要有限重试；全部失败后才标记 `needs_reindex=1` 并把原因暴露给前端。
- 不在启动时自动全量重建，避免重启后意外消耗 embedding 资源；不手改 `pages/` 构建产物。

### Technical implementation path

- [x] **Phase 1 - Runtime Milvus health**：在 capabilities 响应中叠加运行态 Milvus 覆盖信息，包括 compatible、rebuild_required、pending_reindex_count、document_count、chunk_count 与 reason。技术理由：`vector_store.status=ready` 应表示当前可检索，而不是仅表示依赖已安装。
- [x] **Phase 2 - Milvus indexing retry helper**：抽出统一 retry helper，覆盖 embedding 生成与 Milvus upsert，并用于上传自动索引、待重建索引和全量重建。技术理由：本地模型加载、Milvus Lite 状态和 gRPC 瞬态异常都需要在单次任务内短退避重试。
- [x] **Phase 3 - Frontend rebuild entry**：Flow Milvus 节点与 Documents 工具栏增加重建按钮，调用既有 rebuild API，运行中禁用重复提交，成功后刷新 capabilities/documents/pending 状态。技术理由：当自动索引因兼容性或瞬态失败留下待重建文档时，用户需要明确入口修复覆盖。
- [x] **Phase 4 - Verification and release notes**：补充后端与前端测试，验证 capabilities degraded、retry 成功/失败、重建按钮调用与状态刷新；测试通过后更新 CHANGELOG。技术理由：`[x]` 只代表代码落地且相关验证已通过。

### Verification

- `python -m pytest tests/backend/test_api.py tests/backend/test_web_server.py tests/backend/test_capabilities.py -q` → 87 passed, 281 warnings（既有 aiohttp AppKey/cookie warning）。
- `node node_modules/eslint/bin/eslint.js 'app/(console)/flow/page.tsx' 'app/(console)/documents/page.tsx' components/flow/FlowDiagram.tsx components/flow/FlowNode.tsx components/flow/model.ts lib/api.ts lib/i18n.ts` → 0 errors, 3 existing Documents page warnings。
- `node node_modules/next/dist/bin/next build --webpack` → 编译阶段通过；TypeScript/worker 阶段因当前 Windows WASM SWC 环境报 `invalid type: unit value`，未同步 `pages/`。

## v0.22.1 PDF 清洗核心依赖自动安装 (completed)

### User constraints / 约束

- PDF 清洗需要 `pymupdf4llm>=0.0.17,<0.1.0` 与 `PyMuPDF>=1.24,<2.0`。
- 依赖必须直接列入插件自动安装的 requirements，而不是要求用户手动安装 additional requirements。
- 不触碰无关用户改动；不手改 `pages/` 构建产物。

### Technical implementation path

- [x] **Phase 1 — 自动安装入口修正**：将 PyMuPDF4LLM 与 PyMuPDF pin 收敛到根 `requirements.txt`，并从 `requirements-additional.txt` 移除重复声明。技术理由：AstrBot 插件安装器自动安装根 requirements，additional 文件只用于真正可选的大型运行时。
- [x] **Phase 2 — 能力清单语义修正**：从可选依赖安装白名单移除 `pdf_extract`，ingest 环节只报告核心依赖就绪态。技术理由：PDF 清洗已是核心能力，不能继续显示为需要手动安装的可选功能。
- [x] **Phase 3 — 回归验证与收尾**：更新相关测试断言并运行聚焦测试；测试通过后追加 CHANGELOG。技术理由：依赖清单属于安装契约，必须用 API/能力测试锁定。

### Verification

- `python -m pytest tests/backend/test_capabilities.py tests/backend/test_config.py -q` → 27 passed
- `python -m pip install -r requirements.txt` → 安装 `PyMuPDF-1.27.2.3` 与 `pymupdf4llm-0.0.27` 成功
- `python -m pytest tests/backend/test_capabilities.py tests/backend/test_config.py tests/backend/test_web_server.py -q` → 68 passed, 281 warnings（既有 aiohttp AppKey/cookie warning）
- `python -m ruff check core/capabilities.py core/managers/markdown_extractor.py tests/backend/test_capabilities.py tests/backend/test_web_server.py` → 未执行：当前 Python 环境未安装 `ruff`

## v0.22.0 Zotero 镜像 + PyMuPDF4LLM 清洗内核 + 制品包数据模型 + 作用域检索 (completed)

### User constraints / 约束

- 引入 Zotero 单向 Pull 同步：Zotero 为上游事实源，镜像 items/collections/tags/attachments；存储格式 push-ready（未来双向），本轮不做 push/note 写回。
- PyMuPDF4LLM 为 **pinned 依赖**（不 vendor 源码，规避 AGPL 分发义务与版本耦合），**完全替换 fitz 手写抽取**；所有后端适配（Ask 原文展示、chunk 源文本、LightRAG 原文）改读 clean.md。
- 制品包模型：`doc_id = document_id = <library_id>_<item_key>_<attachment_key>`（无 UUID 兼容层，插件未发行）；每文档一目录 `data_dir/library/<document_id>/{original.pdf,clean.md,pages.json,meta.json}`，整体纳入 R2 备份。
- 本地上传也以 Zotero 格式存入镜像库（`LOCAL` 库 + 合成 key，`origin=local` 可编辑）；Zotero 同步来源 `origin=zotero` 在文档系统中**只读**，repository/service 层强制。
- 元数据一等字段：creators、year/venue、item_type+DOI/URL、abstract（raw json 整体存 meta.json）。
- 作用域检索 item/collection/tag/library：orchestrator 层硬过滤覆盖所有通道（Milvus/SQLite lexical/LightRAG），先满足 allowed_document_ids 再 rerank/RRF。
- 不手改 `pages/` 构建产物；迁移只追加幂等；CHANGELOG 中文。

### Technical implementation path

- [x] **Phase 0 — pinned 依赖 + 治理**：requirements-additional 固定 `pymupdf4llm`/`PyMuPDF`；`core/capabilities.py` 登记 `pdf_extract` 依赖与 ingest 环节 PDF 清洗就绪态；`metadata.yaml` → v0.22.0。
- [x] **Phase 1 — Zotero 镜像数据模型**：domain 新增 Zotero* 值对象 + `DocumentOrigin` + `PageChunk`；SourceDocument 改造（document_id/library_id/origin/read_only/markdown_rel/pages_rel/converter）；migrations 009-011（zotero 镜像表 + documents 加列 + page_chunks + collections origin）；store 接口/sqlite/memory 同步实现 + 接口对换测试（test_zotero_mirror.py 16 passed）。
- [x] **Phase 2 — PyMuPDF4LLM 清洗内核**：新增 `markdown_extractor.py` 产出 clean.md + pages.json（LF 归一化 + 写盘后 str 字符 offset 不变量）；重写 IngestManager 切块于 clean.md 并落制品包（library/<document_id>/）；删除 fitz 手写路径；`_extract_raw_doc_text` 改读 clean.md；删除文档级联清制品包目录。test_ingest_manager.py offset 不变量通过，全套 232 passed。
- [x] **Phase 3 — Zotero 客户端 + 单向 Pull**：`core/adapters/zotero/`（sqlite_reader 主路径 / local_api 状态探测 / paths + linked 探针）；`zotero_sync_pipeline.py`（三种 sync_mode strict/conservative/archive + 两种 storage_mode managed/linked + detached 生命态 + 增量）；`ZoteroSyncConfig` + `_conf_schema.json` + CONFIG_KEY_POLICY；migration 012（lifecycle_state/last_synced_at）；api 门面 `sync_zotero_pull/get_zotero_config/get_zotero_sync_status` + 索引/LRAG 回调；组合根注入 + 重启/定时自动同步；web 路由 `/api/zotero/config`、`/api/sync/zotero/pull|status`。test_zotero_sync.py（reader + 3 模式 + linked，6 passed）+ test_zotero_routes（route）。全套 239 passed。
- [x] **Phase 4 — 作用域检索**：`resolve_scope`（item/collection 后代/tag/library）+ orchestrator 硬过滤契约覆盖所有通道（Milvus/SQLite lexical/LightRAG）；item/tag 子作用域禁用图谱防越界；ask/search_kb + web 路由接受 scope。test_retrieval_scope.py 8 passed。
- [x] **Phase 5 — 后端读写边界 + provenance**：service 层 `ReadOnlyError` 强制（delete/classify/delete_collection），web 403；sources 携带 document_id/pages/zotero URI/引用；文档序列化新增来源/只读/生命态/last_synced_at/Milvus 覆盖/LRAG/zotero_meta。test_readonly_enforcement.py 4 passed。
- [x] **Phase 6 — 前端**：api.ts 类型 + zotero 函数；documents 来源徽章/只读/三指示/文献元数据；sync 页 Zotero 状态卡 + 同步按钮；flow 最左端 Zotero 来源节点。tsc 通过。
- [x] **Phase 7 — R2 备份纳入制品包**：sync_pipeline 上传 clean.md/pages.json/meta.json 至 `artifacts/<collection>/<doc_id>/`。test_sync_pipeline.py 制品包备份测试通过。
- [x] **Phase 8 — 测试 + 验证 + 收尾**：全套测试 + ruff + mypy + 前端构建 + sync_frontend + CHANGELOG。

### Verification

- `python -m pytest -q` → 252 passed
- `python -m ruff check . && python -m mypy` → All checks passed / Success（domain 严格域无误）
- `cd web/frontend && npx tsc --noEmit` → passed
- `npx -y node@20 node_modules/next/dist/bin/next build` → passed，13 static pages generated
- `python tools/sync_frontend.py` → 150 文件同步至 `pages/`

## v0.21.0 LRAG recall bug fix, build persistence & floating widget (completed)

### User constraints / 约束

- 修复 LRAG 召回后提示"未召回任何内容/构建失败"的严重 bug，保证构建成本不被浪费。
- LRAG 构建切出界面不能中断，需在右下角常驻浮窗，支持实时暂停与继续。
- LRAG 构建需要断点重连机制，重启后自动识别中断任务并从断点续建。
- 新建专用 graph_build_jobs 持久化表，保障计算资源不被重复消耗。
- 不手动修改 `pages/` 构建产物；CHANGELOG 使用中文。

### Technical implementation path

- [x] **Phase 1 — 修复 LRAG 召回 bug**：删除 `retrieve_lightrag_context()` 中逐文档状态循环（`retrieval_orchestrator.py:165–175`）。技术理由：LightRAG 是全图查询，不依赖单文档状态；现有 `has_workspace()` 与 `is_lightrag_compatible()` 已足够把关；部分失败后仍可查询已构建内容。补充 partial_failure 后仍可查询的测试。
- [x] **Phase 2 — 构建浮窗 + 暂停/继续**：后端 `BuildJob` 增加 `paused` 字段与 `asyncio.Event` 暂停信号；新增 `GET /api/graph/build/active`、`POST /api/graph/build/{job_id}/pause/resume` 端点；前端新建 `BuildWidget.tsx` 右下角浮窗，挂载在 `(console)/layout.tsx`，全局轮询活跃任务。技术理由：构建 asyncio task 本身不会因导航中断，只需前端全局感知任务状态。
- [x] **Phase 3 — 构建任务持久化 + 断点恢复**：新增 migration `008_graph_build_jobs.sql`；source store 增加 `upsert_build_job / list_build_jobs / mark_interrupted_build_jobs`；启动时自动将 `status=running` 的历史任务标记为 `interrupted` 并日志提示；Graph 页 readiness panel 展示"上次构建被中断"横幅。技术理由：`lightrag_index_status` 表本身即天然断点，新任务只重建 pending/error 文档。

### Verification

- `python -m pytest tests/backend/test_lightrag_core.py tests/backend/test_api.py tests/backend/test_web_server.py tests/backend/test_retrieval_orchestrator.py -q` → 89 passed
- `python -m pytest -q` → 216 passed
- `python -m ruff check core/ web/ && python -m mypy` → All checks passed
- `cd web/frontend && npx tsc --noEmit` → passed
- `npx -y node@20 node_modules/next/dist/bin/next build` → 11 static pages generated
- `python tools/sync_frontend.py` → 150 文件同步至 pages/

## v0.20.8 LightRAG runtime mode parity and readiness UX (completed)

### User constraints / 约束

- `tests/mocks/run_dev_realtime.py` 与本地 `config.py` 需要支持显式切换本地或 API 大模型。
- 检查正式 AstrBot 插件中的 LightRAG 能力是否与测试脚本一样跑通，移除误导性的“暂未上线/即将上线”状态。
- 遵循 `AGENTS.md` → `CLAUDE.md`：Plan-First、先更新 TODO、测试通过后再标完成、收尾追加 CHANGELOG。
- 不手动修改 `pages/` 构建产物；不覆盖已有用户改动。

### Technical implementation path

- [x] **Phase 1 — Dev realtime LLM mode selector**：为本地 dev 脚本与配置模板增加主 LLM、LightRAG 专用 LLM 的 `local/api/main` 显式选择，并保持旧字段兼容。技术理由：避免通过“base_url 是否为空”隐式推断运行时，便于在 LM Studio/Ollama 与云端 API 间切换。
- [x] **Phase 2 — Formal config parity**：在正式 typed config 与 `_conf_schema.json` 中增加 LightRAG LLM runtime mode 字段，并让耗时估算按 mode 判断 local/remote。技术理由：正式 AstrBot 配置应与测试脚本具备同等可见性，避免本地 endpoint 与远程 API 混淆。
- [x] **Phase 3 — Graph readiness UX**：将未启用/未安装/未构建的 Graph API 响应改为结构化 not-ready 状态，前端 Graph 页展示真实原因与构建入口，不再显示“即将上线”。技术理由：LightRAG Core 已实现，reserved 语义会误导用户判断功能未发布。
- [x] **Phase 4 — Verification + release notes**：补充/调整相关测试，运行后端与前端类型验证，测试通过后更新 TODO 与 CHANGELOG。技术理由：`[x]` 只代表代码落地且相关验证通过。

### Verification

- `python -m pytest tests/backend/test_config.py tests/backend/test_capabilities.py tests/backend/test_web_server.py tests/backend/test_api.py tests/backend/test_lifecycle_and_cli.py -q` → passed, 111 passed
- `python -m pytest -q` → passed, 215 passed
- `python -m ruff check core/config.py core/plugin_initializer.py core/api.py core/capabilities.py web/server.py tests/backend/test_config.py tests/backend/test_web_server.py tests/mocks/run_dev_realtime.py` → All checks passed
- `python -m mypy` → Success: no issues found
- `npx tsc --noEmit` → passed
- `npx -y node@20 node_modules/next/dist/bin/next build` → passed, 13 static pages generated
- `python tools/sync_frontend.py` → passed, 150 files synced to `pages/`


## v0.18.1 LightRAG reset workspace memory cache leak fix (completed)

### User constraints / 约束

- 修复在 run_dev_realtime.py 运行时重置工作区后 LightRAG 指标与实体提取因内存缓存残留而静默跳过的问题。

### Technical implementation path

- [x] **Phase 1 — Clear memory caches in reset_workspace**：在 reset_workspace 中，在销毁 workspace 磁盘目录前，对 rag 所有的 JsonKVStorage 与 JsonDocStatusStorage 属性执行 drop()。技术理由：由于第三方库 LightRAG 的共享内存机制，仅调用 finalize 和删除物理文件并不能清空在内存中的数据缓存，重新实例化时会读取脏缓存而误认为文档已被处理。
- [x] **Phase 2 — Verification**：运行 python -m pytest 与 mocks 测试，确认无异常。

### Verification

- `python -m pytest` → passed

## v0.20.7 Flow node no internal scroll follow-up (completed)

### User constraints / 约束

- Flow 每个节点块内部不要出现滚动条。
- 滚动/移动应跟随整个画面，不与节点内部滚动冲突。
- 移除内部滚动后重新对齐节点高度。
- 不手动修改 `pages/` 构建产物。

### Technical implementation path

- [x] **Phase 1 — Remove node internal scroll**：移除 `.flow-node-body` 与 `.flow-quick-config` 的内部滚动限制。技术理由：避免节点内部滚动与画布整体拖拽/移动互相抢交互。
- [x] **Phase 2 — Re-align rows by fixed taller cells**：提高 Flow 网格统一行高，让节点撑满行高承载快速配置内容。技术理由：去掉内部滚动后仍保持每行节点高度一致、连线端点稳定。
- [x] **Phase 3 — Edge label readability**：放大 Flow 连线标签字号与留白，保持基于连线中点定位。技术理由：提高“默认 / 高精度 / 备份旁路”提示可读性，同时不引入额外布局占位。
- [x] **Phase 4 — Verification + release notes**：运行前端类型检查并追加 CHANGELOG。技术理由：确认样式调整不破坏前端类型契约。

### Verification

- `npx tsc --noEmit` → passed

## v0.20.6 Flow drag and layout follow-up (completed)

### User constraints / 约束

- 优先修复背景长按拖动时文字被全选、导致画布卡住不能拖的问题。
- 每一行节点高度都对齐；横屏适配下允许拓扑整体更宽，减少文字挤压。
- 移除 Flow 快速配置里的 `max_token_size` 手动调整，最大 Token 应自动适配。
- 不手动修改 `pages/` 构建产物。

### Technical implementation path

- [x] **Phase 1 — Drag selection guard**：背景开始拖拽时阻止浏览器文本选择，并在 Flow 画布/节点主体上禁用选择；输入框和 select 保持可交互。技术理由：拖拽平移应独占背景 pointer 行为，不能被文本选择打断。
- [x] **Phase 2 — Wider aligned rows**：扩大 Flow 网格列宽并用统一行高/节点撑满对齐每一行，超出内容在节点内部滚动。技术理由：横屏下用宽度换可读性，同时稳定连线中心点。
- [x] **Phase 3 — Remove manual max token quick field**：从 Flow 快速配置删除 `embedding.max_token_size` 字段及相关 Flow 文案/mock restart 标记。技术理由：该值应由系统自动适配，不应在快速配置中误导用户手动调参。
- [x] **Phase 4 — Verification + release notes**：运行前端类型检查并追加 CHANGELOG。技术理由：确认交互与类型契约不被破坏。

### Verification

- `npx tsc --noEmit` → passed

## v0.20.5 Flow quick config and branch alignment (completed)

### User constraints / 约束

- 保持当前 Langflow 风格拓扑设计，不改数据流结构和已有切换逻辑。
- 在 Flow 节点内加入高频、非机密、API 可写的快速配置项。
- 机密与结构性配置只提示环境变量或完整设置页，不在 Flow 中保存。
- 不新增后端 API，不改 `PipelineStage` / `CapabilitiesData` / `DependencyStatus` 契约。
- 不手动修改 `pages/` 构建产物。

### Technical implementation path

- [x] **Phase 1 — Effective config + quick-config model**：`/flow` 同时读取 `getCapabilities()` 与 `getEffectiveConfig()`，将有效配置快照传入 Flow 组件，并新增 Flow 内部快速配置字段模型。技术理由：复用现有配置读取/写入能力，不扩展后端接口。
- [x] **Phase 2 — Node quick-config UI + save flow**：在节点卡片内渲染 embedding/vector_store/graph/sync/ingest 的紧凑配置面板，逐节点保存脏字段并按返回值展示 restart/rebuild banner。技术理由：高频配置就地完成，同时保持保存边界清晰。
- [x] **Phase 3 — Parallel branch visual alignment**：统一 `retrieval` 与 `graph` 并行节点高度基准，超出内容在节点 body 内滚动并重新测量连线端点。技术理由：减少分支高度差导致的视觉跳动和连接线不稳。
- [x] **Phase 4 — Verification + release notes**：运行前端类型检查并更新 CHANGELOG。技术理由：确认 Flow 内部类型和 UI 状态不破坏现有前端契约。

### Verification

- `npx tsc --noEmit` → passed

## v0.20.4 Flow page first paint stabilization (completed)

### User constraints / 约束

- 修复进入数据流页面瞬间画面错位/闪乱的问题。
- 修复拖拽、缩放、fit 等操作后文字和节点发糊的问题。
- 只修画布渲染稳定性，不改 Flow 功能与 API 契约。

### Technical implementation path

- [x] **Phase 1 — First paint + transform stabilization**：在拓扑图完成节点测量与首次 fit 前隐藏 world 层；画布缩放改为 `zoom`，平移坐标归整到整数像素，进入页默认视角优先保持 100% 清晰。技术理由：避免默认 `scale=1,x=0,y=0` 被浏览器先绘制一帧，同时减少 transform 缩放文字造成的发糊。
- [x] **Phase 2 — Verification + release notes**：运行前端类型检查并更新 CHANGELOG。技术理由：确保首帧修复不破坏类型契约，同时避免再次污染 `pages/` 禁改区。

### Verification

- `npx tsc --noEmit` → passed

## v0.20.3 Flow page Langflow topology redesign (completed)

### User constraints / 约束

- 根据 `docs/Flow Page Redesign/` 的参考文件与重构 prompt 重构当前 Flow 页面。
- 尽可能遵循参考设计：横向固定分支拓扑、节点化参数区、内联依赖管理、画布平移缩放。
- 参数功能与网络契约不变，不改 `lib/api.ts` 数据类型与后端 API。
- 不手改 `pages/` 构建产物，不触碰用户已有 docs 变更。

### Technical implementation path

- [x] **Phase 1 — Flow topology components**：抽出 `components/flow/` 节点、连线、分段控件、依赖行与图标组件，并按真实节点测量绘制拓扑。技术理由：将复杂交互从页面状态机中拆出，避免单文件继续膨胀。
- [x] **Phase 2 — Page integration**：重写 `/flow` 呈现层，保留 `getCapabilities`、`updateConfigValue`、`installDependency`、`recheckDependencies` 与现有状态机。技术理由：只换 UI，不改变配置写入与能力检测契约。
- [x] **Phase 3 — Tokens and i18n**：补齐 Flow 专用 token、动画与中英文展示文案。技术理由：参考设计要求中性 token 驱动，并保持双语控制台一致性。
- [x] **Phase 4 — Verification + release notes**：运行前端类型检查与构建，测试通过后更新 TODO 与 CHANGELOG。技术理由：`[x]` 必须代表代码落地且相关验证通过。

### Verification

- `npx tsc --noEmit` → passed
- `npx -y node@20 node_modules/next/dist/bin/next build` → passed，13 static pages generated
- `python -m pytest tests/backend/test_api.py tests/backend/test_web_server.py -q` → 73 passed, 274 warnings

## v0.20.2 LightRAG local runtime observability (completed)

### User constraints / 约束

- 保留 LightRAG raw-text indexing path，不把 Milvus `DocumentChunk` 当作 LRAG chunk 复用。
- 进度条按 LRAG 实际或等价切分的 chunk 计数，时间显示必须贴近真实耗时。
- 本地 phi4/LM Studio 长时间推理优先保证稳定，不为本地模型增加并发。
- Terminal 需要更细分类并纳入前端 toast 成功/失败事件。
- 前端设计尽量不碰，只做必要字段、文案和日志上报。

### Technical implementation path

- [x] **Phase 0 — Governance / 执行治理**：按 `AGENTS.md` → `CLAUDE.md` 要求读取项目规范，追加本计划，执行前保护已有 dirty files。技术理由：避免覆盖用户已改动内容，并满足项目闭环。
- [x] **Phase 1 — Local LLM runtime hardening**：为图谱构建 LLM 增加 timeout/retry/backoff 配置，`LMStudioLLMAdapter` 使用可配置超时并记录耗时、速度、retry 与错误类型。技术理由：本地 phi4 慢推理不能被硬编码 180s 提前杀死。
- [x] **Phase 2 — LRAG chunk progress + time model**：继续优先读原文；用 LightRAG 等价 chunking 预先得到 LRAG chunk 总数，job 暴露 `processed_chunks/total_chunks`、monotonic elapsed 与动态 ETA 所需字段。技术理由：进度按真实 LRAG 工作量，而非文章数或 Milvus chunk 数。
- [x] **Phase 3 — Structured terminal events**：扩展内存日志结构化字段与 `/api/logs/events`，把 graph/llm/embedding/retrieval/web/toast/system 分类统一进 terminal 数据源。技术理由：排查性能时需要按功能面筛选，toast 也必须可追踪。
- [x] **Phase 4 — Minimal frontend adaptation**：Graph/Ask 页优先显示 LRAG chunk 进度和真实 elapsed/ETA；ToastProvider 上报事件；Terminal 增加分类过滤但不重做视觉。技术理由：满足可读性要求，同时控制前端改动面。
- [x] **Phase 5 — Verification + release notes**：补充后端与前端类型测试，更新 mock/config 示例，测试通过后勾选 TODO 并追加 CHANGELOG。技术理由：`[x]` 仅代表代码落地且相关测试已过。

### Verification

- `python -m pytest tests/backend/test_lightrag_core.py tests/backend/test_api.py tests/backend/test_web_server.py -q` → 84 passed
- `npx tsc --noEmit` → passed
- `python -m pytest -q` → 214 passed
- `python -m ruff check .` → All checks passed
- `python -m mypy` → Success
- `npx -y node@20 node_modules/next/dist/bin/next build` → passed，13 static pages generated
- `python tools/sync_frontend.py` → 149 文件同步至 `pages/`

## v0.20.1 LightRAG raw-text indexing path (completed)

### User constraints / 约束

- LightRAG 路径使用原始文件文本，Milvus 路径继续使用 SQLite chunk，两者完全分离。
- fitz 未安装时自动降级到 chunk 拼接，保持向后兼容。

### Technical implementation path

- [x] **Phase 1 — `_extract_raw_doc_text()`**：模块级纯函数，从 `SourceDocument.file_path` 重新提取文本；支持 PDF（fitz）、txt/md（直接读文件）；任何异常返回 `None`（降级）。
- [x] **Phase 2 — `_run_lightrag_build_job` 分叉**：优先调用 `_extract_raw_doc_text(doc)` 获取原始文本；失败时降级为原有 chunk 拼接；`max_doc_chars` 截断逻辑对两条路径均生效。

### Verification

- `python -m pytest -q` → 210 passed
- `ruff check . --quiet` → OK
- 重建图谱时终端观察：传入 LightRAG 的文本为原始 PDF 文本（无 chunk overlap 重复）

## v0.20.0 UX & retrieval overhaul (completed)

### User constraints / 约束

- 知识库检索：移除图谱 tab，改为仅向量检索，结果显示带前后文的上下文块。
- 图谱检索迁移到图谱页侧边栏（与详情共用可折叠 panel）。
- Milvus auto-index：文档变更后自动触发，移除所有手动构建向量索引入口。
- LightRAG 构建按钮显著化：空态 CTA + 大按钮 + 构建进度条。
- Research Agent：移除顶部「Research Agent」标题，持久化集合选择。
- 引用来源：绑定到用户当前查看的消息气泡；气泡点击触发白色辉光动画（×2圈）；侧边栏收起改为可折叠 bar。
- 输入框焦点：移除橙色 border+ring，仅保留增强版轨道辉光动画。
- 引用来源 → 点击展开显示上下文（NotebookLM 风格，命中段落加粗）。

### Technical implementation path

- [x] **Phase 1 — Bug 修复**：使用 `listCollections()` 替代 `listKbCollections()` 确保集合正确加载；图谱页 `listCollections()` 调用加 5s 超时保护（`Promise.race`）；从 Search 页完整删除图谱检索 tab。
- [x] **Phase 2 — 搜索页重构**：后端 `search_kb` + `get_chunk_context(doc_id, chunk_id, window)` 扩展，`handle_kb_search` 内联前后文；前端 Search 页移除图谱 tab，结果卡片三段式（前文/命中/后文）。
- [x] **Phase 3 — 图谱页增强**：无图谱时显示空态 CTA 大按钮；buildJob 进度条替代旧文字状态行；侧边栏新增「详情」/「图谱查询」双 Tab，查询区从底部移入侧边栏；工具栏构建按钮根据是否有图谱切换 primary/outline。
- [x] **Phase 4 — RA 顶部栏**：移除 `{t("nav_ask")}` 标题；modeInfo 直接展示；集合选择写入/读取 `localStorage("kr_ask_collection")`。
- [x] **Phase 5 — 引用来源重设计**：新增 `selectedMsgIndex` + `glowingMsgIndex` 状态；点击 assistant 气泡触发白色辉光动画（×1圈后 `onAnimationEnd` 清除）并切换 sources；SourcesPanel 关闭 X 改为折叠 bar。
- [x] **Phase 6 — 输入框焦点辉光**：删除 `.ask-card:focus-within` 的 `border-color`/`box-shadow`；新增 `.ask-card:not(.ask-card--loading):focus-within::before` 轨道辉光（更亮白混橙，1.8s/圈）；`.msg-bubble--glow` 白色辉光动画（2圈后停止）。
- [x] **Phase 7 — 移除手动索引入口**：文档页移除 auto-index toggle 按钮和手动重建按钮；清理相关 state（`autoIndexEnabled` / `pendingCount` / `rebuilding`）和 import。
- [x] **Phase 8 — 引用来源展开上下文**：新增 `GET /api/kb/chunk-context` 端点 + `getChunkContext()` API 函数；`SourceCard` 组件点击展开显示前后文，命中 chunk 加粗显示。

### Verification

- `python -m pytest` → 210 passed, 267 warnings
- `ruff check . && mypy` → All checks passed
- `cd web/frontend && npm run build` → 11 static pages generated
- `python tools/sync_frontend.py` → 149 文件同步至 pages/

## v0.18.0 Data-flow wizard + optional dependency management + capability registry (completed)

### User constraints / 约束

- WebUI 核心参数配置需清晰呈现数据流并按需切换，采用分步流程图 + TODO 式状态，保持现有暖色/玻璃风格。
- 在设置中加入「一键安装并管理」`requirements-additional.txt` 可选依赖（pymilvus / sentence-transformers / lightrag-hku / boto3）的方法，并与数据流视图结合。
- 安装机密始终仅经环境变量；Docker 部署需提示依赖持久化与「装后需重启」。
- 后端梳理数据流、消除冗余、优化结构（去重 + 大文件拆分）。

### Technical implementation path

- [x] **Phase 1 后端基础**：新建 `core/capabilities.py`（可选依赖清单 + 唯一 `module_available` + 数据流环节快照 `detect_pipeline`/`detect_capabilities`）；消除 `config.py`、`plugin_initializer.py` 重复的 `_module_available`（改为 import 同一实现，保留模块名兼容既有 monkeypatch）；在 `core/config.py` 建立 `CONFIG_KEY_POLICY` 单一登记表，`api._CONFIG_UPDATE_KEYS`/`_STRUCTURAL_KEYS` 与 `runtime_config._ALLOWED_RUNTIME_KEYS` 改为派生；`r2_sync.enabled`/`notion_sync.enabled`/`source_store.ocr_enabled` 纳入可写（非机密）。
- [x] **Phase 2 后端接口**：`KnowledgeRepositoryApi` 新增 `get_capabilities`/`list_dependencies`/`install_dependency`/`recheck_dependencies`；`web/server.py` 注册 `/api/capabilities`、`/api/dependencies`、`/api/dependencies/install`、`/api/dependencies/recheck`；安装经 `sys.executable -m pip install`，仅限白名单包（`resolve_install_spec` 防注入），输出逐行转发到日志缓冲（终端日志页可见）。
- [x] **Phase 3 后端结构**：能力检测/允许键去重收敛（请求 #3 实质）；抽出 `core/api_capabilities.py::CapabilitiesApiMixin`，确立 mixin 拆分范式。
- [x] **Phase 3b（deferred 跟进）**：将 `core/api.py`（仍 ~1360 行，超 CONVENTIONS §4 红线）的 documents/retrieval/graph/sync 公共方法进一步拆为 mixin 子门面，并把 `plugin_initializer.initialize()` 分阶段化。理由：该门面耦合密集、被 web/event_handler/测试广泛依赖，宜在独立 session 单独评审与回归；本次优先交付前端可见价值，去重已完成。按 CONVENTIONS §4 以本条登记跟进。
- [x] **Phase 4 前端**：`lib/api.ts` 新增 capabilities/dependencies 类型、客户端与 mock；`lib/i18n.ts` 新增 `nav_flow` + `flow_*` 中英键；`components/rail/Rail.tsx` 新增「数据流」入口；新建 `app/(console)/flow/page.tsx` 数据流流程图（① → ⑦ 节点 + TODO 式状态徽章 + 节点内切换后端 + 切换后果横幅 + 缺失依赖就地安装），数据源为 `/api/capabilities`（取代前端字符串匹配）。
- [x] **Phase 5 前端**：flow 页内依赖管理面板（安装 / 版本 / 重新检测）+ 终端日志链接 + 安装后「需重启 + Docker 持久化」提示。
- [x] **Phase 6 前端**：`settings/page.tsx` 精简（移除与 flow 重复的状态概览卡与「基础召回」说明，新增指向 `/flow` 的入口横幅；保留外观与高级字段编辑）。

### Verification

- `python -m pytest` → 199 passed, 1 skipped
- `ruff check .` → All checks passed
- `mypy` → Success（domain 严格域无误）
- `cd web/frontend && npm run build` → 编译通过，`/flow` 静态路由生成
- `python tools/sync_frontend.py` → 同步 149 文件至 `pages/`（含 `/flow`）

## v0.17.0 Milvus default retrieval and on-demand LightRAG precision mode (completed)

### User constraints / 约束

- 新安装默认使用 Milvus；旧安装显式配置 `astr` 时保持兼容，并在 Milvus 不可用时受控回退。
- LightRAG 仅由 Web Research Agent 在指定 collection 中显式启用；默认问答与 Discord 均不自动调用。
- 高精度问答使用 Milvus chunks + LightRAG context，由外层 LLM 单次生成最终答案。
- LightRAG 未就绪时展示成本预估，允许构建后自动续问、本次退回 Milvus或取消。
- 所有前端改动延续现有暖色、圆角、毛玻璃、药丸控件和中英文设计语言。

### Technical implementation path

- [x] **Phase 1 — 后端数据流收敛**：删除旧 GraphStore/Pipeline，统一 Ask、query_agent 与 LightRAG context 路径，新增请求/实际召回模式契约。
- [x] **Phase 2 — Embedding 与索引兼容性**：独立 embedding 配置、真实维度探针、Milvus schema 校验及 Milvus/LightRAG 指纹状态。
- [x] **Phase 3 — Web 高精度交互**：在 Research Agent 设置浮层加入会话级开关、collection 约束、构建续问与实际模式标识。
- [x] **Phase 4 — 发布与回归闭环**：更新 schema、文档、版本、测试和静态前端产物。
- [x] **Phase 5 — 首次安装基础能力与设置页收敛**：启动时创建默认 collection，保证 PDF 上传与 SQLite 词汇召回始终可用；采用轻量多语言本地 Embedding 作为新安装默认值；设置页明确区分基础召回和可选 LightRAG 高精度参数，并清理 Web 上传暂存副本。
- [x] **Phase 6 — 安装依赖轻量化**：根 requirements 仅保留基础安装依赖；Milvus、本地 Embedding/PyTorch、LightRAG、R2 与开发工具统一进入手动安装的 Additional Requirements 文件，缺包时保持插件启动、上传与 SQLite/AstrBot 基础召回。

### Verification

- `python -m pytest -q` → `185 passed, 1 skipped`
- `python -m ruff check . && python -m mypy` → `All checks passed / Success`
- `cd web/frontend && npm run lint && npm run build` → `0 errors, 8 existing warnings / 12 static pages generated`
- `python tools/sync_frontend.py --check` → `pages/ 已与 web/frontend/out 一致`

## v0.16.0 Official LightRAG Core replacement (in progress)

### User constraints / 约束

- 官方 `lightrag-hku` Core 单后端；所有触发 LLM 的索引动作必须手动确认。
- sandbox 不配置模型，真实 insert/query/export/delete 探针由 AstrBot 部署后手动执行并观察 terminal。

### Technical implementation path

- [x] **Phase 0 — 部署后探针入口**：新增 `POST /api/graph/probe`，要求 `confirmed=true`，真实 provider 不可用时禁止 mock；输出逐步 `KR LightRAG` terminal 日志。
- [x] **Phase 1 — 依赖与配置**：版本升至 `v0.16.0`，新增 `lightrag-hku`，graph 配置切换为 Core 语义。
- [x] **Phase 2 — Core 接入**：按 collection 独立 workspace，显式 `ainsert(ids=[doc_id])`，查询、导出、删除走官方 Core。
- [x] **Phase 3 — 手动构建**：dry-run estimate、`confirmed=true`、后台 job 与轮询进度。
- [x] **Phase 4 — 可视化**：解析官方 `export_data()` CSV 为真实 nodes/edges；导出失败返回明确错误。
- [x] **Phase 5 — 文档生命周期**：删除/移动固定调用 `adelete_by_doc_id`；独立 `lightrag_index_status` 跟踪 pending/indexed/error。
- [x] **Frontend**：LightRAG 文案、成本确认、job 进度、answer/context、删除/移动影响提示、设置区。
- [ ] **Deployment verification**：在 AstrBot 真实 LLM/Embedding 环境执行 `docs/LIGHTRAG_DEPLOYMENT_PROBE.md`，确认 `delete_stable=true`。
- [x] **Static frontend export**：使用临时 Node.js 20 完成 Next.js build，并执行 `python tools/sync_frontend.py --force` 同步 `pages/`。

### Verification

- `python -m pytest -q` → `168 passed, 5 skipped`
- `python -m ruff check ...` → `All checks passed`
- `npx tsc --noEmit` → passed
- `npx -y node@20 node_modules/next/dist/bin/next build` → passed; 12 static pages generated

---

## v0.15.3 Web 控制台启动接线 (completed)

### User constraints / 约束

- 仅接线启动逻辑；不改动 `web/server.py`、前端或 schema；不引入新依赖。

### Technical implementation path

- [x] **Phase 1 — `__init__` 新增 `_web_runner`**：`core/plugin_initializer.py` 声明 `self._web_runner: Any | None = None`，用于持有 aiohttp AppRunner 引用。
- [x] **Phase 2 — `initialize()` 触发启动**：步骤 7 读取 `web_console` 配置，若 `enabled=True` 则调用 `_start_web_console()`。
- [x] **Phase 3 — `_start_web_console()` 实现**：懒导入 `aiohttp.web` 与 `web.server.build_app`；密码为空时 log error 并跳过；`OSError`（端口占用）与其他异常均 log error 跳过，不影响插件主体；正常启动后 log info 打印访问地址。
- [x] **Phase 4 — `teardown()` 优雅关闭**：在 `_backup_task` 取消后、`vector_store` 关闭前调用 `runner.cleanup()`，异常仅 warning。

### Verification

- `python -m pytest tests/backend/test_config.py tests/backend/test_web_server.py -k "not test_section_overrides" -q` → `44 passed`

---

## v0.15.2 Schema options + secret field security hardening (completed)

### User constraints / 约束

- 仅修复安全漏洞；不引入新功能；不改动前端产物。

### Technical implementation path

- [x] **Phase 0 — 枚举型字段补充 `options`**：`_conf_schema.json` 中 `vector_db.backend`、`vector_db.embedding_provider`、`ask.conversation_enhancement_mode` 三个值域固定的字段添加 `"options"` 数组。技术理由：AstrBot UI 识别该字段后渲染下拉框，防止用户填入无效值静默失效。
- [x] **Phase 1 — 移除 `api_key` 持久化白名单**：从 `core/runtime_config.py` 的 `_ALLOWED_RUNTIME_KEYS["vector_db"]` 中删除 `"api_key"`，使其无法经 `RuntimeConfigStore.set_value` 写入明文 JSON 文件。技术理由：`api_key` 属机密字段，应仅由环境变量 `KR_EMBEDDING_API_KEY` 注入，不得落盘。
- [x] **Phase 2 — Web API 机密字段显式拦截**：在 `core/api.py` 的 `update_config_value` 中新增 `_SECRET_KEYS` frozenset（含 `api_key / secret_access_key / access_key_id / password`），命中时立即抛出 ValueError 并给出环境变量指引。技术理由：双重防护，即使白名单漏网也在 API 层阻断。
- [x] **Phase 3 — 错误日志脱敏**：`core/repository/embedding/external.py` 的 HTTP 错误日志去掉 `err_text`（API 响应体可能含鉴权失败详情），仅保留状态码。异常消息仍携带完整信息供调用方处理。

### Verification

- `python -m pytest tests/backend/test_config.py tests/backend/test_web_server.py -k "not test_section_overrides" -q` → `44 passed`

---

## v0.15.1 Pre-release bug fixes & CI repair (completed)

### User constraints / 约束

- 测试阶段发现的 bug 修复；不引入新功能；不改动前端构建产物。
- CI `pytest` 必须全量通过后才算完成。

### Technical implementation path

- [x] **Phase 1 — CI 测试修复**：`test_milvus_lite_vector_store_lifecycle` 在无 `pymilvus` 环境下抛 `ModuleNotFoundError`；用 `importlib.util.find_spec` 检测并加 `pytest.mark.skipif`。技术理由：pymilvus 是可选依赖，CI 环境不装，测试应优雅跳过而非失败。
- [x] **Phase 2 — fitz 懒加载**：`core/managers/ingest_manager.py:16` 的 `import fitz` 移入 `_extract_and_chunk()` 方法体内，用 `try/except ImportError` 包裹并抛出带安装指引的友好错误。技术理由：模块顶层 import 会在 PyMuPDF 安装失败时导致整个插件无法加载。
- [x] **Phase 3 — Schema 同步**：`_conf_schema.json` 中 `vector_db.db_filename` 默认值改为 `"vector_store.db"`；新增 `auto_index_enabled` 字段（bool, default true）。技术理由：v0.15.0 修改了 `core/config.py` 的默认值但未同步 schema，AstrBot UI 显示旧值。
- [x] **Phase 4 — Sync 状态语义修正**：`core/pipelines/sync_pipeline.py` 当所有文档同步失败（`failed_count == len(pending_docs) > 0`）时返回 `status: "error"`；部分失败返回 `status: "partial_failure"`。技术理由：当前 disabled 目标被调用时返回 `status: "success"` 伴随 `failed_count > 0`，语义误导。
- [x] **Phase 5 — 回归与版本收尾**：`python -m pytest` → 168 passed；`ruff check .` → All checks passed；`metadata.yaml` → `v0.15.1`；`CHANGELOG.md` 追加条目。

### Verification

- `python -m pytest` → 全量通过（含 milvus test skipif）
- `ruff check . && mypy` → 零错误
- `python -c "from core.plugin_initializer import PluginInitializer"` → 无 ImportError（即使 PyMuPDF 未装）
- sync disabled R2 test → `status: "error"` 或 `status: "partial_failure"`

---

## v0.14.0 Local retrieval & Ask Agent integration (completed)

### User constraints / 约束

- 本版本先完成方案讨论与验证，再进入业务代码实现；未获用户批准前不修改检索、AstrBot hook、WebUI 或持久化代码。
- 评估将向量检索改为插件本地运行，并以进程内、单文件持久化的 Milvus Lite 作为优先候选；AstrBot KB 读取保留为可回退或迁移期兼容路径。
- Ask Agent 需要支持 `/kr agent on|off`：打开后，AstrBot 普通对话可使用插件检索结果；关闭后不得影响原有 AstrBot 普通对话。
- Ask Agent 增加可选的“关系 persona”影响：打开时以真人 RA（Research Assistant）风格总结证据与结论，关闭时保持当前问答风格。WebUI 开关放在输入框底部集合选择器右侧。
- 外部 agent 与内部 agent 的边界尚待讨论；本计划先给出推荐职责划分，不提前固化 HTTP 或 AstrBot SDK 契约。
- 评估 NotebookLM 风格的“在线检阅文档”：回答必须能回到来源文档、定位证据片段并继续阅读，而不是只展示不可追溯的向量命中摘要。

### Technical implementation path

- [x] **Phase 0 — Milvus Lite 可行性 spike 与基准**：用隔离原型验证 `pymilvus[milvus-lite]` 本地文件 URI、Linux 部署、单进程生命周期、dense vector CRUD、metadata filter、删除重建、混合检索、数据库文件备份恢复与异常重启；记录小规模边界、仅 `FLAT` 索引、无 partition / 用户角色等限制。单独验证当前 Milvus Lite 版本能否直接使用内建 BM25；官方资料存在版本差异，未通过原型前不得将该能力写入正式契约。技术理由：Milvus Lite 适合作为本地候选，但不能根据 Standalone 能力推断 Lite 行为。（Spike 成功完成：确认需使用字符串主键 schema；已解决 FLOAT_VECTOR 缺少 dim 报错；dynamic field metadata 可用；graceful close 锁释放流程已验证。）
- [x] **Phase 1 — 定义本地检索端口与数据所有权**：新增独立 `retrieval` / `vector_store` ABC，明确 SQLite `source_store` 仍是文档与 chunk 的事实源，Milvus Lite 只是可重建索引；AstrBot KB reader 降为兼容 adapter，不再作为 Ask Agent 的唯一检索源。索引行至少保存 `chunk_id`、`doc_id`、`collection`、文本、内容哈希和可定位引用元数据。技术理由：避免把可丢弃索引与原始文档生命周期混为一体，并允许后续切换 Standalone。（VectorStore 基础接口已定义，InMemoryVectorStore 实现落地，WebUI 配置卡片与多语言键值已接入，测试全绿。）
- [x] **Phase 2 — 明确本地 embedding 策略与按需懒加载**：实现 EmbeddingProvider 多路由适配器，支持用户在配置中自定义选择本地（如 BAAI/bge-large-en-v1.5, bge-m3）或云端 API 提供商；贯彻「按需懒加载（Lazy Load）」与「动态下载（On-demand Download）」原则，只有当用户显式选择本地模型部署时，才动态加载 `sentence-transformers` 依赖并触发模型下载，保证默认状态的轻量与零开销。技术理由：避免在不使用本地 Embedding 时霸占磁盘与内存，且保障英文文献库的精准匹配表征。（base/local/external/cached/factory 五个 Embedding 模块全部落地，SQLite 缓存层实现，懒加载按需下载 100% 测试覆盖。）
- [x] **Phase 3 — 收敛索引生命周期与灾备**：上传、更新、删除文档时同步 upsert / delete 本地索引；提供按 chunk 哈希增量补建、全量 rebuild、健康检查与版本迁移；将 Milvus Lite 文件纳入 R2 快照范围，恢复后支持校验或从 SQLite 重建。技术理由：当前本地上传文档不会写入 AstrBot KB，改用本地索引后必须补齐一致性闭环。（文档同步触发、集合级删除与全量 rebuild API 已集成至 `core/api.py`，单文件数据库灾备恢复测试 100% 通过。）
- [x] **Phase 4 — 统一 Ask retrieval orchestrator**：让 WebUI Ask、AstrBot 普通对话增强和后续外部工具调用共享一条检索管线；候选召回包含 local dense、可验证后再启用的 lexical / sparse 检索、实体召回和图邻域扩展，并统一去重、RRF、来源编号与引用结构；明确在 API 生成端支持复用主框架已配置的 LLM，但必须使用独立的上下文与 RA Persona，确保 Standalone Ask 100% 独立并隔离于 AstrBot 当前会话 of 闲聊历史与角色扮演污染。（Milvus Lite 向量库以自定义字符串主键 schema 构建完毕，统一 RetrievalOrchestrator 与本地 embedding/vector 组件已集成至 `core/api.py` 与 PluginInitializer 组合根，E2E 融合排序与词匹配回退测试全部通过。）
- [x] **Phase 5 — 接入 AstrBot 普通对话增强（非侵入式 Hook 打通）**：在真实 AstrBot SDK 薄壳注册普通消息 Hook 骨架；**目前先打通 Hook 信号通路，但采取旁路 Dry-Run/透传（Pass-through）机制，绝对不干预或修改 AstrBot 的原生原有对话回答**；预留清晰的、热插拔式的「插槽接口（Slot Hook）」，待用户思考并设计好具体的交互影响形式后再行代码填充，保障系统过渡期的非侵入稳定性。（`on_message` 与 `on_agent` 回调已集成至 `core/main.py` 与 `core/event_handler.py`，100% Dry-Run 安全透传 Hook 与槽位逻辑已通过 E2E 生命周期套件验证。）
- [x] **Phase 6 — 增加 Persona 控制与普通对话记忆检索增强**：内部 `ask()` 接口/Web UI 中的 Ask Agent 对话支持 `persona_enabled` 开关，在 Web UI 的输入框底部集合选择器右侧添加对应的“启用 Persona / 角色设定”开关；当 `persona_enabled` 为 `True` 时，动态提取 AstrBot 当前运行态设定的 Persona Prompt 并融入系统提示词以指导 Standalone Ask 答复；`/kr agent on` 和 `off` 目前阶段**仅且只**决定了 AstrBot 的回答是否可以调用插件的记忆召回功能，当为 `on` 时通过 handler 将召回片段（Grounded Context）动态注入传回至 AstrBot 普通消息的 `system_prompt` 中；当为 `off` 时则完全不进行检索，实现 100% 零开销 pass-through。（Standalone Ask persona-enabled 开关已在 WebUI 与核心引擎全面落地，Agent 消息 Hook 零开销透传优化完成，后端单元/集成测试全绿。）
- [x] **Phase 7 — 实现双模式对话增强与 Agent 工具契约**：新增 `ask.conversation_enhancement_mode` 配置项（支持 WebUI Settings 切换），分类处理两种逻辑：一是原生召回注入 (`inject`)；二是内部代理询问 (`query_agent`)，强制关闭内部 Ask Persona 防止过拟合，并通过 `conversation_id` 绑定打通 WebUI Ask 历史大一统，以指令级注入实现完美代理。（ask schema 已注册至 `_conf_schema.json`，双模式对话增强路由在 `core/event_handler.py` 中完整实现，单元/集成测试全覆盖，Next.js 前端编译同步且测试 100% 通过。）
- [x] **Phase 8 — NotebookLM 风格在线检阅与引用定位**：为每个 chunk 持久化页码、段落或字符范围、原件引用 and 可展示预览；回答引用返回稳定 `doc_id + chunk_id + locator`，WebUI 支持从来源面板打开原件并定位到证据附近。评估 PDF.js 在线阅读器；Notion MCP 继续承担同步镜像，不作为本地检索或引用定位的必需依赖。技术理由：Milvus Lite 能提高召回，但在线阅览、证据定位和连续阅读属于应用层能力。（`DocumentChunk` 新增 metadata 字典字段，SQLite replace/list chunks 已更新 JSON 序列化，`IngestManager` 页码/段落/定位符解析全面实现，测试 100% 绿灯。）
- [x] **Phase 9 — 测试、文档与发布闭环**：补向量端口对换测试、Milvus Lite integration 测试、索引重建与 R2 恢复测试、AstrBot hook 桩测试、persona 提示词测试、引用定位 HTTP / WebUI 测试；更新配置 schema、架构说明、版本记录与前端静态产物。
  - [x] 向量端口对换测试（`tests/backend/test_vector_store.py`）
  - [x] Milvus Lite integration 测试（`tests/backend/test_retrieval_orchestrator.py::test_milvus_lite_vector_store_lifecycle`）
  - [x] 索引重建测试（`tests/backend/test_api.py::test_vector_db_sync_and_rebuild`）
  - [x] AstrBot hook 桩测试（`tests/backend/test_lifecycle_and_cli.py`，覆盖 on_message / on_agent on|off 全路径）
  - [x] Persona 提示词测试（`tests/backend/test_api.py::test_ask_with_persona_enabled`）
  - [x] 引用定位元数据测试（`tests/backend/test_sqlite_source_store.py`，覆盖 page_number / locator / paragraph 字段序列化）
  - [x] 引用定位 HTTP 测试（`/api/ask` sources 字段已在 `test_ask_route_returns_answer_and_sources` 中补齐对 `chunk_id + doc_id + locator` 的结构断言）
  - [x] 版本记录（`CHANGELOG.md` v0.14.0 条目已追加）
  - [x] 前端静态产物（`pages/` 已与 `web/frontend/out` 一致）
- [x] **Phase 10 — WebUI 可控 Embedding 与受限配置修改（后端实现）**：在 `core/api.py` 新增 `update_config_value` 配置修改方法，并设立写保护白名单（仅允许修改 `vector_db` 与 `ask`，防范 `r2_sync` 和 `notion_sync` 被错误篡改）；实现配置变更后的动态热重载（Hot-reload），避免重启服务端即时重构 `EmbeddingProvider` 并注入检索器；在 `web/server.py` 新增 `POST /api/config/update` 路由接入。（`core/api.py::update_config_value` 白名单校验 “vector_db”/”ask” + 热重载 EmbeddingProvider / MilvusLiteVectorStore 实现完毕；`web/server.py` 路由注册；`tests/backend/test_web_server.py::test_config_update_route` 覆盖验证通过。）
- [x] **Phase 11 — WebUI 可控 Embedding 与受限配置修改（前端与联调）**：在 `web/frontend/lib/api.ts` 新增 `updateConfigValue` 网络接口；在设置页 `web/frontend/app/(console)/settings/page.tsx` 中，**保持下方”后端有效配置”的只读卡片网格设计完全不变，在其上方（即”外观”设置下方）新增独立的配置编辑面板**；使用现有的 `SegmentedControl` 等 UI 控件与基础输入框，支持配置并提交保存 `vector_db`（`backend` 选择 `astr`/`milvus`、`embedding_provider` 选择 `local`/`external`、`embedding_model`、`api_key`、`base_url`）和 `ask`（`conversation_enhancement_mode` 选择 `inject`/`query_agent`）；当 `embedding_provider` 选为 `local` 时，在面板中动态展示离线模型运行所需的 `pip install sentence-transformers` 依赖安装指南。（`lib/api.ts::updateConfigValue` 接口、Settings 配置编辑面板（vector_db / ask 全字段）及本地模型安装说明均已实现并构建同步。）
- [x] **Phase 12 — 全量回归与质量核对**：编写配置实时持久化与受控写入单元测试；进行 Node 22 下的 Next.js 静态静态构建镜像编译并同步；执行 `pytest` 与 `ruff` 代码检查，保障项目 100% 绿灯。
  - [x] 配置受控写入单元测试（`tests/backend/test_web_server.py::test_config_update_route`）
  - [x] `pytest` 152 passed
  - [x] `ruff check .` All checks passed
  - [x] `pages/` 与 `web/frontend/out` 已一致
  - [x] `mypy` duplicate module 错误：已通过在 `core` 目录下递归补齐空 `__init__.py` 解决，且无配置违规。
  - [x] Next.js 静态构建验证：在 Node 22.15.0 下成功重跑 `npm run build`，并利用 `tools/sync_frontend.py` 成功将 129 个静态文件同步至 `pages/` 目录。

### Decisions required / 待确认

> 以下决策已在 Phase 2–7 实施中明确落地。

- [x] `/kr agent on|off` 的作用域：**已决定**为当前会话/频道级（Phase 5/6 实现）。
- [x] AstrBot 普通对话增强方式：**已决定**为双模式——`inject`（注入检索上下文）与 `query_agent`（独立 Ask Agent 代理），两种模式均已实现（Phase 7）。
- [x] “关系 persona”的来源：**已决定**为读取 AstrBot 当前 Persona Prompt 并融入系统提示词（Phase 6）。
- [x] 外部 agent 首版范围：**已决定**保留 WebUI `/api/ask`，暂不暴露 MCP tool（Phase 4）。
- [x] 本地 embedding 的目标：**已决定**按需懒加载，同时支持完全离线（`local`）与复用已有 provider（`external`），由用户配置选择（Phase 2）。

### Verification

- `python3 -m pytest` → ✅ 152 passed
- `ruff check . && mypy` → ✅ All checks passed / Success
- `cd web/frontend && npm run lint && npm run build` → ✅ lint 通过（5 个既有 hook dependency warning 保留）；Node 22.15.0 下 Next.js export 成功，129 个静态文件
- `python3 tools/sync_frontend.py && python3 tools/sync_frontend.py --check` → ✅ `pages/` 已与 `web/frontend/out` 一致
- Milvus Lite spike：摄入、查询、更新、删除、重启、快照恢复、全量 rebuild、异常恢复 → ✅ Phase 0 原型验证通过（见 Phase 0 备注）
- AstrBot 人工验收：`/kr agent off` 不影响普通对话；`/kr agent on` 后普通对话带可追溯引用；RA persona 开关只改变回答表达 → 待真实 AstrBot 环境验收

## v0.13.0 Contract convergence & persistence hardening (completed)

### User constraints / 约束

- 先提交计划供用户审核；本轮不修改业务代码、不执行迁移、不改变现有运行态数据。
- R2 与 Notion 信息由用户在 AstrBot 原生插件配置中填写；WebUI 的有效配置页继续保持只读核对模式，并对机密字段脱敏。
- Notion token 不写入插件配置：仍由 AstrBot 中 `notion_sync.mcp_server_name` 指向的 MCP server 管理。
- 持久化修复须兼容现有 `knowledge_repository.db` 与 `data_dir/documents/`，数据库结构变更只允许追加幂等 migration。
- 本版本为功能与数据一致性修复，版本号按次版本升级为 `v0.13.0`，不作为 `v0.12.x` 视觉补丁继续扩展。

### Technical implementation path

- [x] **Phase 1 — 锁定前后端 HTTP 契约并补端到端测试**：统一 collection 创建、文档上传、文档更新的返回资源结构；把文档字段 `size_bytes` / `updated_at` 等映射为前端稳定模型；修正 KB 搜索 `k` 与后端 `top_k` 参数不一致；统一 reserved `501` 降级协议；将图谱查询的 `entity_id` / `relation_id` / `src_entity_id` / `dst_entity_id` 序列化为前端消费结构。技术理由：现有后端路由测试未覆盖真实前端 wrapper，多个已实现端点仍会在 UI 中产生字段错位或异常。
- [x] **Phase 2 — 接通已有但 UI 尚未消费的能力**：前端接入 `POST /api/logout`、`GET /api/documents/{id}/raw`、`POST /api/sync/{target}`、同步状态读取、集合删除与图谱 collection 筛选；明确 `/api/sync/all` 为真实 fan-out 或移除未支持入口；在组合根把现有 `LLMAdapter` 注入 `KnowledgeRepositoryApi`，避免 Ask 生产环境始终退化为检索摘要。技术理由：这些后端能力已存在，但当前端到端用户流程没有闭环。
- [x] **Phase 3 — 加固 AstrBot 原生配置入口**：保留 `_conf_schema.json` 已有的 R2 字段（`account_id`、`access_key_id`、`secret_access_key`、`bucket`、`cdn_domain` 等）与 Notion MCP 字段（`mcp_server_name`、`database_id`、`parent_page_id` 等）；补 enabled 状态下的必填校验、字段说明与可用性诊断；确认 AstrBot schema 支持时将 secret 字段标记为密码输入；保持 `/api/config/effective` 只读且脱敏。技术理由：配置入口已经存在，下一步应补约束与诊断，而不是在 WebUI 再造一套可写配置页。
- [x] **Phase 4 — 收敛运行时配置持久化边界**：为 `RuntimeConfigStore` 增加允许写入键白名单，仅持久化 Notion 自动建库产生的非敏感字段；校验 AstrBot `save_config` / `update_config` / `persist_config` 的参数语义，避免用局部 override 覆盖原生完整配置；Notion 自动建库后同步刷新内存 `Config`，使只读有效配置无需重启即可看到新 `database_id`。技术理由：当前 JSON override 可写任意键，框架写回适配与内存刷新仍不完整。
- [x] **Phase 5 — 修复 R2 灾备真实闭环**：为数据库快照定义专用对象键与上传方法，修复真实 R2 上传为 `backups/knowledge_repository.db.pdf` 而恢复读取 `backups/knowledge_repository.db` 的不一致；使用 SQLite backup API 或受控 checkpoint 生成一致性快照；恢复时下载到临时文件、校验 SQLite 完整性，并在关闭现有连接后原子替换或明确要求重启；补真实 `R2SyncTarget` mock 集成测试。技术理由：当前内存替身测试未覆盖真实键名，且直接覆盖已连接 SQLite 文件存在损坏风险。
- [x] **Phase 6 — 完善本地数据生命周期**：把摄入的“复制原件 + documents 写入 + chunks 写入”收敛为失败可回滚流程；删除文档时清理 `data_dir/documents/` 原件、关联图谱贡献与增量状态，并明确是否删除 R2 对象 / 归档 Notion 页面；补孤儿文件、孤儿图谱记录与重启后读取测试。技术理由：SQLite 表内级联删除已存在，但文件系统、图谱仓储和远端镜像当前没有随文档生命周期同步收敛。
- [x] **Phase 7 — 校准图谱与备份能力声明**：决定 `graph_entities.embedding` 与 `reuse_kb_embedding` 是正式接入还是明确 defer；修正文档中“manifest + kb.db 快照”“大文件改用 R2 链接”等尚未完整落地的声明，或实现对应能力；明确插件备份范围是本插件 `knowledge_repository.db`、原件目录，还是还需纳入 AstrBot 自身 KB 数据。技术理由：当前 schema、配置、TODO 历史声明与实际实现存在偏差，恢复能力边界需要对用户可解释。
- [x] **Phase 8 — 全量回归与发布闭环**：补前端 wrapper ↔ aiohttp 路由集成测试、配置持久化测试、SQLite 重启/迁移测试、R2 快照备份恢复测试与删除生命周期测试；完成版本记录、前端静态构建同步与质量检查。

### Verification

- `python3 -m pytest tests/backend/test_config.py tests/backend/test_sqlite_source_store.py tests/backend/test_graph_store.py tests/backend/test_sync_pipeline.py tests/backend/test_r2_target.py tests/backend/test_web_server.py` → 相关契约均包含在全量回归中并通过
- `python3 -m pytest` → 136 passed
- `ruff check . && mypy` → All checks passed / Success
- `cd web/frontend && npm run lint && npm run build`（通过 Node 22 执行）→ lint 通过（保留 5 个既有 hook dependency warning）；Next.js export 成功
- `python3 tools/sync_frontend.py && python3 tools/sync_frontend.py --check` → `pages/` 已与 `web/frontend/out` 一致
- `curl http://localhost:26619/{ask,documents,search,graph,sync,settings}` → 动态预览路由均返回 HTTP 200
- AstrBot 原生插件设置填写 R2 / Notion，打开 `/settings` → 代码路径与脱敏契约已覆盖；真实 AstrBot 环境待人工验收
- 上传、更新、删除、R2 同步、R2 恢复、Notion 初始化与拉取、重启后读取 → 自动化契约已覆盖；真实 R2 / Notion 凭据环境待人工验收

## v0.12.1 WebUI screenshot parity patch (completed)

### User constraints / 约束

- 以 `docs/屏幕截图 2026-06-01 133003.png` 至 `133036.png` 五张截图为视觉验收基线。
- 本版本为 `v0.12.0` 的补丁修复，只处理 WebUI 截图对齐、前端发布链路与版本记录一致性。
- 所有现有 `/api/*` 请求路径、方法与字段契约保持不变。
- 不手改 `pages/`；仅通过前端构建与 `tools/sync_frontend.py` 同步生成。

### Technical implementation path

- [x] **Phase 1 — 治理与发布链路修复**：统一 `metadata.yaml` 版本号；让 `tests/run_webui.py` 优先托管 `web/frontend/out/`，不存在时回退 `pages/`；技术理由：避免动态预览继续加载旧源码目录或过期静态产物。
- [x] **Phase 2 — 全局视觉基线收敛**：修正 HSL 派生 token 覆盖，保留唯一全局 `Atmosphere`，移除页面重复 `DotField` 与额外 Aurora；技术理由：当前重复视效叠加造成背景噪声与截图明显不一致。
- [x] **Phase 3 — 左栏外壳截图对齐**：补齐搜索/跳转框、品牌副标题、`AI` badge、在线状态与激活项左侧强调条，并校准 rail 间距；技术理由：左栏是五张截图共享的固定视觉锚点。
- [x] **Phase 4 — 五页截图对齐**：分别校准 Ask、文档、检索、图谱、同步页面的布局密度、空状态、面板位置、图谱平面节点和同步分组；技术理由：当前页面功能已存在，但结构与目标截图存在明显偏差。
- [x] **Phase 5 — 构建、静态同步与回归**：构建 Next.js export，经 `tools/sync_frontend.py` 同步 `pages/`，运行前端 lint、后端测试、`ruff` 与 `mypy`；技术理由：确保补丁可由 aiohttp 单进程托管且不破坏后端。

### Verification

- `cd web/frontend && npm run lint && npm run build` → lint 通过（保留 5 个既有 hook dependency warning）；Next.js export 成功
- `python3 tools/sync_frontend.py && python3 tools/sync_frontend.py --check` → `pages/` 已与 `web/frontend/out` 一致
- `python3 -m pytest` → 128 passed
- `ruff check . && mypy` → All checks passed / Success
- 浏览器逐张对照 `docs/屏幕截图 2026-06-01 133003.png` 至 `133036.png` → 动态预览已启动于 `http://localhost:26619/`

## v0.12.0 WebUI visual optimization (completed)

### User constraints / 约束

- 严格按照《视效优化-落地说明.md》的要求，对控制台前端（Next.js + fumadocs-ui）的视效进行增强与交互细化。
- 所有数据请求路径、契约和 API 完全保持一致，不做任何后端或网络传输层改动。
- 引入 HSL 强调色渐变滑杆与预设，确保全站级联换肤与本地持久化。
- 移除空状态示例提问气泡；在应用各页移除冗余的 SunBloom 装饰背景。
- 知识图谱节点重构为扁平淡毛玻璃 HTML 圆盘，连线高亮，关系小药丸仅在聚焦邻域时展示。

### Technical implementation path

- [x] **Phase 1 — 氛围视觉层落地**：扩充 `DotField` 数量至 22 个并增加微光深度感；编写 `Atmosphere` 组件，基于 RAF 和 LERP（0.06）实现对鼠标指针坐标的惯性跟随；在页面 `main` 容器底层全局挂载，以及登录页作为 Hero 底层（`components/fx/Atmosphere.tsx`, `components/fx/DotField.tsx`, `app/(console)/layout.tsx`）。
- [x] **Phase 2 — Ask Agent 初始页化繁为简**：重构 `AskPage` 空状态，移除示例卡片气泡推荐，仅渲染居中 `✦` 星尘图标及标题介绍（`ask_empty_title` 和 `ask_empty_sub`），同时移除应用页冗余的 `SunBloom` 太阳背景（`app/(console)/ask/page.tsx`）。
- [x] **Phase 3 — 自定义 HSL 级联变色与持久化**：重构 `tokens.css` 设计令牌，使强调色由 H/S/L 三个变量和 `color-mix` 混合公式动态控制；在 Settings 页新增 Hue/Saturation/Lightness 渐变轨道滑杆与 6 组 HSL 预设按钮，写入 document 并同步持久化到 localStorage（`app/(console)/settings/page.tsx`, `styles/tokens.css`, `lib/theme.ts`）。
- [x] **Phase 4 — 混合淡毛玻璃知识图谱**：重写 `GraphPage`，使节点以 HTML 圆盘展现并辅以 `backdrop-filter: blur(7px)` 与 HSL 半透明混色，SVG 承载连线与点击热区；关系小药丸采用扁平毛玻璃外观，且仅在选中/Hover节点的关联边上动态浮现，支持 1-hop 聚焦淡化（`app/(console)/graph/page.tsx`）。
- [x] **Phase 5 — 翻译键值对对齐**：在 `lib/i18n.ts` 中补全空状态标题、滑杆轨道及说明的对应中英文翻译条目，维持语言持久化与流畅切换。

### Verification

- `npm run build` inside `web/frontend` → ✅ Compiled and static exported successfully, 0 TypeScript/Turbopack errors.

---

## v0.11.0 Backend hardening & API completing (completed)

### User constraints / 约束

- 实现 v0.10.0 遗留的两个未完工后端端口：文档下载与显式登出。
- 本版本聚焦于后端健壮性与可用性提升，不改变现有 WebUI 主体结构。
- 保证前后端契约的一致性，通过补充和加强单元/集成测试进行验证。
- 不执行任何 `git commit`，提交交由用户执行。

### Technical implementation path

- [x] **Phase 1 — 配置持久化收敛**：为 `RuntimeConfigStore` 增加更清晰的加载/覆盖/写回边界，并预留 AstrBot 原生配置写回适配口；技术理由：固定运行时覆盖与框架配置的职责，规范运行时动态配置的加载与写入流程。
- [x] **Phase 2 — Notion 自动分页与健壮性**：在 `NotionMCPAdapter` 中为 `query_database` 补齐自动分页（通过 page cursor 循环拉取全部数据）、标准属性存在性检查以及缺失属性列的详细诊断信息；技术理由：保证当 Notion 数据规模增大或属性列被重命名时，同步流程能平滑降级或清晰失败。
- [x] **Phase 3 — 同步状态可审计性**：增强 Notion 初始化、同步拉取 (pull) 和推送 (push) 的统计结果与错误日志，确保 `sync_records` 及 API 返回能科学区分 skipped, failed, schema_missing 和 remote_missing；技术理由：提升云端同步技术债的排查效率。
- [x] **Phase 4 — 补全未完工 API 端口**：
  - [x] 在 `web/server.py` 实现 `GET /api/documents/{doc_id}/raw` 文档下载端点，并在前端解除下载按钮的禁用状态（若适用）。
  - [x] 在 `web/server.py` 实现 `POST /api/logout` 显式登出端点，清理后端 session 集合并删除 `kr_session` cookie。
- [x] **Phase 5 — 历史 TODO 清理**：修正 `v0.1.0` 历史残留状态，把已被后续高版本覆盖 of 初始化工作闭环，避免新一轮开发误判。
- [x] **Phase 6 — 回归与契约测试强补**：针对 Notion 分页及异常诊断、配置存储、新增的 raw 下载与登出 HTTP 端口进行 100% 契约和集成测试覆盖。

### Verification

- `python3 -m pytest` → ✅ 128 passed
- `cd web/frontend && npm run build` → 确认前端正常构建
- `python3 tools/sync_frontend.py --check` → 确认前后端静态同步无误
- `ruff check . && mypy` → ✅ All checks passed & Success

---

## v0.10.0 WebUI 全面重构 · Next.js + fumadocs-ui (completed)

### User constraints / 约束

- 前端技术栈：Next.js App Router + `fumadocs-ui` + `next-themes`，引入暖色奶油设计语言。
- 后端端口契约不得破坏；仅新增 `POST /api/ask`（Ask Agent）。
- 部署：`output:'export'` 静态导出 → `tools/sync_frontend.py` → `pages/` → aiohttp 单进程托管。
- `?mock` 离线预览模式必须保留；进场动画禁止初始 opacity:0。
- 视效优先，可适当提高系统资源占用（GPU 合成动画），使用 fumadocs 前端技术栈。
- 前端依赖但后端尚未实现的端口，须先在本 TODO 标记，不得臆造路径。

### 前端依赖、后端尚未实现的端口（需后续版本跟进）

- [ ] `GET /api/documents/{id}/raw` — 文档下载；检查器下载按钮先 disabled，后端实现后接通。
- [ ] `POST /api/logout` — 显式登出；暂用前端清除 `kr_session` cookie 降级，后端实现后替换。
- [x] `POST /api/ask` — Ask Agent 对话（v0.10.0 已实现，见 Phase 5）。

### Technical implementation path

- [x] **Phase 1** — TODO 更新。
- [x] **Phase 2** — 脚手架：`web/frontend/` 起 Next.js(App Router, TS) + `fumadocs-ui` + `next-themes` + `geist` 字体；`next.config.ts` 配 `output:'export'` + dev rewrite → `:26618`。
- [x] **Phase 3** — 设计 Token：`styles/tokens.css`（浅/深主题全部 CSS 变量）+ `app/layout.tsx` 挂 `RootProvider` + `ThemeProvider`。
- [x] **Phase 4** — API 层：`lib/api.ts` 按 §6 封装全部端口，含 `reserved` 降级、错误 toast、`?mock` 切换。
- [x] **Phase 5** — 后端新增 `/api/ask`：`core/adapters/llm.py` 扩展 `generate()` 方法；`core/api.py` 新增 `ask()` + `llm_adapter` 注入；`web/server.py` 注册路由 + SPA catch-all 静态服务。
- [x] **Phase 6** — 外壳：左栏 `rail`（Ask featured / 知识库分组 / 运维分组 / 设置+用户区）+ 7 个路由骨架页。
- [x] **Phase 7** — 文档工作台 `/documents`：三栏布局（集合列 / 文档表 / 检查器）+ 批量操作条 + 上传，无任何 `prompt()`。
- [x] **Phase 8** — 设置页 `/settings`：外观区（主题/语言/色系）+ `config/effective` 只读卡片。
- [x] **Phase 9** — 检索 `/search` + 配额 `/quota`。
- [x] **Phase 10** — Ask Agent `/ask`：对话 + 来源面板 + `[n]` 角标联动 + 「在文档中打开」跳转。
- [x] **Phase 11** — 图谱 `/graph` + 同步/备份 `/sync`；`reserved` 端口优雅降级。
- [x] **Phase 12** — 视效层（`components/fx`）：DotField / SunBloom / GrainOverlay / `.fx-glass`；`prefers-reduced-motion` 支持。
- [x] **Phase 13** — `tools/sync_frontend.py` 更新（支持 Next.js `out/`）+ `CLAUDE.md §5` 命令更新。
- [x] **Phase 14** — 测试补充：`/api/ask` 路由测试 + `ask()` 单元测试；新增 SPA catch-all 路由测试。
- [x] **Phase 15** — `metadata.yaml` 版本号 → `v0.10.0`，`CHANGELOG.md` 追加条目。

### Verification

- `python3 -m pytest tests/backend/test_api.py tests/backend/test_web_server.py` → ✅ 42 passed
- `ruff check . && mypy` → 无错误
- `cd web/frontend && npm run build` → ✅ Next.js export 成功，`out/` 产出 8 个页面
- `python tools/sync_frontend.py --check` → `pages/` 与 `out/` 一致
- 浏览器访问 `http://localhost:26618` → 完整 7 页面、双主题、中英 i18n、?mock 可用

---

## v0.9.0 Backend hardening without WebUI port changes (deferred)

> ❌ **已合并至 v0.11.0 统一实施**。由于开发顺序调整，v0.10.0 WebUI 重构先行落地，v0.9.0 的后端优化与健壮性改造顺延至 v0.11.0，并与 v0.10.0 遗留的 API 端口补齐合并执行。

### User constraints / 约束

- 本版本只纳入不会影响前端端口与现有 WebUI 入口结构的重要优化。
- 不修改 `web_console.host` / `web_console.port` 的运行语义。
- 不做 WebUI 大改版；前端设计优化由用户后续单独处理。
- 不执行任何 `git commit`，提交交给用户执行。

### Technical implementation path

- [x] **Phase 1 — 配置持久化收敛**：为 `RuntimeConfigStore` 增加更清晰的加载/覆盖/写回边界，并预留 AstrBot 原生配置写回适配口；技术理由：v0.8.0 已能回写 `database_id`，但当前落点是 `data_dir/runtime_config.json`，需要把运行时覆盖与框架配置的职责固定下来。
- [x] **Phase 2 — Notion schema 与分页健壮性**：补 `query_database` 分页、标准属性存在性检查、缺失属性诊断信息；技术理由：真实 Notion 数据库页数变多或属性被用户改名时，当前 pull/push 需要更清楚地失败或降级。
- [x] **Phase 3 — 同步状态可审计性**：增强 Notion init/pull/push 的结果统计与错误消息，保证 `sync_records` 与 API 返回能区分 skipped、failed、schema_missing、remote_missing；技术理由：后续排查同步问题时不能只看泛化 error。
- [x] **Phase 4 — 历史 TODO 清理**：修正 v0.1.0 历史残留状态，把已被 v0.2.0+ 覆盖的初始化工作闭环；技术理由：避免后续 agent 误判项目仍卡在初始化阶段。
- [x] **Phase 5 — 回归与契约测试补强**：补 Notion 分页、schema 缺失、运行时配置覆盖优先级、错误消息稳定性的单元测试；技术理由：这些优化都在后端内部，不应改变前端端口或现有 UI 使用方式。

### Verification

- `python3 -m pytest tests/backend/test_config.py tests/backend/test_notion_target.py tests/backend/test_web_server.py tests/backend/test_lifecycle_and_cli.py` → 待执行
- `python3 -m pytest` → 待执行
- `ruff check . && mypy` → 待执行
- `python3 tools/sync_frontend.py --check` → 待执行，确认前端静态产物仍一致

---

## v0.8.0 Notion 双向元数据 + 设置核对 (completed)

### User constraints / 约束

- 解决 Backlog 中两个 Notion 问题：自动建库与反向同步。
- WebUI 设置项只做只读核对，不做完整配置编辑器。
- 同步更新真实前端 `web/frontend/index.html` 与静态产物 `pages/index.html`。
- 不执行任何 `git commit`，提交交给用户执行。

### Technical implementation path

- [x] **Phase 1** — Notion 自动建库：新增 `notion_sync.parent_page_id` / `database_title` 配置，经 Notion MCP `create_database` 创建标准 Database，并将生成的 `database_id` 写入 `data_dir/runtime_config.json` 运行时覆盖配置。
- [x] **Phase 2** — Notion 反向同步：新增 pull 管线，只按 `DocID` 拉取 Notion 页面中的 `Collection` / `Tags` 并合并到本地文档；不覆盖标题、文件路径、content hash 或 PDF 原件，不做级联删除。
- [x] **Phase 3** — API/CLI 接线：新增 `GET /api/config/effective`、`POST /api/notion/init`、`POST /api/sync/notion/pull`，并 plumb `/kr notion init` 与 `/kr sync notion --pull`。
- [x] **Phase 4** — WebUI 设置核对：新增“设置核对”页，展示脱敏后的后端有效配置与前后端能力矩阵；同步/备份页新增 Notion 初始化和反向拉取按钮。
- [x] **Phase 5** — 测试与前端同步：补充配置、Notion target、Web API、CLI 生命周期测试，并同步 `web/frontend/` 到 `pages/`。

### Verification

- `python3 -m pytest tests/backend/test_config.py tests/backend/test_notion_target.py tests/backend/test_web_server.py tests/backend/test_lifecycle_and_cli.py` → 43 passed
- `python3 -m pytest` → 116 passed
- `ruff check . && mypy` → All checks passed / Success
- `python3 tools/sync_frontend.py --check` → pages/ 已与 web/frontend/ 一致

---

## v0.7.0 图谱可视化 + 检索预览进阶 (completed)

### User constraints / 约束

- 前端进阶：依赖 v0.5.0 独立 Web 控制台与 v0.6.0 图谱后端，把图谱与召回过程可视化。

### Technical implementation path

- [x] **Phase 1** — 后端图谱读接口补全：实现 `core/api.py::get_graph()` 与 `web/server.py` `/api/graph/data`，返回按 collection 过滤的 entities / relations / source chunk 引用；技术理由：前端图谱页不应直读 SQLite，必须走 API 门面。
- [x] **Phase 2** — 图谱可视化数据模型与测试：为 graph data JSON 增加稳定字段（node id/name/type/degree、edge relation/weight/source_chunk_ids），补 `tests/backend/test_api.py` 与 `test_web_server.py`；技术理由：先锁定前后端契约，避免 UI 反复适配。
- [x] **Phase 3** — 前端图谱视图：在 `web/frontend/index.html` 增加实体/关系交互图（原生 SVG/Canvas 或轻量 DOM，不引 npm），点击节点/边展示 source chunk 摘要；技术理由：延续 v0.5.0 零构建约束。
- [x] **Phase 4** — 图谱查询前端：接 `/api/graph/query`，展示 RRF 融合后的 chunks、matched entities、relations 和 academic context preview；技术理由：把 Phase 5/6 后端能力变成可检查的用户流程。
- [x] **Phase 5** — 检索预览增强：并排展示 KB 向量召回、实体关键词召回、1-hop 图邻域召回与最终 RRF 排序；技术理由：让调参时能判断是向量、实体匹配还是图扩展贡献了结果。
- [x] **Phase 6** — 前端同步与 smoke：运行 `python tools/sync_frontend.py` 同步到 `pages/`，补/跑 web smoke 测试；技术理由：独立 Web 控制台的发布产物必须与源码一致。

### Verification

- `python3 -m pytest tests/backend/test_api.py tests/backend/test_graph_store.py tests/backend/test_graph_search_pipeline.py tests/backend/test_web_server.py` → 46 passed
- `python3 -m pytest` → 111 passed
- `ruff check . && mypy` → All checks passed / Success
- `python3 tools/sync_frontend.py --check` → pages/ 已与 web/frontend/ 一致
- 打开图谱页 → 渲染实体/关系；点节点显示来源
- 输入 query → 图示融合召回路径

---

## v0.6.0 LightRAG 知识图谱 (completed)

### User constraints / 约束

- 用 LightRAG 增量式，规避 GraphRAG 高 LLM 成本（增量 ≈ $0.15 vs GraphRAG $4–7）。
- 仅对内容哈希变化的 chunk 抽取；实体嵌入复用 KB 既有 bge-m3；不生成社区报告。

### Technical implementation path

- [x] **Phase 1** — `repository/graph_store/base.py` ABC（实体/关系 upsert、邻域查询、契约 docstring）。
- [x] **Phase 2** — `graph_store/sqlite.py`（实体表+关系表+实体嵌入表）+ `memory.py`；`migrations/003_graph_store.sql`。
- [x] **Phase 3** — `pipelines/graph_build_pipeline.py`：变化 chunk → LLM 抽取 → 嵌入相似度归并 → upsert（增量）。
- [x] **Phase 4** — 混合查询：向量召回 + 图邻域扩展 + RRF 融合（对齐 AstrBot rrf_k）。
- [x] **Phase 5** — 命令 `/kr graph build`、`/kr graph query <q>`（薄壳一行委派）。
- [x] **Phase 6** — 领域本体预设与自定义引擎（Dynamic Ontology Preset & Customization Engine）：支持在 `GraphSyncConfig` 配置自定义 `entity_types` 列表，动态注入 LLM 抽取 Prompt 系统提示词并实现全链路类型过滤召回。

### Verification

- `python3 -m pytest` → 107 passed
- `ruff check . && mypy` → All checks passed / Success
- `git diff --cached --check` → 无 whitespace/EOF 问题
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

## v0.1.0 项目初始化 (completed)

### User constraints / 约束

- 基于通用项目框架模板，保留分层结构与治理三件套。

### Technical implementation path

- [x] **Phase 1 — 骨架**：复制模板，建立分层目录与治理文件。
- [x] **Phase 2 — 填空**：替换 `metadata.yaml` / `_conf_schema.json` / `pyproject.toml` / `CLAUDE.md` §5 命令占位。
- [x] **Phase 3 — 首个子系统**：按 `ARCHITECTURE.md` 的「新增子系统清单」落地第一个业务管线。

### Verification

- `python3 -m pytest` → 全绿
- `ruff check . && mypy` → 无错误

---

## 💬 待讨论 Backlog

> 以下条目均处于**待讨论**状态，尚未纳入任何版本计划。执行前须明确优先级、设计方案并获确认，以防与未来改动冲突。

### 功能 (Features)

- 💬 **自动分类（可优化项）**：在手动分类基础上，提供可选 LLM/embedding 聚类自动打标签（默认关，开启时成本警告）。v0.3.0 已留 ABC 口，后续可升级为正式版本。
- 💬 （示例）<在此登记尚未排期的功能想法。>

### 架构 / 清理 (Architecture / Cleanup)

- 💬 （示例）<在此登记需要讨论的重构/技术债。>
