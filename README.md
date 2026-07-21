<div align="center">

<img src="./logo.svg" width="96" alt="Knowledge Arch Logo" />

# Knowledge Arch

**AstrBot 知识库原件管理、同步备份与 Research Agent 插件**

[![version](https://img.shields.io/badge/版本-v1.0.8-blueviolet)](metadata.yaml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-plugin-6f42c1)](https://github.com/AstrBotDevs/AstrBot)

*PDF 原件库 · Zotero 同步 · 五档检索 · LightRAG 图谱 · 独立 WebUI*

</div>

---

## 这是什么

Knowledge Arch 为 AstrBot 增加一个面向资料、论文和长期知识沉淀的独立知识库应用。它以 PDF 等原件为中心，提供文档上传、集合分类、Zotero 镜像、Notion / R2 同步备份、多档检索问答和 LightRAG 知识图谱能力，并通过独立 Web 控制台完成日常管理。

核心亮点：

- **原件优先的知识库管理**：保留 PDF 原件与抽取后的 clean markdown，支持集合、标签、文档元数据、笔记和分块检查。
- **五档检索模式**：从快速查证到多轮深度推演，按问题复杂度选择成本档位（见[检索模式](#五档检索模式)）。
- **Research Agent 问答**：在 AstrBot 对话中直接自然语言提问，先探查范围再召回，答案附 `Author - Year - Title` 引用列表；WebUI 内亦有独立问答页。
- **Zotero 资料同步**：支持本地 Zotero 与 Zotero Web API 模式，把 Zotero collection 树同步为插件内集合树，含换号保护。
- **LightRAG 图谱**：按集合构建 workspace，支持纯图谱查询与「语义/词法证据 + 图谱上下文」混合检索。
- **同步与备份**：Cloudflare R2 保存可跨设备恢复的完整快照；Notion 提供可读元数据镜像。
- **独立 WebUI**：默认端口 `26618`，内置登录鉴权，覆盖文档、问答、图谱、同步、配额、设置、数据流诊断和可过滤的终端日志。

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

重启 AstrBot 后，插件会按需初始化数据库、迁移和 Web 控制台资源。

### 基础配置

在 AstrBot 管理面板 -> 插件配置 -> Knowledge Arch 中至少配置：

| 配置键 | 说明 |
|--------|------|
| `web_console.enabled` | 是否启用独立 Web 控制台 |
| `web_console.port` | Web 控制台端口，默认 `26618` |
| `web_console.username` | 登录用户名，默认 `admin` |
| `web_console.password` | 登录密码；建议用环境变量 `KR_WEB_PASSWORD` 注入，留空会拒绝启动 WebUI |

> AstrBot 面板只承载 Web 控制台、R2、Notion、Embedding 四组基础配置；
> Zotero、LightRAG 图谱与检索调优在 **WebUI 设置页 / 数据流页**配置，持久化到 `runtime_config.json`。

> **Notion MCP 版本要求：** 当前适配器使用 `@suekou/mcp-notion-server` v1.2.x 的
> `notion_query_database` / `notion_create_database_item` 工具契约。v2 已切换到 Data Source API；
> 请在 AstrBot 的 MCP 配置中把启动包锁为 `@suekou/mcp-notion-server@1.2.4`，不要使用未锁版本的
> `npx -y @suekou/mcp-notion-server`。宿主配置位于本仓库外，本插件不会自动修改。

### 可选依赖

AstrBot 自动安装的 [`requirements.txt`](./requirements.txt) 只包含基础运行依赖。下列能力需要 [`requirements-additional.txt`](./requirements-additional.txt)，可整体 pip 安装，也可以在 WebUI「数据流」页对缺失依赖**一键安装**（白名单内）：

```bash
pip install -r requirements-additional.txt
```

| 能力 | 依赖说明 |
|------|----------|
| 本地 Embedding | `sentence-transformers`，用于向量检索和 LightRAG embedding |
| LightRAG 图谱 | `lightrag-hku`，用于图谱构建、纯图谱查询与图谱混合检索 |
| Cloudflare R2 | `boto3`，用于原件与数据库备份 |

### 验证插件生效

1. 打开 `http://<服务器IP>:26618`，使用配置的用户名和密码登录。
2. 在「文档」页上传 PDF（上限 200MB），确认文档进入集合并完成抽取。
3. 在「Research Agent」页提问，或发送 `/ka research on` 后在 AstrBot 对话中直接提问，确认回答引用了知识库资料。
4. 可选：在「数据流」页检查 Zotero、Embedding、Milvus、LightRAG 等模块的就绪状态。

---

## 使用指南

### 插件在做什么

| 流程 | 行为 |
|------|------|
| 上传 / 同步资料 | 保存原件，抽取 markdown，切分 chunks，写入 SQLite 源库 |
| 集合与标签管理 | 本地集合可编辑；Zotero 集合只读镜像；检索和图谱范围包含选中集合及后代 |
| 对话增强 | `/ka agent on` 时把召回片段注入主 LLM（被动 grounding）；主动检索用自然语言触发 research skill |
| 图谱构建 | 对集合及其后代文档构建单一 LightRAG workspace，支持暂停、恢复和历史状态 |
| 同步备份 | R2 以内容寻址快照备份全部插件持久化数据；Notion 镜像文档元数据；Zotero pull 同步文献库 |

### 五档检索模式

聊天工具、WebUI 问答页与聊天面板共用同一组模式。**按需选最低档**——档位越高，内部 LLM 调用越多、耗时越长：

| 模式 | 适用场景 | 成本 | 范围要求 |
|------|----------|------|----------|
| `default` | 查存 / 单点事实，最快 | ★ | 可全局 |
| `enhanced` | 分析、对比、机制类问题：一次拆解 + 宽召回 + 自检纠偏 | ★★ | 可全局 |
| `deep_thinking` | 综述、系统梳理级任务：多轮迭代推演 | ★★★★ | 需绑定集合 |
| `graph_mixed` | 语义/词法证据 + LightRAG 图谱上下文混合 | ★★★ | 需绑定集合 |
| `graph_only` | 纯图谱检索，只用实体关系上下文 | ★★ | 需绑定集合 |

> 图谱两档需要先在「LightRAG 图谱」页对目标集合完成构建。配置了 cross-encoder reranker 时，各模式自动「宽召回 → 重排」。

### 对话式 research（中英双语）

发送 `/ka research on` 开启后，直接在对话中提问即可：

1. 主 LLM 先用 `research_scope_probe` 探查范围（命中的论文 / 集合 / 标签）；
2. 范围明确直接召回作答，模糊则先告诉你范围与建议模式、征求确认；
3. 答案下方附 `Author - Year - Title` 引用列表。

默认英文召回、按提问语言作答（可用 `/ka research_language` 固定）。两个工具均只读，不会修改任何同步配置。

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
| `/ka r2 <push\|pull\|status>` | R2 增量备份 / 恢复登记 / 用量查询 |
| `/ka r2 force <push\|pull>` | 全量覆盖上传 / 整库恢复并自动软重启（均需二次确认） |
| `/ka webui <on\|off>` | 实时启停 Web 控制台 |

### R2 完整备份与跨设备恢复

采用内容寻址快照协议（`knowledge-arch/v1/`）：每次 `push` 生成完整清单但只上传远端缺失的 blob，`latest.json` 最后提交——任何中途失败都不会破坏上一份可恢复快照。

- **备份包含**：SQLite 一致性快照（文档/集合/笔记/聊天/同步/构建状态）、原件库与抽取产物、Milvus / LightRAG / embedding 缓存索引、可移植的非机密运行配置。
- **明确排除**：所有 API key 与密码、`secrets/`、依赖包、模型缓存、日志、临时文件、端口与设备绝对路径。

跨设备恢复：新设备装好插件和依赖、配置同一 Bucket 的 R2 凭据后，在设置页点「一键恢复」或执行 `/ka r2 force pull`——插件会下载并校验全部 blob（manifest、SHA-256、路径安全、SQLite integrity）再自动软重启；恢复失败自动回滚旧环境。

> **恢复是整体覆盖，不做增量合并。** 执行前用 `/ka r2 status` 或设置页确认远端 latest 快照是需要的版本。

### Zotero 换号保护

同一账号换 token 直接生效；检测到 token 属于**不同账号**时，同步会被阻止并要求确认：`replace` 只清空 Zotero 来源的本地镜像（本地上传的文档与集合保留）并自动开始新账号完整拉取；`cancel` 保留旧 token 和全部数据。WebUI 有对应的确认弹窗。

### WebUI 面板导览

| 页面 | 路径 | 说明 |
|------|------|------|
| 总览 / 工作台 | `/` | 文档、笔记、聊天与操作面板的综合入口 |
| 文档 | `/documents` | 文档表、元数据、分块、PDF 预览与笔记 |
| Research Agent | `/ask` | 带引用来源的知识库问答，五档模式可选 |
| LightRAG 图谱 | `/graph` | 图谱构建（可暂停/恢复）、实体关系查询与统计 |
| 检索 | `/search` | 知识库检索与召回调试 |
| 同步 / 备份 | `/sync` | Zotero、Notion、R2 同步入口 |
| 配额 | `/quota` | R2 等同步目标的用量与风险提示 |
| 设置 | `/settings` | 有效配置、外观、同步配置与运行状态 |
| 数据流 | `/flow` | 各模块依赖、配置、健康状态与依赖一键安装 |
| 终端日志 | 侧栏 `>_` / 设置页 | 运行日志：级别/分类/关键词过滤、错误跳转、堆栈折叠、复制导出 |

---

## 高级配置与调优

### 模块开关一览

| 功能 | 配置位置 | 默认 |
|------|----------|------|
| Web 控制台 | AstrBot 面板 `web_console.enabled` | 关 |
| R2 备份 | AstrBot 面板 `r2_sync.enabled` | 关 |
| Notion 镜像 | AstrBot 面板 `notion_sync.enabled` | 关 |
| Embedding 提供方 | AstrBot 面板 `embedding.provider` | `local` |
| Zotero 同步 | WebUI 设置页 / 数据流页 | 关 |
| LightRAG 图谱 | WebUI 设置页 / 数据流页 | 关 |

### 推荐部署组合

| 场景 | 推荐配置 |
|------|----------|
| 只做基础资料管理 | 启用 WebUI，使用基础 SQLite / markdown 抽取即可 |
| 需要语义问答 | 安装可选依赖并配置 Embedding；`default` / `enhanced` 模式即可覆盖多数问题 |
| 需要论文关系推理 | 启用 LightRAG，配置图谱 LLM 与 Embedding 后按集合构建，使用 `graph_mixed` / `graph_only` |
| 追求召回精度 | 配置 cross-encoder reranker，各模式自动宽召回后重排 |
| 需要资料库迁移备份 | 启用 R2 做原件与状态备份；Notion 用于可读镜像 |
| 已使用 Zotero | 启用 Zotero 同步：本地模式读本机 Zotero，server 模式走 Zotero Web API |

### 常见问题

**WebUI 无法打开**：检查 `web_console.enabled` 是否为 `true`、`web_console.password` 是否非空、端口 `26618` 是否被占用或被防火墙拦截。

**LightRAG 无法构建**：确认已安装 `lightrag-hku`（数据流页可一键安装），并提供可用的图谱 LLM / Embedding。数据流页会直接标出缺失项。

**Zotero 同步没有 PDF**：本地模式需要 Zotero 开启 "Allow other applications to communicate with Zotero"；server 模式需要有效 API key，且只能访问账号权限允许的条目和附件。

**上传失败（413）**：单文件上限 200MB；超大文件建议拆分或压缩后上传。

**安装依赖很慢**：本地 Embedding 会安装 PyTorch / sentence-transformers，Linux CPU 部署建议先装 CPU-only PyTorch 再装其余依赖。

**排查运行问题**：打开侧栏终端日志，按 ERROR 过滤或搜索关键词，可展开完整堆栈、一键复制/下载日志用于反馈。

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
- [路线图](https://github.com/Gar1ton/Astrbot_Knowledge_Repository/blob/developer/TODO.md) 与 [变更记录](./CHANGELOG.md)。

---

## 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)：插件运行时与知识库生态。
- [Moirai - 世界线](https://github.com/MKiyoaki/astrbot-plugin-moirai)：README 组织方式参考。
- [LightRAG](https://github.com/HKUDS/LightRAG)：图谱增强检索能力。
- Zotero、Notion、Cloudflare R2：资料管理与同步备份生态。
