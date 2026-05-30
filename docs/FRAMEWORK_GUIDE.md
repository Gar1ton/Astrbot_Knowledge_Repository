# 通用项目框架模板 · 使用手册

> 本文是一份**自包含的框架说明**，用于知识库存档（如 Notion）。它汇总了模板的设计理念、结构、
> 治理规范、上手流程、agent 自动加载行为与「按改动级别的阅读策略」。
> 文中提到的文件（`CLAUDE.md`、`ARCHITECTURE.md` 等）均位于模板项目内。

---

## 0. 一句话定位

这是一个**结构与约定先行**的项目脚手架（**不限于 astrbot 插件**）。它几乎不含业务代码，提供的是
一套**分层结构 + 治理流程**，唯一目的：

> **规范并约束「vibe coding」的代码可视性**——让任何人/任何 coding agent 一眼就知道
> 「代码该放哪、依赖该指向哪、文档该怎么写」，并能自动遵循执行。

---

## 1. 核心理念（5 根支柱）

| 支柱 | 含义 | 收益 |
|------|------|------|
| **薄壳层** | 框架入口只做「注册 + 一行委派」，零业务 | 换框架只重写入口，业务不动 |
| **组合根** | 所有对象的创建/装配集中一处，构造器注入 | 依赖关系一目了然、可单测 |
| **接口先行** | 每层一个 `base.py`(ABC)，契约写在 docstring | 生产/测试实现可对换，契约唯一真相源 |
| **类型化配置** | 原始 dict → 各子系统专属 dataclass | 杜绝散落的 `cfg.get(...)` |
| **治理三件套** | CLAUDE / CHANGELOG / TODO 各有严格格式 | 流程可被 agent 自动执行 |

### 依赖方向（最重要的一张图）

```
        外部框架 / 运行时 (astrbot / FastAPI / CLI / …)
                          │ 注册、回调
                          ▼
   main(薄壳) → event_handler(分发) → managers/pipelines(编排) → repository(仓储) → domain(纯模型)
                                  └── 横切：adapters(翻译) · mixins · utils · config ──┘
```

**铁律：依赖只能指向内层（向下），永不反向。** `domain` 是圆心，零依赖。
看一个文件的 import，就能判断它属于哪层、是否越界——这是「可视性」的根。

---

## 2. 目录结构总览

```
项目根/
├── CLAUDE.md / AGENTS.md          # agent 行为契约（入口，自动加载）
├── CHANGELOG.md / TODO.md         # 治理三件套（连同 CLAUDE.md）
├── ARCHITECTURE.md / CONVENTIONS.md  # 架构圣经 / 编码公约
├── metadata.yaml / _conf_schema.json # 清单 + 配置 schema
├── pyproject.toml / requirements.txt # 工具链 + 依赖
├── .github/workflows/tests.yml    # CI
├── core/                          # ★ 全部业务逻辑，单向分层
│   ├── main.example.py            #   薄壳层范例
│   ├── plugin_initializer.example.py  # 组合根范例
│   ├── (event_handler/config/api 角色说明)
│   ├── domain/  repository/  managers/  adapters/  mixins/  pipelines/  utils/
│   └── 各目录 README.md            #   每层职责 + 依赖方向 + 命名规则
├── migrations/                    # 编号迁移 NNN_*.sql + 幂等 runner
├── web/ + web/frontend/           # 可选全栈：路由委派 core/api + 前端
├── pages/                         # 前端构建产物落地（由 tools 生成，勿手改）
├── tools/                         # 构建/版本/诊断脚本
├── tests/ (backend/ mocks/ mock_data/)  # 测试分层 + 接口对换测试
└── dev/                           # 本地 dev runner
```

### 分层职责速查

