# Project Structure — 目录与治理指引

> 本文承接旧根目录 README 的 landing 功能。根目录 `README.md` 现在面向 AstrBot 插件用户，
> 本文面向维护者和 coding agent，说明仓库结构、治理文件和发布前检查入口。

## 一句话定位

Knowledge Repository 是一个 AstrBot 知识库插件，同时保留了“结构与约定先行”的工程治理框架：

- 插件功能代码按 `core/` 单向分层组织；
- WebUI 源码和构建产物分离；
- 版本计划、变更记录和 agent 行为契约保持可追溯。

## 必读入口

| 文件 | 作用 |
|------|------|
| [`../CLAUDE.md`](../CLAUDE.md) | 最高行为契约：工作边界、必读顺序、Plan-First、TODO / CHANGELOG 闭环。 |
| [`../AGENTS.md`](../AGENTS.md) | 非 Claude 系 coding agent 入口，指向 `CLAUDE.md`。 |
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | 架构圣经：分层、依赖方向、组合根、接口先行。 |
| [`../CONVENTIONS.md`](../CONVENTIONS.md) | 编码与可视性公约：命名、docstring、文件大小、测试约定。 |
| [`../TODO.md`](../TODO.md) | 当前路线图、版本计划和执行状态。 |
| [`../CHANGELOG.md`](../CHANGELOG.md) | 版本倒序变更日志。 |
| [`./FRAMEWORK_GUIDE.md`](./FRAMEWORK_GUIDE.md) | 更完整的框架模板使用手册。 |

## 目录结构一览

```text
.
├── CLAUDE.md / AGENTS.md              # agent 行为契约
├── CHANGELOG.md / TODO.md             # 治理与版本闭环
├── ARCHITECTURE.md / CONVENTIONS.md   # 架构与编码约定
├── README.md                          # 面向用户的插件介绍
├── metadata.yaml / _conf_schema.json  # AstrBot 插件元数据与配置 schema
├── requirements.txt                   # AstrBot 自动安装的基础依赖
├── requirements-additional.txt        # 手动可选依赖：Embedding / LightRAG / R2 / 开发工具
├── logo.svg / logo.png                # 发布展示 logo；logo.png 由 AstrBot 识别
├── core/                              # 插件后端业务逻辑
│   ├── domain/                        # 纯数据模型，零依赖
│   ├── repository/                    # 持久化接口和实现
│   ├── managers/                      # 用例编排
│   ├── pipelines/                     # 同步、检索、图谱等流水线
│   ├── adapters/                      # 外部系统与 domain 翻译
│   ├── api.py                         # Web / 命令共享的业务门面
│   └── plugin_initializer.py          # 组合根与生命周期管理
├── migrations/                        # SQLite 编号迁移与幂等 runner
├── web/
│   ├── server.py                      # aiohttp Web 控制台后端
│   └── frontend/                      # Next.js 前端源码
├── pages/                             # 前端静态产物，由 tools/sync_frontend.py 生成，禁止手改
├── tools/                             # 构建、同步、版本等辅助脚本
├── tests/                             # 后端、前端与 mock 测试
├── docs/                              # 技术设计、结构指引和设计资产
├── data/                              # 本地示例/模板数据；运行态数据不要提交
└── dev/                               # 本地开发辅助说明
```

## 分层职责速查

| 层 | 职责 | 依赖规则 |
|----|------|----------|
| `main.py` | AstrBot 薄壳：注册 hook / command 并委派 | 可依赖框架；不写业务 |
| `web/server.py` | HTTP 层：请求参数翻译、鉴权、路由注册 | 委派给 `core/api.py` |
| `core/api.py` | 框架无关业务门面 | 组合 managers / pipelines / repository |
| `core/managers` / `core/pipelines` | 业务编排和多步骤流水线 | 依赖 repository 接口与 domain |
| `core/repository` | 持久化抽象与生产/内存实现 | 只依赖 domain |
| `core/domain` | 纯数据模型 | 零依赖 |
| `core/adapters` | 外部系统数据翻译 | 可依赖外部 SDK 与 domain |

## 发布前检查

按任务影响范围选择验证命令：

```bash
python -m pytest
ruff check .
mypy
cd web/frontend && npm run build
python tools/sync_frontend.py --check
git diff --check
```

`pages/` 只能通过以下流程更新：

```bash
cd web/frontend
npm run build
cd ../..
python tools/sync_frontend.py
python tools/sync_frontend.py --check
```

## 依赖说明

- [`requirements.txt`](../requirements.txt)：基础依赖，会被 AstrBot 插件安装器自动安装。
- [`requirements-additional.txt`](../requirements-additional.txt)：手动可选依赖，覆盖本地 Embedding、LightRAG、R2 和开发测试工具。
- 机密配置优先通过环境变量注入，例如 `KR_WEB_PASSWORD`、`KR_R2_SECRET_ACCESS_KEY`、`KR_EMBEDDING_API_KEY`。

## 维护规则摘要

- 任何非平凡任务先更新 `TODO.md`，测试通过后才能标 `[x]`。
- 收尾时在 `CHANGELOG.md` 追加或发布对应版本条目，并点名涉及文件/模块。
- 已标记 `(completed)` 的 TODO 计划段落只作历史记录，除修正错误外不改内部技术细节。
- 不手改 `pages/`，不改仓库外路径，不提交运行态密钥或私有数据。
