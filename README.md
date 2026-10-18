<div align="center">

<img src="./logo.svg" width="96" alt="Knowledge Arch Logo" />

# Knowledge Arch

**AstrBot 知识库原件管理、同步备份与 Research Agent 插件**

[![version](https://img.shields.io/badge/版本-v1.2.0-blueviolet)](metadata.yaml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-plugin-6f42c1)](https://github.com/AstrBotDevs/AstrBot)

*PDF 原件库 · Zotero 同步 · 六档检索 · Harvard 引用 · LightRAG 图谱 · Notion / R2 · 独立 WebUI*

</div>

---

## 这是什么

Knowledge Arch 为 AstrBot 增加一个面向资料、论文和长期知识沉淀的独立知识库应用。它以 PDF 等原件为中心，提供文档上传、集合分类、Zotero 镜像、Notion / R2 同步备份、多档检索问答和 LightRAG 知识图谱能力，并通过独立 Web 控制台完成日常管理。

核心亮点：

- **原件优先的知识库管理**：保留 PDF 原件、逐页原始抽取与清洗后的 clean markdown，脚注单独保留并可回读；支持集合、标签、元数据、笔记与分块检查。
- **六档检索模式**：从快速查证、整篇精读到多轮深度推演，按问题复杂度选择成本档位（见[检索模式](#六档检索模式)）。
- **Research Agent 问答**：在 AstrBot 对话中直接自然语言提问，先探查范围再召回；答案自带由代码生成的 **Harvard 引用**，WebUI 内以 Markdown 渲染，点击短引即可跳到来源片段。
- **Zotero 资料同步**：本地 Zotero 与 Zotero Web API 双模式，collection 树镜像为插件集合树；三种同步模式控制删除语义，回收站内容自动剔除，含换号保护。
- **LightRAG 图谱**：按集合构建 workspace，支持纯图谱查询与「语义/词法证据 + 图谱上下文」混合检索。
- **同步与备份**：Cloudflare R2 保存可跨设备恢复的完整快照；Notion 通过 MCP v2 镜像元数据，本地变更自动推送，并自动标记「已做笔记」的文章。
- **索引自动维护**：新文档入库、换 embedding、插件升级后，Milvus 向量索引按需自动重切、重建，不必再手动点按钮。
- **灵活的 Embedding 来源**：本地 sentence-transformers、OpenAI 兼容外部服务，或直接复用 AstrBot 已配置的 Embedding Provider。
- **Codex Skill**：把 Codex / Claude Code 当推理层，插件只做确定性检索（`plugin_llm_used=false`），一次注册即可让 agent 直接研究你的本地文献库（见 [Codex Skill](#codex-skill)）。
- **独立 WebUI**：默认端口 `26618`，内置登录鉴权，中英双语，覆盖文档、问答、图谱、同步、配额、设置、数据流诊断、显存面板与可过滤的终端日志。

---

## v1.2.0 有什么新变化

> 上一个正式版是 v1.1.1。以下汇总 v1.1.2 – v1.2.0 的主要变化，完整条目见 [CHANGELOG.md](./CHANGELOG.md)。

| 方向 | 变化 |
|------|------|
| 清洗与切片 | 新清洗流水线（`cleaning-v3`）：去除页眉页脚、出版噪声与 JSTOR 类数据库访问水印，修复跨页断句；脚注单独保留、全文阅读时补回；切片改为章节 + token 软目标边界，chunk ID 带修订号，旧引用不会串到新正文 |
| 增强 / 深度回答 | 证据会话复用同一请求内的检索、embedding 与重排结果，按「方面」覆盖选证据，并在预算内读取相邻正文和脚注；`enhanced` 改为答案先行的中等篇幅，不再套用 deep 的长报告模板 |
| 回答呈现 | 聊天回答以安全 Markdown 渲染（标题、列表、粗体、代码块）；参考文献不再重复打印文件名里的作者、年份和 `.pdf` |
| Harvard 引用 | Zotero 独立附件与本地上传的 PDF 可从 `作者 (年份) - 标题.pdf` 形式的文件名提取书目信息，大幅减少 `Anon., n.d.`；Zotero 权威数据永远优先 |
| 向量索引 | 新增自动重建调度器（事件驱动 + 防抖 + 启动补跑 + 失败退避）；插件升级导致处理版本过期的旧文档会自动重切并重建一次 |
| Milvus 稳定性 | 插件热重载、AstrBot 重装依赖后正确释放 Milvus Lite 服务与文件锁；启动失败时数据流面板直接显示真实原因与恢复提示 |
| Embedding | 新增 `embedding.provider = astr` 复用 AstrBot Embedding Provider；外部服务同时支持 API base 与完整 `/embeddings` 端点，严格校验返回维度与数量，错误信息脱敏 |
| Notion | 迁移到 `@suekou/mcp-notion-server@2.0.2` / Data Source API；本地变更 10 秒合并自动推送、300 秒周期补查；自动勾选「已做笔记」；接口预检与失败账本在 WebUI 可见 |
| Zotero | 回收站里的集合及其子集合不再被镜像；`strict_mirror` / `conservative` 删除语义按名称纠正（见下方升级须知） |
| 全文检索 | `fulltext` 模式端到端可用：读取整篇正文、不截断，超长文档先确认再发送 |
| 界面 | 英文界面不再夹杂中文（i18n 补齐 116 处） |
| Codex Skill | 新增 `index-status` / `index-rebuild`；`read --whole` 读到文末，超长读取需 `--confirm-large-read` |

### 从 v1.1.x 升级须知

1. **Zotero `sync_mode` 删除语义变化（破坏性）**。旧版本中两个模式的行为与名称相反，v1.2.0 已纠正：
   - `strict_mirror`：Zotero 中删除的文档会被**硬删除**（文档记录、向量、LightRAG 全清）；
   - `conservative`（默认）：删除的文档标为 `detached`，保留记录与制品，仅移除向量索引。

   原先使用默认模式的用户，此后 Zotero 删除的文档会留在库里为 detached，需手动清理或切到 `strict_mirror`；已被旧版本硬删的文档不会恢复。
2. **Notion 需要升级宿主 MCP**。使用 Node.js 22+，把 AstrBot MCP 启动包锁为 `@suekou/mcp-notion-server@2.0.2`，并按需重新填写 Articles / QA 的容器与 Data Source ID。插件不会自动修改宿主 MCP 配置，也不迁移旧库映射。步骤见 [Notion 同步指南](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/docs/NOTION_SYNC.md)。
3. **旧文档会自动重切一次**。首次启动时，处理版本过期的文档会被标记待重建，由自动重建调度器在后台重切 chunk 并写入向量索引；文档多时会占用一段 embedding 算力。新的水印清洗与脚注保留需要重新抽取原件才能生效：在「文档」页对单篇执行重新抽取，或重新导入。
4. **Milvus 锁定的处理方式变了**。旧版的「清除锁定」按钮已改为只读恢复说明；遇到数据目录被占用时，请**完整退出 AstrBot 再启动**，不要手动删除锁文件。

---

## 快速开始

### 安装

**方式一：AstrBot 插件市场**（推荐）

在 AstrBot 管理面板的插件市场中搜索 `astrbot_plugin_knowledge_repository`，安装后重启 AstrBot。

**方式二：手动克隆**

```bash
cd <AstrBot 数据目录>/plugins
git clone https://github.com/Gar1ton/Astrbot_Knowledge_Repository astrbot_plugin_knowledge_repository
```

仓库默认分支 `main` 只包含正式发布版本，因此上述命令不会安装开发期测试、设计稿或前端源码。
参与开发时请改用 `developer` 分支，见文末开发指引。

重启 AstrBot 后，插件会按需初始化数据库、迁移和 Web 控制台资源。兼容 AstrBot `>=4.5.7,<5`。

### 基础配置

在 AstrBot 管理面板 -> 插件配置 -> Knowledge Arch 中至少配置：

| 配置键 | 说明 |
|--------|------|
| `web_console.enabled` | 是否启用独立 Web 控制台 |
| `web_console.port` | Web 控制台端口，默认 `26618` |
| `web_console.username` | 登录用户名，默认 `admin` |
| `web_console.password` | 登录密码；建议用环境变量 `KR_WEB_PASSWORD` 注入，留空会拒绝启动 WebUI |

> AstrBot 面板只承载 Web 控制台、R2、Notion、Embedding 四组基础配置；
> Zotero、LightRAG 图谱、向量索引与检索调优在 **WebUI 设置页 / 数据流页**配置，持久化到 `runtime_config.json`。

机密一律优先从环境变量读取，不写进配置文件：

| 环境变量 | 用途 |
|----------|------|
| `KR_WEB_PASSWORD` | Web 控制台密码 |
| `KR_R2_SECRET_ACCESS_KEY` | R2 Secret Access Key |
| `KR_EMBEDDING_API_KEY` | 外部 Embedding API Key（仅 `embedding.provider = external`） |
| `KR_LIGHTRAG_LLM_API_KEY` | LightRAG 专用 LLM API Key |
| `KR_DEEP_THINKING_LLM_API_KEY` | 深度思考专用 LLM API Key |
| `KR_ZOTERO_API_KEY` | Zotero Web API Key（server 模式） |

Notion 不在插件内持有 token：同步经 AstrBot 已配置的 Notion MCP server 进行，token 由 MCP 侧管理。

### 可选依赖

AstrBot 自动安装的 [`requirements.txt`](./requirements.txt) 只包含基础运行依赖。下列能力需要 [`requirements-additional.txt`](./requirements-additional.txt)，可整体 pip 安装，也可以在 WebUI「数据流」页对缺失依赖**一键安装**（白名单内）：

```bash
pip install -r requirements-additional.txt
```

| 能力 | 依赖说明 |
|------|----------|
| 本地 Embedding / Rerank | `sentence-transformers`，用于本地向量模型与本地 cross-encoder 重排（Embedding 用 `external` / `astr` 且不用本地重排时可不装） |
| LightRAG 图谱 | `lightrag-hku`，用于图谱构建、纯图谱查询与图谱混合检索 |
| Cloudflare R2 | `boto3`，用于原件与数据库备份 |

### 验证插件生效

1. 打开 `http://<服务器IP>:26618`，使用配置的用户名和密码登录。
2. 在「文档」页上传 PDF（上限 200MB），确认文档进入集合并完成抽取；向量索引会在后台自动写入。
3. 在「Research Agent」页提问，或发送 `/ka research on` 后在 AstrBot 对话中直接提问，确认回答引用了知识库资料。
4. 可选：在「数据流」页检查 Zotero、Embedding、Milvus、LightRAG、Notion 等模块的就绪状态。

---

## 使用指南

### 插件在做什么

| 流程 | 行为 |
|------|------|
| 上传 / 同步资料 | 保存原件，逐页抽取并清洗为 markdown，保留脚注，按章节与 token 边界切分 chunks，写入 SQLite 源库 |
| 集合与标签管理 | 本地集合可编辑；Zotero 集合只读镜像；检索和图谱范围包含选中集合及后代 |
| 向量索引 | 入库即时写入 Milvus；兼容性变化或失败时排入待重建队列，由自动重建调度器在后台排空 |
| 对话增强 | `/ka agent on` 时把召回片段注入主 LLM（被动 grounding）；主动检索用自然语言触发 research skill |
| 图谱构建 | 对集合及其后代文档构建单一 LightRAG workspace，支持暂停、恢复、取消和历史状态 |
| 同步备份 | R2 以内容寻址快照备份全部插件持久化数据；Notion 镜像文档元数据并标记笔记；Zotero pull 同步文献库 |

### 六档检索模式

WebUI 问答页与聊天面板提供全部六档；AstrBot 对话中的 research 工具使用前五档。**按需选最低档**——档位越高，内部 LLM 调用越多、耗时越长：

| 模式 | 适用场景 | 成本 | 范围要求 |
|------|----------|------|----------|
| `default` | 查存 / 单点事实，最快（保留 6 条证据） | ★ | 可全局 |
| `enhanced` | 分析、对比、机制类问题：一次拆解 + 宽召回 + 证据会话 + 自检纠偏，答案先行、篇幅适中 | ★★ | 可全局 |
| `deep_thinking` | 综述、系统梳理级任务：多轮迭代推演 + 校验 | ★★★★ | 需绑定集合 |
| `graph_mixed` | 语义/词法证据 + LightRAG 图谱上下文混合 | ★★★ | 需绑定集合 |
| `graph_only` | 纯图谱检索，只用实体关系上下文 | ★★ | 需绑定集合 |
| `fulltext` | 针对单篇文献精读：整篇正文直接送入 LLM，不截断 | 随篇幅 | 需选定一篇文档 |

> - 图谱两档需要先在「LightRAG 图谱」页对目标集合完成构建。配置了 cross-encoder reranker 时，各模式自动「宽召回 → 重排」。
> - `fulltext` 正文超过 60 000 字符时会先弹出确认框，显示字符数与估算 token；确认前不调用 LLM、不写入聊天记录。答案只带一条文档级 Harvard 引用（无页码）。

### 对话式 research（中英双语）

发送 `/ka research on` 开启后，直接在对话中提问即可：

1. 主 LLM 先用 `research_scope_probe` 探查范围（命中的论文 / 集合 / 标签）；
2. 范围明确直接召回作答，模糊则先告诉你范围与建议模式、征求确认；
3. 答案正文里的论断直接跟 Harvard 短引 `(作者, 年份, p. 页码)`，尾部附去重排序的「参考文献」表。

默认英文召回、按提问语言作答（可用 `/ka research_language` 固定）。两个工具均只读，不会修改任何同步配置。

### 引用格式（Harvard）

三条出口——WebUI 问答、AstrBot 聊天、Codex Skill——统一使用 Cite Them Right 风格的 Harvard 引用，
且**由代码确定性生成**：模型只负责在正文里标记引用位置，作者、年份、页码全部由插件按来源元数据
填充，因此不存在编造作者或年份的可能。

- **正文内**：`(Vaswani et al., 2017, p. 3)`；页码取自命中 chunk 的元数据，跨页时为 `pp. 3-5`。
  相邻引用合并为 `(A, 2020; B, 2021)`。4 位及以上作者缩写为 `et al.`。
- **参考文献表**：答案尾部按首作者姓氏字母序、按文档去重，形如
  `Vaswani, A., Shazeer, N. and Parmar, N. (2017) 'Attention is all you need', NeurIPS. doi: 10.…`。
- **元数据缺失时**：降级为标准 Harvard 占位 `(Anon., n.d., p. 2)`，不会伪造。

书目字段的来源，按优先级：

1. **Zotero 同步镜像**：作者、年份、期刊、DOI 齐全，始终优先；
2. **手工填写**：「文档 → 元数据」里的作者 / 年份 / 期刊 / DOI；
3. **文件名解析**：文件名形如 `Peng, Hou and Zhou (2026) - Title.pdf` 或 `Author - 2021 - Title.pdf` 时，
   自动提取作者、年份与干净标题，只填补前两者的空缺；解析不确定时不猜。

> 在 WebUI 里点击正文中的任意 Harvard 短引，可直接跳转到对应的来源片段。

### /ka 指令速查

聊天端只保留运营控制面；内容管理（文档/集合/标签/图谱）请在 WebUI 操作。开关均持久化，重启保留。

| 指令 | 说明 |
|------|------|
| `/ka help` | 指令一览 |
| `/ka status` | 服务框架概览（所用模型 / 各服务 / 运行时开关） |
| `/ka agent <on\|off>` | 开关知识库召回注入 AstrBot 回复 |
| `/ka research <on\|off>` | 开关自然语言 research skill |
| `/ka research_language <cn\|en\|cn&en>` | research 回答语言（`cn&en`=跟随提问，默认） |
| `/ka persona <on\|off>` | 开关 AstrBot 人格 prompt（off 时不污染 research 精度） |
| `/ka zotero pull` | 触发一次 Zotero 增量同步 |
| `/ka zotero account <replace\|cancel>` | 处理 Zotero 换号确认（见下） |
| `/ka r2 <push\|status>` | R2 增量备份 / 用量查询 |
| `/ka r2 pull` | 登记恢复远端快照（需二次确认） |
| `/ka r2 force <push\|pull>` | 全量覆盖上传 / 整库恢复并自动软重启（均需二次确认） |
| `/ka notion <push\|status>` | Notion 单向增量推送 / 查看同步状态 |
| `/ka notion force push` | 忽略增量记录、全量重推所有文章（需二次确认） |
| `/ka webui <on\|off>` | 实时启停 Web 控制台 |

### R2 完整备份与跨设备恢复

采用内容寻址快照协议（`knowledge-arch/v1/`）：每次 `push` 生成完整清单但只上传远端缺失的 blob，`latest.json` 最后提交——任何中途失败都不会破坏上一份可恢复快照。

- **备份包含**：SQLite 一致性快照（文档/集合/笔记/聊天/同步/构建状态）、原件库与抽取产物、Milvus / LightRAG / embedding 缓存索引、可移植的非机密运行配置。
- **明确排除**：所有 API key 与密码、`secrets/`、依赖包、模型缓存、日志、临时文件、端口与设备绝对路径。

跨设备恢复：新设备装好插件和依赖、配置同一 Bucket 的 R2 凭据后，在设置页点「一键恢复」或执行 `/ka r2 force pull`——插件会下载并校验全部 blob（manifest、SHA-256、路径安全、SQLite integrity）再自动软重启；恢复失败自动回滚旧环境。

> **恢复是整体覆盖，不做增量合并。** 执行前用 `/ka r2 status` 或设置页确认远端 latest 快照是需要的版本。

### Zotero 同步

在 WebUI 设置页 / 数据流页启用。两个维度相互独立：

| 维度 | 选项 |
|------|------|
| 访问方式 `access_mode` | `local`：读取本机 Zotero 数据库；`server`：经 Zotero Web API（需 `KR_ZOTERO_API_KEY`） |
| 原件存放 `storage_mode` | `managed_copy`：PDF 复制进插件制品包；`linked`：PDF 留在 Zotero storage 根目录；`zotmoov`：PDF 留在 ZotMoov 移动后的目录 |

同步模式 `sync_mode` 决定 Zotero 中删除的条目如何处理：

| 模式 | Zotero 已删文档 | 重建开销 |
|------|----------------|----------|
| `strict_mirror` | 硬删除（文档记录、向量、LightRAG 全清） | 触发 Milvus 重建 |
| `conservative`（默认） | 标为 `detached`：保留记录、制品与 LightRAG，仅移除向量索引 | 轻量 |
| `archive` | 保留并继续可被检索 | 最少 |

- 集合树始终与 Zotero 保持一致：Zotero 中删除或移入回收站的集合（含其全部子集合）会在下次同步时移除，文档本身按上表处理。
- 可选开启 `zotero_sync.auto_sync_enabled` 定时拉取（默认关，间隔 3600 秒），或随时 `/ka zotero pull`。

**换号保护**：同一账号换 token 直接生效；检测到 token 属于**不同账号**时，同步会被阻止并要求确认：`replace` 只清空 Zotero 来源的本地镜像（本地上传的文档与集合保留）并自动开始新账号完整拉取；`cancel` 保留旧 token 和全部数据。WebUI 有对应的确认弹窗。

### Notion 同步

Notion 是可读的元数据镜像，不是备份：Articles 库只写属性（标题、作者、集合等），**不改写你在页面里写的正文**；QA 库保存问答。

- **前置条件**：AstrBot 中配置 Notion MCP server，Node.js 22+，启动包锁为 `@suekou/mcp-notion-server@2.0.2`。每轮同步前插件会预检工具能力，接口不兼容时直接停止并说明原因。
- **初始化**：可复用已有 Articles / QA 数据库并自动回填 Data Source ID；也可清空目标 ID、填写已授权的 `parent_page_id`，在「设置 → 同步 / 备份 → Notion 同步」点「初始化数据库」由插件新建。
- **自动同步**（默认开）：已提交的本地变更安静 10 秒后合并推送，每 300 秒周期补查一次；`auto_sync_interval_sec = 0` 只关周期补查，`auto_sync_enabled` 关闭全部自动推送，手动同步始终可用。
- **「已做笔记」标记**：插件按固定规则（不调用模型）读取正文，页面有非空正文内容时勾选 `已做笔记` checkbox；只勾选、不自动取消。在 Notion 中新建一个按该列筛选的视图即可一键查看。
- **清理策略** `sync_mode`：`preserve`（默认）保留已脱离的页面；`strict` 将其移入 Notion 回收站。
- **消耗**：同步不使用 LLM 或 embedding，模型 token 恒为 0；任务结果显示 MCP 调用次数与耗时。失败明细见设置页的同步账本。

完整的升级、初始化与消耗说明见 [Notion 同步指南](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/docs/NOTION_SYNC.md)。

### 向量索引自动维护

- **自动重建**：文档被标记待重建（上传时索引失败、Zotero 遇到不兼容索引、换 embedding、移动集合、重新抽取等）后，调度器静默 `vector_db.auto_rebuild_delay_seconds`（默认 30 秒）没有新变动才开跑，Zotero 批量同步的上百次信号会合并为一次重建。插件启动时也会补跑一次，排空积压队列。
- **与手动按钮共用同一任务**：自动重建与「重建索引」按钮走同一个 job 和进度条，不会并发起第二次。
- **失败退避**：失败后按 60 秒起、翻倍、封顶 1 小时退避；连续 6 次零进展后暂停，等待新信号再继续，避免坏 PDF 引发重建风暴。
- **开关**：`vector_db.auto_rebuild_enabled`（默认开），改动即时生效，无需重启。

### WebUI 面板导览

| 页面 | 路径 | 说明 |
|------|------|------|
| 总览 / 工作台 | `/` | 文档、笔记、聊天与操作面板的综合入口 |
| 文档 | `/documents` | 文档表、元数据、分块、PDF 预览、笔记与单篇重新抽取 |
| Research Agent | `/ask` | 带引用来源的知识库问答，六档模式可选，回答以 Markdown 渲染 |
| LightRAG 图谱 | `/graph` | 图谱构建（可暂停/恢复/取消）、实体关系查询与统计 |
| 检索 | `/search` | 知识库检索与召回调试 |
| 同步 / 备份 | `/sync` | Zotero、Notion、R2 同步入口与任务进度 |
| 配额 | `/quota` | R2 等同步目标的用量与风险提示 |
| 设置 | `/settings` | 有效配置、外观、同步配置、Notion 失败明细与运行状态 |
| 数据流 | `/flow` | 各模块依赖、配置、健康状态、故障原因与依赖一键安装 |
| 终端日志 | `/terminal` | 运行日志：级别/分类/关键词过滤、错误跳转、堆栈折叠、复制导出 |
| 显存与本地模型 | 顶栏「显存」 | embedding / rerank 驻留状态、显存占用，单个或全部一键卸载 |

---

## Codex Skill

插件随发行包附带一个 **project-level skill**：`.agents/skills/operate-knowledge-arch/`。
它的定位与插件内置的 research 问答**正好相反**：

> 让 **Codex / Claude Code 做推理层**，插件只提供确定性的本地证据。

技能只调用 `/api/ask/evidence` 这类「不产生答案」的端点，返回体固定带
`plugin_llm_used=false`、`full_text_used=false`；问题拆解、充分性判断、纠偏轮次与最终合成
全部由 agent 完成。它被明确禁止调用会产生答案的 `/api/ask`。

### 安装与注册

1. **装依赖**（只需一次，密码要存进系统钥匙串）：

   ```powershell
   python -m pip install -r requirements-codex-skill.txt
   ```

   > 技能本身是 stdlib-only 的单文件脚本，唯一的外部依赖是 `keyring`。
   > 技能不会自动帮你装依赖——这是刻意的。

2. **查看当前连接状态**：

   ```powershell
   python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py connection-status
   ```

   返回 `configured` / `environment_override` / `unconfigured` 三态之一。

3. **首次注册**（交互式，会依次询问 WebUI 地址、用户名、密码；密码输入不回显）：

   ```powershell
   python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py connection-setup
   ```

   注册会先用一次 `doctor` 校验连通性，通过后才落盘。

### 凭据存在哪

| 内容 | 位置 |
|------|------|
| 地址与用户名 | Windows `%APPDATA%/Codex/knowledge-arch/connection.json`；macOS `~/Library/Application Support/Codex/knowledge-arch/connection.json`；Linux `$XDG_CONFIG_HOME/codex/knowledge-arch/connection.json`（POSIX 下自动 `chmod 0600`） |
| 密码 | **只进系统凭据管理器**（`keyring`，服务名 `knowledge-arch.codex.connection.v1`），永不落盘到配置文件 |

临时切换目标实例：同时设置 `KNOWLEDGE_ARCH_URL` 与 `KNOWLEDGE_ARCH_USERNAME` 环境变量即可
（关闭鉴权的实例可另配 `KR_WEB_PASSWORD`）。环境变量覆盖**永不持久化**，也绝不会把已注册实例的
密码带给临时目标。

### 命令速查

| 分类 | 命令 |
|------|------|
| 连接 | `connection-status`、`connection-setup`、`doctor` |
| 检索 | `catalog`、`ask-evidence`（研究主路径）、`search`（仅用于排障）、`read`（受意图门控的全文分页；`--whole` 读到文末，超长读取需 `--confirm-large-read`） |
| Notion | `notion-save-qa`（把选定问答推送到已配置的 QA 数据库） |
| LightRAG | `graph-estimate`、`graph-build`、`graph-next`、`graph-submit`、`graph-retry`、`graph-status` |
| 向量索引 | `index-status`（待重建数、当前任务、兼容性）、`index-rebuild`（先预览、`--apply` 才触发，可 `--wait` 等待结束） |
| 配置 | `config-show`、`config-options`、`config-set`（先预览、`--apply` 才写）、`restart` |

典型研究调用：

```powershell
python .agents/skills/operate-knowledge-arch/scripts/knowledge_arch_client.py ask-evidence `
  --question "原始问题" --query "聚焦检索词" --mode enhanced --collection PapersCollection
```

每条证据都带 `harvard_in_text` 与 `harvard_reference` 两个服务端渲染好的引用串，agent 直接原样
使用即可，无需（也不允许）自造引用格式。

### 安全边界

技能把检索到的正文一律当作**证据而非指令**；禁止直接改写 SQLite / `runtime_config.json` / 源码 /
密钥；任何配置变更或索引重建必须先预览、经你确认后才能 `--apply`；重启是需要单独确认的第二次变更。
`index-rebuild --wait` 超时只表示停止观察，重建仍在后台进行。

> **Windows 沙箱**：若遇到 `windows sandbox: helper_unknown_error: apply deny-read ACLs`，
> 按 SKILL.md 的说明授予该次调用作用域内的批准即可，不要去改目录 ACL。

---

## 高级配置与调优

### 模块开关一览

| 功能 | 配置位置 | 默认 |
|------|----------|------|
| Web 控制台 | AstrBot 面板 `web_console.enabled` | 关 |
| R2 备份 | AstrBot 面板 `r2_sync.enabled` | 关 |
| Notion 镜像 | AstrBot 面板 `notion_sync.enabled`（开启后自动同步默认开） | 关 |
| Embedding 提供方 | AstrBot 面板 `embedding.provider`（`local` / `external` / `astr`） | `local` |
| Zotero 同步 | WebUI 设置页 / 数据流页 | 关 |
| LightRAG 图谱 | WebUI 设置页 / 数据流页 | 关 |
| 向量索引自动重建 | WebUI 数据流页 `vector_db.auto_rebuild_enabled` | 开 |

几个排障时常用的调参键（均在 WebUI 设置页可改）：

| 配置键 | 默认 | 作用 |
|--------|------|------|
| `embedding.device` | `auto` | `auto` / `cpu` / `cuda` / `cuda:N`。显式写 `cuda` 而 CUDA 不可用时**直接报错**，不再静默退回 CPU 造成「慢得莫名其妙」 |
| `embedding.load_timeout_seconds` | 180 | 首次加载（含下载权重）的等待上限，仅对尚未加载时的那次调用生效 |
| `vector_db.auto_rebuild_delay_seconds` | 30 | 自动重建的防抖窗口（下限 5 秒），即时生效 |
| `ask.llm_timeout_seconds` | 300 | 单次 LLM 调用超时 |
| `ask.task_timeout_seconds` | 900 | 一次 Ask 的任务级总超时。到点只是**放弃等待**、不取消后台任务：答案仍会写入历史，前端自动补拉回来 |

### Embedding 的三种来源

| `embedding.provider` | 说明 |
|----------------------|------|
| `local`（默认） | 本机 sentence-transformers，默认模型 `intfloat/multilingual-e5-small`；需安装可选依赖 |
| `external` | OpenAI 兼容的 `/embeddings` 服务。`embedding.base_url` 可填 API base（如 `https://api.openai.com/v1`）或完整的 `/embeddings` 端点，代理路径前缀会保留；API Key 经 `KR_EMBEDDING_API_KEY` 注入。插件严格校验返回数量、顺序与维度，首批成功后锁定维度，错误信息不含凭据 |
| `astr` | 复用 AstrBot 已配置的 Embedding Provider，见下 |

更换 provider、模型或维度后，旧的 Milvus / LightRAG 索引会被判为不兼容，并由自动重建接管。

### 复用 AstrBot 已配置的 Embedding（`embedding.provider = astr`）

已经在 AstrBot「模型提供商」里配好 Embedding 模型的话，不必在本插件里重复配一遍：

```json
{
  "embedding": {
    "provider": "astr",
    "astrbot_provider_id": "my_embedding_provider"
  }
}
```

- `astrbot_provider_id` 是 AstrBot「模型提供商」里那条 **Embedding Provider 的 ID**（不是模型名）。
  API Key、API Base、模型名、维度、代理与超时**全部由 AstrBot 管理**，本插件不保存任何副本，
  `KR_EMBEDDING_API_KEY` 在此模式下不需要；`embedding.model` / `embedding.base_url` 被忽略。
- 留空 ID 时：AstrBot 里**恰好有一个**已启用的 Embedding Provider 才会自动选用；有多个或没有都会
  在诊断里明确报错，**不会静默取第一个**。只允许 Embedding 类型的 provider，填成聊天/重排/语音会被拒绝。
- 本插件只通过 AstrBot 的 `EmbeddingProvider` 抽象（`get_embedding` / `get_embeddings` / `get_dim`）
  取向量，不直接调用任何服务商 API。**实际兼容性取决于对应 AstrBot provider 是否正确实现了这一契约**；
  输入格式、批量上限、向量维度与超时都由该 provider 决定。本插件不会截断、填充或转换维度不一致的向量，
  返回空向量、数量不符或维度不符时会报错并给出修复建议。
- **更换 provider 或其模型后需要重建向量索引**：provider ID、adapter 类型、模型名（provider 自己报告时）
  与实测维度都会进入索引指纹，任一变化都会把旧索引判为不兼容并走重建流程。
  注意：AstrBot 的 OpenAI / Gemini 类 Embedding provider 不向外报告模型名，此时只改模型名而 ID 与维度
  不变，插件**无法察觉**，请手动重建索引。
- 共享 provider 归 AstrBot 所有：本插件不会关闭它、不会改它的配置，顶栏「卸载模型」对它也是空操作。
  AstrBot 热重载该 provider 后会自动跟随新实例；若其模型/维度在运行中变了，插件会拒绝继续写入
  （避免把不同向量空间的数据混进同一份索引），重启插件并重建索引即可。
- 解析或探测失败时，向量检索与知识图谱标记为不可用，其余功能（含 AstrBot/SQLite 基础召回）照常启动。

### 推荐部署组合

| 场景 | 推荐配置 |
|------|----------|
| 只做基础资料管理 | 启用 WebUI，使用基础 SQLite / markdown 抽取即可 |
| 需要语义问答 | 配置 Embedding（本地、外部或复用 AstrBot）；`default` / `enhanced` 模式即可覆盖多数问题 |
| 精读单篇论文 | 选定文档后使用 `fulltext` 模式 |
| 需要论文关系推理 | 启用 LightRAG，配置图谱 LLM 与 Embedding 后按集合构建，使用 `graph_mixed` / `graph_only` |
| 追求召回精度 | 配置 cross-encoder reranker，各模式自动宽召回后重排 |
| 需要资料库迁移备份 | 启用 R2 做原件与状态备份；Notion 用于可读镜像与笔记追踪 |
| 已使用 Zotero | 启用 Zotero 同步：本地模式读本机 Zotero，server 模式走 Zotero Web API；按需选择 `sync_mode` |

### 常见问题

**WebUI 无法打开**：检查 `web_console.enabled` 是否为 `true`、`web_console.password` 是否非空、端口 `26618` 是否被占用或被防火墙拦截。

**向量库节点显示「数据目录被占用」**：Milvus Lite 的旧服务仍持有锁，持锁者可能就是当前 AstrBot 进程中的旧实例。请**完整退出 AstrBot 后重新启动**，仅重启或重装插件可能不够；仍失败时再检查是否有重复进程、目录 ACL 或安全软件。不要直接删除锁文件或向量数据目录。

**新上传的文档搜不到**：在数据流页确认「自动重建索引」已开启，并查看向量库节点的待重建数量；重建在防抖窗口（默认 30 秒）后自动开始，进度可在进度栏查看。

**LightRAG 无法构建**：确认已安装 `lightrag-hku`（数据流页可一键安装），并提供可用的图谱 LLM / Embedding。数据流页会直接标出缺失项。

**LightRAG 构建卡住**：可在图谱页取消构建（幂等），并有连续失败熔断（阈值 3 次）。

**Zotero 同步没有 PDF**：本地模式需要 Zotero 开启 "Allow other applications to communicate with Zotero"；server 模式需要有效 API key，且只能访问账号权限允许的条目和附件。

**Zotero 删掉的文献还留在库里**：默认 `conservative` 模式会把它们标为 `detached` 并保留数据；需要随 Zotero 硬删除时切换到 `strict_mirror`。

**Notion 同步报 404 / 找不到数据库**：核对 `database_id` / `qa_database_id` 是新版 **Database 容器 ID**、`data_source_id` 是对应的 Data Source ID，并确认 Notion 集成已被授权访问这两个库。报错会指出是哪一个配置字段与当前 ID。

**Notion 提示缺少 Data Source 工具**：宿主 MCP 仍是旧版本。把 AstrBot MCP 配置中的启动包锁为 `@suekou/mcp-notion-server@2.0.2`（Node.js 22+）并重连。

**引用全是 `Anon. (n.d.)`**：该文档没有书目元数据。Zotero 来源的文档自带作者/年份；本地上传的文档请在「文档 → 元数据」里补作者、年份、期刊、DOI，或把文件命名为 `作者 (年份) - 标题.pdf` 后重新导入。

**上传失败（413）**：单文件上限 200MB；超大文件建议拆分或压缩后上传。

**安装依赖很慢**：本地 Embedding 会安装 PyTorch / sentence-transformers，Linux CPU 部署建议先装 CPU-only PyTorch 再装其余依赖；不需要本地模型时可改用 `external` / `astr`。

**问答等了十几分钟，页面上答案消失了**：前端会在超时后自动轮询并补回后台已完成的答案；若仍未出现，检查 `ask.task_timeout_seconds` 与终端日志里的 LLM 调用记录。

**显存被占着，想跑本地大模型**：顶栏「显存」面板可查看 embedding / rerank 驻留状态并一键卸载（同时清空 CUDA 缓存）。卸载后下次检索会自动重新加载，随时可点。模型空闲 420 秒后本来也会自动卸载。

**排查运行问题**：打开终端日志页，按 ERROR 过滤或搜索关键词，可展开完整堆栈、一键复制/下载日志用于反馈。

---

## 版本演进（v1.0 → v1.2）

| 阶段 | 版本 | 主线 |
|------|------|------|
| 发布治理 | v1.0.0 – v1.0.3 | 首个正式版；Notion 单库过滤同步与 QA 推送、developer/main 双分支发布流水线、AGPL-3.0 授权、Windows 包名冲突修复 |
| 目录收敛 | v1.0.4 | 收敛为当前的 `kacore/` `web/` `migrations/` 布局 |
| Codex Agent 界面 | v1.0.5 – v1.0.8 | 诞生 Codex Skill；证据-only Ask（`plugin_llm_used=false`）；全文阅读意图门控；Codex 驱动的 LightRAG 构建；交互式连接注册；`notion-save-qa` |
| 生产健壮性 | v1.0.9 – v1.0.12 | Milvus Lite 在 Windows 可装可用；embedding 设备/加载超时；LightRAG 构建取消与熔断；终端日志完整性；Ask 长任务不再丢答案 |
| 引用与显存 | v1.1.0 – v1.1.1 | Harvard 引用三出口统一；显存与本地模型面板；`fulltext` 全文检索端到端可用与超长确认门 |
| 自维护索引 | v1.1.2 – v1.1.3 | Milvus 索引自动重建；文件名书目解析修复 `Anon., n.d.`；英文界面 i18n 补齐 |
| **本版** | **v1.2.0** | **清洗与证据升级**（水印去除、脚注保留、新切片边界、证据会话）；**Notion MCP v2** 与自动同步、笔记标记；**复用 AstrBot Embedding** 与外部 embedding 加固；**Milvus 生命周期**修复；Zotero 删除语义纠正 |

完整条目见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 技术架构（开发者）

插件遵循「薄壳 + 组合根 + 单向分层」的结构：

```text
AstrBot / Web / CLI
        |
        v
main.py / web/server.py
        |
        v
kacore/event_handler.py -> kacore/api.py
        |
        v
managers / pipelines -> repository -> domain
```

关键约束：

- 框架入口只注册和委派，不写业务逻辑。
- 业务编排集中在 `kacore/api.py`、`kacore/managers/` 和 `kacore/pipelines/`。
- 持久化通过 `kacore/repository/*/base.py` 的接口契约隔离。
- `kacore/domain/` 保持零依赖。
- 前端源码在 `web/frontend/`，静态产物在 `pages/`，只能通过构建和 `tools/sync_frontend.py` 同步。

开发与目录指引：

完整开发资料位于 `developer` 分支。开发者克隆后执行：

```bash
git switch developer
pip install -r requirements-dev.txt
```

- [Git 工作流](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/docs/GIT_WORKFLOW.md)：developer/main 维护、发布与远端审批。
- [项目结构](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/docs/PROJECT_STRUCTURE.md)：目录结构与发布前检查。
- [架构规范](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/ARCHITECTURE.md)：分层、依赖方向和组合根。
- [编码公约](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/CONVENTIONS.md)：命名、契约与测试约定。
- [Notion 同步指南](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/docs/NOTION_SYNC.md)：MCP v2 升级、笔记规则与消耗。
- [路线图](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/TODO.md) 与 [变更记录](./CHANGELOG.md)。

---

## 许可证

本项目以 [AGPL-3.0](./LICENSE) 授权。若你在网络服务中分发或提供本项目的修改版本，须同样以 AGPL-3.0
公开对应的完整源码。

---

## 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)：插件运行时与知识库生态。
- [Moirai - 世界线](https://github.com/MKiyoaki/astrbot-plugin-moirai)：README 组织方式参考。
- [LightRAG](https://github.com/HKUDS/LightRAG)：图谱增强检索能力。
- Zotero、Notion、Cloudflare R2：资料管理与同步备份生态。