| 层 | 职责 | 依赖规则 |
|----|------|----------|
| `main`(薄壳) | 框架注册 + 委派 | 可依赖框架；不写业务 |
| `event_handler` | 框架事件 → 子系统路由 | 持注入依赖；业务下沉 |
| `managers` / `pipelines` | 用例编排 / 多步骤流水线 | 依赖 repo 接口 + domain；**不 import 框架** |
| `repository` | 持久化抽象 + 实现 | 只依赖 domain |
| `domain` | 纯数据模型 | **零依赖**（圆心） |
| `adapters` | 框架数据 ↔ domain 翻译 | 可依赖框架 + domain |
| `mixins` / `utils` | 可复用行为 / 横切工具 | 不反向依赖业务 |
| `config` | 原始配置 → typed dataclass | 集中键名/默认值/类型 |

---

## 3. 治理三件套 · 格式规范（最常被引用的部分）

### `CLAUDE.md`（最高行为契约，会被 agent 自动加载）
- **工作目录边界**：只在本工作区改代码；列出只读/禁改区。
- **必读顺序**：`ARCHITECTURE.md → CONVENTIONS.md → TODO.md`。
- **执行协议（Plan-First）**：非平凡任务先读测试 → 出分 Phase 的计划 → 等批准 → 才动代码。
- **每轮工作闭环**：① 动代码前先在 `TODO.md` 勾 `🚧`/追加子项 → ② 写码遵循公约 → ③ 测试过才标 `[x]` → ④ 收尾在 `CHANGELOG.md` 追加条目。

### `CHANGELOG.md`（版本倒序）
- 最新在最上；标题 `## [vX.Y.Z] — YYYY-MM-DD`，遵循 SemVer，版本与 `metadata.yaml` 对齐。
- 子分区固定顺序（按需出现）：`新增功能 / 修复 / 性能优化 / 架构健康 / 测试 / 构建与工程`。
- **每条变更点名涉及的文件或模块**，强化可追溯。
- 默认**只追加不读**；用 `[Unreleased]` 暂存，发布时改写为版本标题。

### `TODO.md`（带严格语法的路线图）
- **状态标记**：`[x]` 已完成(且测试过) / `[ ]` 待实现 / `🚧` 进行中 / `❌` 不做(保留) / `✅` 小节完成 / `💬` 待讨论。
- **版本号**：`## vX.Y.Z 计划名 (planning|in progress|completed)`，版本取自 `metadata.yaml`。
- **新建计划结构**（固定三块）：`### User constraints` → `### Technical implementation path`(按 Phase + `[ ]`) → `### Verification`(命令 → 结果)。
- **铁律**：先更新 TODO 再动代码；测试过才标 `[x]`；Deferred 不删；不改 Completed 计划内部细节。

---

## 4. 新项目上手（三步）

1. **复制**整个模板目录为新项目。
2. **填空**：替换所有 `*.example.*` 占位与下列文件的占位内容——
   `metadata.yaml`（名/版本/作者）、`_conf_schema.json`（配置项）、
   `pyproject.toml`（工具链）、`requirements.txt`（依赖）、`CLAUDE.md §5`（构建/测试命令）。
3. **开工**：让 agent 先读 `CLAUDE.md`，它会按必读顺序加载规范并遵循执行闭环。

---

## 5. Agent 自动加载行为（重要：分两层）

| 对象 | 是否自动 | 说明 |
|------|----------|------|
| `CLAUDE.md` / `AGENTS.md` | **自动注入** | Claude Code / Cursor / Codex 会话开始即把入口文件塞进上下文，无需触发 |
| `ARCHITECTURE` / `CONVENTIONS` / `TODO` | **默认不自动** | 入口文件里的链接，agent 须主动 `Read` 才进上下文 |

**让下游文档可靠加载的三种方案（从轻到重）：**

- **A. 首次会话一句触发词**（最简单、跨所有 agent）：
  > 「这是基于通用框架模板的新项目。开始前请先读 `CLAUDE.md`，并按其『必读顺序』依次加载 `ARCHITECTURE.md`、`CONVENTIONS.md`、`TODO.md`，理解后再动手。」
- **B. Claude Code `@import` 内联**：把 `CLAUDE.md` 的必读项改成 `@ARCHITECTURE.md` 等，会话开始自动内联（零触发，但每会话占 token，且非 Claude 系不认）。
- **C. SessionStart hook**：在 `.claude/settings.json` 配 hook 每次开会话强制注入（最自动，Claude Code 专属）。

