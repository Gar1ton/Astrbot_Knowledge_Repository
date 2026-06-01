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

## v0.14.0 Local retrieval & Ask Agent integration (planning)

### User constraints / 约束

- 本版本先完成方案讨论与验证，再进入业务代码实现；未获用户批准前不修改检索、AstrBot hook、WebUI 或持久化代码。
- 评估将向量检索改为插件本地运行，并以进程内、单文件持久化的 Milvus Lite 作为优先候选；AstrBot KB 读取保留为可回退或迁移期兼容路径。
- Ask Agent 需要支持 `/kr agent on|off`：打开后，AstrBot 普通对话可使用插件检索结果；关闭后不得影响原有 AstrBot 普通对话。
- Ask Agent 增加可选的“关系 persona”影响：打开时以真人 RA（Research Assistant）风格总结证据与结论，关闭时保持当前问答风格。WebUI 开关放在输入框底部集合选择器右侧。
- 外部 agent 与内部 agent 的边界尚待讨论；本计划先给出推荐职责划分，不提前固化 HTTP 或 AstrBot SDK 契约。
- 评估 NotebookLM 风格的“在线检阅文档”：回答必须能回到来源文档、定位证据片段并继续阅读，而不是只展示不可追溯的向量命中摘要。

### Technical implementation path

- [ ] **Phase 0 — Milvus Lite 可行性 spike 与基准**：用隔离原型验证 `pymilvus[milvus-lite]` 本地文件 URI、Linux 部署、单进程生命周期、dense vector CRUD、metadata filter、删除重建、混合检索、数据库文件备份恢复与异常重启；记录小规模边界、仅 `FLAT` 索引、无 partition / 用户角色等限制。单独验证当前 Milvus Lite 版本能否直接使用内建 BM25；官方资料存在版本差异，未通过原型前不得将该能力写入正式契约。技术理由：Milvus Lite 适合作为本地候选，但不能根据 Standalone 能力推断 Lite 行为。
- [ ] **Phase 1 — 定义本地检索端口与数据所有权**：新增独立 `retrieval` / `vector_store` ABC，明确 SQLite `source_store` 仍是文档与 chunk 的事实源，Milvus Lite 只是可重建索引；AstrBot KB reader 降为兼容 adapter，不再作为 Ask Agent 的唯一检索源。索引行至少保存 `chunk_id`、`doc_id`、`collection`、文本、内容哈希和可定位引用元数据。技术理由：避免把可丢弃索引与原始文档生命周期混为一体，并允许后续切换 Standalone。
- [ ] **Phase 2 — 明确本地 embedding 策略**：先比较本地 `bge-m3` 候选与可配置外部 embedding provider，确定模型下载、缓存目录、CPU / 内存占用、批量摄入耗时和离线启动降级；Milvus Lite 只保存和检索 dense vector，不承担 dense embedding 生成。技术理由：将向量库改成本地并不等于向量生成已经本地化，必须把模型运行成本纳入设计。
- [ ] **Phase 3 — 收敛索引生命周期与灾备**：上传、更新、删除文档时同步 upsert / delete 本地索引；提供按 chunk 哈希增量补建、全量 rebuild、健康检查与版本迁移；将 Milvus Lite 文件纳入 R2 快照范围，恢复后支持校验或从 SQLite 重建。技术理由：当前本地上传文档不会写入 AstrBot KB，改用本地索引后必须补齐一致性闭环。
- [ ] **Phase 4 — 统一 Ask retrieval orchestrator**：让 WebUI Ask、AstrBot 普通对话增强和后续外部工具调用共享一条检索管线；候选召回包含 local dense、可验证后再启用的 lexical / sparse 检索、实体召回和图邻域扩展，并统一去重、RRF、来源编号与引用结构。技术理由：当前 `ask()` 只查 AstrBot KB，而图谱查询另走独立管线，继续叠加入口会产生不同答案与不同引用。
- [ ] **Phase 5 — 接入 AstrBot 普通对话增强**：在真实 AstrBot SDK 薄壳注册 `/kr agent on|off` 与普通消息 hook；开关状态持久化，默认关闭。推荐按会话或频道记录开关，并提供原生配置中的全局默认值；开启时优先把检索上下文和引用注入 AstrBot 原有回答链路，避免额外生成一次 Ask Agent 答案后再让 AstrBot 二次改写。技术理由：保留 AstrBot 原有会话、persona 与 provider 行为，同时控制延迟和 token 成本。
- [ ] **Phase 6 — 增加 RA persona 模式**：为 Ask 请求和 AstrBot 内部增强上下文增加 `persona_enabled`；关闭时保留现有提示词，打开时使用关系 persona 模板，要求先归纳证据、再给出面向真人研究助理交流的总结，并保持来源引用。WebUI 在集合选择器右侧增加独立开关；后端配置提供默认值，单次请求允许覆盖。实施前与用户确认：这里是插件自带 RA persona，还是复用 AstrBot 已选 persona 并追加 RA 行为约束。技术理由：persona 影响应作用于最终回答提示词，不应污染检索排序。
- [ ] **Phase 7 — 明确内部 / 外部 agent 契约**：推荐将“内部 agent”定义为 AstrBot 普通对话中的检索增强器，只返回 grounded context 给 AstrBot 现有回答链路；将“外部 agent”定义为 WebUI / API 主动调用的独立问答入口，由插件负责检索与生成答案。后续如需供第三方 agent 调用，再增加只返回检索上下文的 tool/API，避免强制二次 LLM 生成。技术理由：共享检索核心，但让最终回答责任归属清晰。
- [ ] **Phase 8 — NotebookLM 风格在线检阅与引用定位**：为每个 chunk 持久化页码、段落或字符范围、原件引用和可展示预览；回答引用返回稳定 `doc_id + chunk_id + locator`，WebUI 支持从来源面板打开原件并定位到证据附近。评估 PDF.js 在线阅读器；Notion MCP 继续承担同步镜像，不作为本地检索或引用定位的必需依赖。技术理由：Milvus Lite 能提高召回，但在线阅览、证据定位和连续阅读属于应用层能力。
- [ ] **Phase 9 — 测试、文档与发布闭环**：补向量端口对换测试、Milvus Lite 集成测试、索引重建与 R2 恢复测试、AstrBot hook 桩测试、persona 提示词测试、引用定位 HTTP / WebUI 测试；更新配置 schema、架构说明、版本记录与前端静态产物。

