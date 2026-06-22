<div align="center">

<img src="./logo.svg" width="96" alt="Knowledge Repository Logo" />

# Knowledge Repository

**AstrBot 知识库原件管理、同步备份与 Research Agent 插件**

[![version](https://img.shields.io/badge/版本-v0.28.0-blueviolet)](metadata.yaml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-plugin-6f42c1)](https://github.com/AstrBotDevs/AstrBot)

*PDF 原件库 · Zotero 同步 · LightRAG 图谱 · 独立 WebUI*

</div>

---

## 这是什么

Knowledge Repository 为 AstrBot 增加一个面向资料、论文和长期知识沉淀的独立知识库应用。它以 PDF 等原件为中心，提供文档上传、集合分类、Zotero 镜像、Notion / R2 同步备份、混合检索问答和 LightRAG 知识图谱能力，并通过独立 Web 控制台完成日常管理。

核心亮点：

- **原件优先的知识库管理**：保留 PDF 原件与抽取后的 clean markdown，支持集合、标签、文档元数据、笔记和分块检查。
- **Research Agent 问答**：在 AstrBot 对话中注入知识库召回上下文，或由独立 Ask Agent 生成带引用的研究型回答。
- **Zotero 资料同步**：支持本地 Zotero 与 Zotero Web API 模式，把 Zotero collection 树同步为插件内集合树。
- **LightRAG 高精度图谱**：按集合构建 LightRAG workspace，支持实体关系图谱、图谱查询和构建进度管理。
- **同步与备份**：可选同步到 Notion Database 与 Cloudflare R2，适合把资料库变成可迁移、可审计的长期资产。
- **独立 WebUI**：默认端口 `26618`，内置登录鉴权，覆盖文档、Ask、图谱、同步、配额、设置、终端日志和数据流诊断。

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

重启 AstrBot 后，插件会按需初始化数据库、迁移和 Web 控制台资源。

### 基础配置

在 AstrBot 管理面板 -> 插件配置 -> Knowledge Repository 中至少配置：

| 配置键 | 说明 |
|--------|------|
| `web_console.enabled` | 是否启用独立 Web 控制台 |
| `web_console.port` | Web 控制台端口，默认 `26618` |
| `web_console.username` | 登录用户名，默认 `admin` |
| `web_console.password` | 登录密码；建议用环境变量 `KR_WEB_PASSWORD` 注入，留空会拒绝启动 WebUI |

### 可选依赖

AstrBot 自动安装的 [`requirements.txt`](./requirements.txt) 只包含基础运行依赖。下面能力需要手动安装 [`requirements-additional.txt`](./requirements-additional.txt)：

```bash
pip install -r requirements-additional.txt
```

| 能力 | 依赖说明 |
|------|----------|
| 本地 Embedding | `sentence-transformers`，用于向量检索和 LightRAG embedding |
| LightRAG 图谱 | `lightrag-hku`，用于高精度图谱构建与查询 |
| Cloudflare R2 | `boto3`，用于原件与数据库备份 |
| 开发验证 | `pytest`、`ruff`、`mypy` 等工具 |

### 验证插件生效

1. 打开 `http://<服务器IP>:26618`，使用配置的用户名和密码登录。
2. 在 WebUI 的“文档”页上传 PDF，确认文档进入集合并完成抽取。
3. 在“Research Agent”页提问，或在 AstrBot 对话中发送普通问题，确认返回内容引用知识库资料。
4. 可选：在“数据流”页检查 Zotero、Embedding、Milvus、LightRAG 等模块的就绪状态。

---

## 使用指南

### 插件在做什么

| 流程 | 行为 |
|------|------|
| 上传 / 同步资料 | 保存原件，抽取 markdown，切分 chunks，写入 SQLite 源库 |
| 集合与标签管理 | 本地集合可编辑；Zotero 集合只读镜像；ask 和 LightRAG 范围包含选中集合及后代 |
| 对话增强 | `/ka agent on` 时把召回片段注入主 LLM（被动 grounding）；主动检索用自然语言触发 research skill |
| 图谱构建 | 对集合及其后代文档构建单一 LightRAG workspace，支持暂停、恢复和历史状态 |
| 同步备份 | R2 备份原件与状态；Notion 镜像文档元数据；Zotero pull 同步文献库 |

### /ka 指令速查

聊天端只保留运营控制面；内容管理（文档/集合/标签/Notion/知识图谱）请在 WebUI 操作。
开关均持久化到 `runtime_config.json`，重启保留。

| 指令 | 说明 |
|------|------|
| `/ka help` | 指令一览 |
| `/ka status` | 服务框架概览（所用模型 / 各服务 / 运行时开关） |
| `/ka agent <on\|off>` | 开关 ka 与 AstrBot 回复的关联（RAG 注入/旁路） |
| `/ka research <on\|off>` | 开关自然语言 research skill |
| `/ka persona <on\|off>` | 开关 AstrBot 人格 prompt（off 时不污染 research 精度） |
| `/ka zotero pull` | 触发一次 Zotero 增量同步 |
| `/ka r2 push` | 增量上传备份到 Cloudflare R2 |
| `/ka r2 force push` | 全量覆盖上传（需 60s 内重发确认） |
| `/ka r2 pull` | 从 R2 整库快照恢复，覆盖本地（需重启；需确认） |
| `/ka r2 force pull` | 强制恢复并自动重启（需确认） |
| `/ka webui <on\|off>` | 实时启停 Web 控制台 |

> **自然语言 research**：开启 `/ka research on` 后，可在对话中直接用自然语言提问，
> AstrBot 会调用 `knowledge_research` 工具，按「范围 → 模式 → 检索」分步召回并作答；
> 该工具只读，不会修改任何同步配置。

### WebUI 面板导览

| 页面 | 路径 | 说明 |
|------|------|------|
| 总览 / 工作台 | `/` | 文档、笔记、聊天与操作面板的综合入口 |
| 文档 | `/documents` | 文档表、元数据、分块、PDF 预览与笔记 |
| Research Agent | `/ask` | 带引用来源的知识库问答 |
| LightRAG 图谱 | `/graph` | 图谱构建、实体关系查询与图谱统计 |
| 检索 | `/search` | 知识库检索与召回调试 |
| 同步 / 备份 | `/sync` | Zotero、Notion、R2 同步入口 |
| 配额 | `/quota` | R2 等同步目标的用量与风险提示 |
| 设置 | `/settings` | 有效配置、外观、同步配置与运行状态 |
| 数据流 | `/flow` | 各模块依赖、配置和健康状态 |
| 终端 | `/terminal` | 插件运行日志和后台任务状态 |

---

## 高级配置与调优

### 核心模块开关

| 功能 | 配置位置 | 默认 |
|------|----------|------|
| Web 控制台 | `web_console.enabled` | 关 |
| R2 备份 | `r2_sync.enabled` | 关 |
| Notion 镜像 | `notion_sync.enabled` | 关 |
| Zotero 同步 | `zotero_sync.enabled` | 关 |
| LightRAG 图谱 | `graph.enabled` | 关 |
| 本地 / 外部 Embedding | `embedding.provider` | `local` |

### 推荐部署组合

| 场景 | 推荐配置 |
|------|----------|
| 只做基础资料管理 | 启用 WebUI，使用基础 SQLite / markdown 抽取即可 |
| 需要语义问答 | 安装可选依赖并配置 Embedding；按需接入 Milvus 或默认检索 |
| 需要论文关系推理 | 启用 `graph.enabled`，配置 LightRAG LLM 与 Embedding 后按集合构建 |
| 需要资料库迁移备份 | 启用 R2；Notion 用于可读镜像，R2 用于原件与状态备份 |
| 已使用 Zotero | 启用 Zotero 同步，本地模式读取本机 Zotero，server 模式读取 Zotero Web API |

### 常见问题

**WebUI 无法打开**

检查 `web_console.enabled` 是否为 `true`，`web_console.password` 是否非空，端口 `26618` 是否被占用或被防火墙拦截。

**LightRAG 无法构建**

确认已安装 `requirements-additional.txt`，并在配置中提供可用的 LightRAG LLM / Embedding。数据流页会显示缺失依赖和配置项。

**Zotero 同步没有 PDF**

本地模式需要 Zotero 开启 “Allow other applications to communicate with Zotero”；server 模式需要有效 API key，且只能访问账号权限允许的条目和附件。

**安装依赖很慢**

本地 Embedding 会安装 PyTorch / sentence-transformers，Linux CPU 部署建议先安装 CPU-only PyTorch，再安装 `requirements-additional.txt`。

---

## 技术架构（开发者）

插件遵循“薄壳 + 组合根 + 单向分层”的结构：

```text
AstrBot / Web / CLI
        |
        v
main.py / web/server.py
        |
        v
core/event_handler.py -> core/api.py
        |
        v
managers / pipelines -> repository -> domain
```

关键约束：

- 框架入口只注册和委派，不写业务逻辑。
- 业务编排集中在 `core/api.py`、`core/managers/` 和 `core/pipelines/`。
- 持久化通过 `core/repository/*/base.py` 的接口契约隔离。
- `core/domain/` 保持零依赖。
- 前端源码在 `web/frontend/`，静态产物在 `pages/`，只能通过构建和 `tools/sync_frontend.py` 同步。

开发与目录指引：

- [PROJECT_STRUCTURE.md](./docs/PROJECT_STRUCTURE.md)：目录结构、治理文件和 landing 指引。
- [FRAMEWORK_GUIDE.md](./docs/FRAMEWORK_GUIDE.md)：框架模板的完整设计手册。
- [CLAUDE.md](./CLAUDE.md)：本仓库最高行为契约。
- [AGENTS.md](./AGENTS.md)：非 Claude 系 coding agent 入口。
- [ARCHITECTURE.md](./ARCHITECTURE.md)：分层、依赖方向、组合根和接口先行。
- [CONVENTIONS.md](./CONVENTIONS.md)：命名、docstring、文件大小和测试约定。
- [TODO.md](./TODO.md)：路线图和版本计划。
- [CHANGELOG.md](./CHANGELOG.md)：版本变更记录。

---

## 致谢

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)：插件运行时与知识库生态。
- [Moirai - 世界线](https://github.com/MKiyoaki/astrbot-plugin-moirai)：README 组织方式参考。
- [LightRAG](https://github.com/HKUDS/LightRAG)：图谱增强检索能力。
- Zotero、Notion、Cloudflare R2：资料管理与同步备份生态。
