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

## v0.20.1 LightRAG raw-text indexing path (in progress)

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

## v0.20.0 UX & retrieval overhaul (in progress)

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
- [ ] **Phase 3b（deferred 跟进）**：将 `core/api.py`（仍 ~1360 行，超 CONVENTIONS §4 红线）的 documents/retrieval/graph/sync 公共方法进一步拆为 mixin 子门面，并把 `plugin_initializer.initialize()` 分阶段化。理由：该门面耦合密集、被 web/event_handler/测试广泛依赖，宜在独立 session 单独评审与回归；本次优先交付前端可见价值，去重已完成。按 CONVENTIONS §4 以本条登记跟进。
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