### Decisions required / 待确认

- [ ] `/kr agent on|off` 的作用域：推荐“当前会话或频道”，是否还需要用户级和全局级命令。
- [ ] AstrBot 普通对话增强方式：推荐“注入检索上下文，由 AstrBot 原链路生成一次答案”；是否还需要“先调用独立 Ask Agent，再直接引用其答案”的可选模式。
- [ ] “关系 persona”的来源：推荐插件内置 RA 模板并允许叠加 AstrBot 当前 persona；是否需要读取并完全继承 AstrBot persona。
- [ ] 外部 agent 首版范围：推荐先保留 WebUI `/api/ask`，并增加只返回 grounded context 的工具契约设计；是否需要同步暴露 MCP tool。
- [ ] 本地 embedding 的目标：需要确认优先级是“完全离线”、低内存 CPU 运行，还是优先复用用户已有 embedding provider 以降低安装体积。

### Verification

- `python3 -m pytest tests/backend` → 待实现后执行
- `ruff check . && mypy` → 待实现后执行
- `cd web/frontend && npm run lint && npm run build` → 待实现后执行
- `python3 tools/sync_frontend.py && python3 tools/sync_frontend.py --check` → 待实现后执行
- Milvus Lite spike：摄入、查询、更新、删除、重启、快照恢复、全量 rebuild、异常恢复 → 待执行并记录基准
- AstrBot 人工验收：`/kr agent off` 不影响普通对话；`/kr agent on` 后普通对话带可追溯引用；RA persona 开关只改变回答表达 → 待执行

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
- `curl http://localhost:3000/{ask,documents,search,graph,sync,settings}` → 动态预览路由均返回 HTTP 200
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
- 浏览器逐张对照 `docs/屏幕截图 2026-06-01 133003.png` 至 `133036.png` → 动态预览已启动于 `http://localhost:3000/`

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
- [x] **Phase 2** — 脚手架：`web/frontend/` 起 Next.js(App Router, TS) + `fumadocs-ui` + `next-themes` + `geist` 字体；`next.config.ts` 配 `output:'export'` + dev rewrite → `:6520`。
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
- 浏览器访问 `http://localhost:6520` → 完整 7 页面、双主题、中英 i18n、?mock 可用

---

## v0.9.0 Backend hardening without WebUI port changes (deferred)

> ❌ **已合并至 v0.11.0 统一实施**。由于开发顺序调整，v0.10.0 WebUI 重构先行落地，v0.9.0 的后端优化与健壮性改造顺延至 v0.11.0，并与 v0.10.0 遗留的 API 端口补齐合并执行。

### User constraints / 约束

- 本版本只纳入不会影响前端端口与现有 WebUI 入口结构的重要优化。
- 不修改 `web_console.host` / `web_console.port` 的运行语义。
- 不做 WebUI 大改版；前端设计优化由用户后续单独处理。
- 不执行任何 `git commit`，提交交给用户执行。

### Technical implementation path

- [ ] **Phase 1 — 配置持久化收敛**：为 `RuntimeConfigStore` 增加更清晰的加载/覆盖/写回边界，并预留 AstrBot 原生配置写回适配口；技术理由：v0.8.0 已能回写 `database_id`，但当前落点是 `data_dir/runtime_config.json`，需要把运行时覆盖与框架配置的职责固定下来。
- [ ] **Phase 2 — Notion schema 与分页健壮性**：补 `query_database` 分页、标准属性存在性检查、缺失属性诊断信息；技术理由：真实 Notion 数据库页数变多或属性被用户改名时，当前 pull/push 需要更清楚地失败或降级。
- [ ] **Phase 3 — 同步状态可审计性**：增强 Notion init/pull/push 的结果统计与错误消息，保证 `sync_records` 与 API 返回能区分 skipped、failed、schema_missing、remote_missing；技术理由：后续排查同步问题时不能只看泛化 error。
- [ ] **Phase 4 — 历史 TODO 清理**：修正 v0.1.0 历史残留状态，把已被 v0.2.0+ 覆盖的初始化工作闭环；技术理由：避免后续 agent 误判项目仍卡在初始化阶段。
- [ ] **Phase 5 — 回归与契约测试补强**：补 Notion 分页、schema 缺失、运行时配置覆盖优先级、错误消息稳定性的单元测试；技术理由：这些优化都在后端内部，不应改变前端端口或现有 UI 使用方式。

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