> 推荐：架构/公约用 B 常驻，TODO/CHANGELOG 保持按需读——既零触发又不过度膨胀 token。

---

## 6. 按改动级别的阅读策略（省 token）

**原则：只读覆盖「这次决策」所需的最窄集合。`CLAUDE.md` 本就自动注入（免费），其余按需取。**

| 级别 | 例子 | 除 CLAUDE.md(自动)外需读 | 可跳过 |
|------|------|--------------------------|--------|
| **L0 平凡** | 错别字/注释/版本号/单行 | （无） | 一切；仅对外可见时追加 CHANGELOG |
| **L1 单文件局部** | 修 bug、调一个函数 | 该层 `README` + `TODO`（勾/追加）；`CONVENTIONS` 只扫命名/docstring/大小 | `ARCHITECTURE`；通读 `CHANGELOG` |
| **L2 跨层/加文件** | 给 base 加方法+改实现 | L1 + `ARCHITECTURE`(依赖方向/接口先行两节) + 两层 `README` + `base.py` 契约 | 通读 `CHANGELOG` |
| **L3 新子系统/改组合根** | 加整条 pipeline、新 repository | **唯一读全级**：`ARCHITECTURE`(尤其新增子系统清单) + `CONVENTIONS` + 相关 `README`/`base.py` + `TODO`(建版本计划) | — |
| **L4 排查回归/改老代码** | 「为什么这么写」、重构 | **唯一该读 `CHANGELOG`**（搜版本/模块，别从头读）+ 按需架构/公约 | — |

**省 token 三技巧：**
1. 用 Grep 取节，不要 Read 整个大文件（ARCHITECTURE/CHANGELOG 按标题/模块名搜）。
2. 优先读局部 `README` 和 `base.py` 契约，而非全局架构 + 每个实现（契约 1 份顶实现 N 份）。
3. 同会话已在上下文的文件不重读；`CHANGELOG` 默认只写不读。

---

## 7. ✅ 新增子系统清单（agent 加功能照此执行）

1. **定位层级**：编排（managers/pipelines）/ 持久化（repository）/ 纯模型（domain）？
2. **先定接口**：在该层 `base.py` 增 ABC/抽象方法，docstring 写清契约（输入/输出/副作用/错误语义）。
3. **写实现**：生产实现 +（涉及 I/O 时）内存/桩实现，满足同一接口。
4. **加配置**：需配置则在 `config` 增 `XxxConfig` dataclass + `get_xxx_config()`，并在 `_conf_schema.json` 登记。
5. **组合根注入**：在 `plugin_initializer` 按依赖顺序构造、传入依赖、注册生命周期/定时任务。
6. **接薄壳**（如需框架触发）：在 `main`/`event_handler` 注册回调并委派，不在薄壳写业务。
7. **写测试**：用内存实现做接口对换测试，覆盖契约。
8. **更新治理**：`TODO.md` 勾对应 Phase；收尾在 `CHANGELOG.md` 追加条目（点名新增文件/模块）。

> 任一步缺失（尤其 2、5、7）视为未完成——这是「可视性」不被 vibe coding 侵蚀的保证。

---

## 8. 编码可视性公约 · 要点

- **命名即地图**：目录=层，文件=单一职责，`base.py`=该层接口，`*.example.*`=占位。
- **docstring 写契约**：模块/类说明「为什么 + 契约」（同步顺序、主键约定、None/False 语义），不复述 what。
- **风格**：`from __future__ import annotations`；仅类型 import 放 `if TYPE_CHECKING:`；用 `# ── 区块 ──` 分隔。
- **文件大小红线**：单文件 >400 行警告、>600 行必拆；单函数 >60 行抽小函数；重复 3 次即提取。
- **边界**：业务层不 import 框架 SDK（经 adapters 翻译）；组件不自造依赖（装配只在组合根）；`domain` 永远零依赖。
- **语言**：文档/注释中文，标识符/命令/版本号英文。

---

*本手册随模板演进；若模板内规范更新，以仓库内 `CLAUDE.md` / `ARCHITECTURE.md` / `CONVENTIONS.md` 为准。*
