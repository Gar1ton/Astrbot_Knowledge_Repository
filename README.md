# 通用项目框架模板（Project Framework Template）

一个**结构与约定先行**的项目脚手架，用于快速起步任意程序/插件（**不限于 astrbot**）。
它本身几乎不含业务代码——它提供的是一套**分层结构 + 治理流程**，目的只有一个：

> **规范并约束「vibe coding」的代码可视性**——让任何人/任何 coding agent 一眼就知道
> 「代码该放哪、依赖该指向哪、文档该怎么写」，并能自动遵循执行。

## 插件安装依赖

AstrBot 自动安装的 [`requirements.txt`](./requirements.txt) 仅包含 PDF 上传、PyMuPDF4LLM
清洗、SQLite 基础召回和 Web 控制台需要的轻量依赖。Milvus、本地 Embedding/PyTorch、
LightRAG 与 R2 均为真正的可选功能，并统一由
[`requirements-additional.txt`](./requirements-additional.txt) 手动安装；配置方法见
[`docs/OPTIONAL_DEPENDENCIES.md`](./docs/OPTIONAL_DEPENDENCIES.md)。

## 怎么用（复制后三步）

1. **复制**整个目录为你的新项目。
2. **填空**：替换所有 `*.example.*` 占位文件与下列文件的占位内容——
   - `metadata.yaml`（项目名/版本/作者）、`_conf_schema.json`（配置项）、
   - `pyproject.toml`（工具链）、`requirements.txt`（依赖）、`CLAUDE.md §5`（构建/测试命令）。
3. **开工**：让任何 coding agent 先读 `CLAUDE.md`，它会按必读顺序自动加载规范并遵循执行闭环。

## 文档导航（按阅读顺序）

| 文件 | 作用 |
|------|------|
| [`CLAUDE.md`](./CLAUDE.md) | **最高行为契约**：边界、必读顺序、执行协议、工作闭环。Agent 入口。 |
| [`AGENTS.md`](./AGENTS.md) | 非 Claude 系 agent 入口（指向 `CLAUDE.md`）。 |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 架构圣经：分层、依赖方向、组合根、接口先行、**新增子系统清单**。 |
| [`CONVENTIONS.md`](./CONVENTIONS.md) | 编码与可视性公约：命名、docstring、文件大小红线。 |
| [`TODO.md`](./TODO.md) | 路线图 + 严格的 TODO 语法（状态标记/版本号/计划结构）。 |
| [`CHANGELOG.md`](./CHANGELOG.md) | 版本倒序变更日志 + 写入规范。 |

## 目录结构一览

```
.
├── CLAUDE.md / AGENTS.md          # agent 行为契约
├── CHANGELOG.md / TODO.md         # 治理三件套（连同 CLAUDE.md）
├── ARCHITECTURE.md / CONVENTIONS.md
├── metadata.yaml / _conf_schema.json   # 清单 + 配置 schema（占位）
├── pyproject.toml / requirements.txt   # 工具链 + 依赖（占位）
├── .github/workflows/tests.yml    # CI（占位）
├── core/                          # ★ 全部业务逻辑，单向分层
│   ├── main.example.py            #   薄壳层范例
│   ├── plugin_initializer.example.py  # 组合根范例
│   ├── domain/  repository/  managers/  adapters/  mixins/  pipelines/  utils/
│   └── *.README.md                #   各角色/各层职责说明
├── migrations/                    # 编号迁移 + 幂等 runner（约定）
├── web/  + web/frontend/          # 可选全栈层（约定）
├── pages/                         # 前端构建产物落地（约定）
├── tools/                         # 构建/版本/诊断脚本（约定）
├── tests/  (backend/ mocks/ mock_data/)   # 测试分层（约定）
└── dev/                           # 本地 dev runner（约定）
```

> 每个目录内都有 `README.md` 说明该层职责、依赖方向与命名规则。删除业务时保留这些 README 即可保持框架完整。
