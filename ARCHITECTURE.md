# ARCHITECTURE — 架构圣经

> 本文件解释**为什么这样分层、代码放哪、依赖指向哪**。任何 agent 在落地代码前必须理解本文件。
> 核心理念一句话：**单向分层 + 组合根集中装配 + 接口先行 + 类型化配置**。

---

## 1. 依赖方向（最重要的一张图）

```
                外部框架 / 运行时 (astrbot / FastAPI / CLI / …)
                              │  注册、回调
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │  shell (main)            框架适配薄壳：只注册 + 委派，零业务  │  最外层
   ├──────────────────────────────────────────────────────────┤
   │  event_handler           事件分发：框架事件 → 子系统调用     │
   ├──────────────────────────────────────────────────────────┤
   │  managers / pipelines    编排服务：业务流程、用例编排         │
   ├──────────────────────────────────────────────────────────┤
   │  repository              仓储：持久化抽象（ABC）+ 实现        │
   ├──────────────────────────────────────────────────────────┤
   │  domain                  纯数据模型：零依赖（圆心）           │  最内层
   └──────────────────────────────────────────────────────────┘

   横切支撑（被各层使用，自身不反向依赖业务）：
     adapters（框架↔domain 翻译） · mixins（可复用行为） · utils（工具） · config（类型化配置）
```

**铁律：依赖只能指向内层（向下），永不反向。**

- `domain` 不 import 任何其他层（连框架、连数据库都不知道）。
- `repository` 只依赖 `domain`。
- `managers` 依赖 `repository` 接口 + `domain`，**不直接 import 框架**。
- `event_handler` / `shell` 依赖框架，但把业务全部委派给 `managers`。
- 需要框架数据进入业务时，先经 `adapters` 翻译成 `domain` 对象。

> 这条规则是「可视性」的根：看一个文件的 import，就能判断它属于哪层、是否越界。
> 越界 import（如 `domain` 里出现 `import sqlite3` 或框架 API）= 架构腐坏的第一信号。

---

## 2. 薄壳原则（Thin Shell）

框架入口（`core/main.example.py` 所示）**只做两件事**：

1. 向框架**注册** hooks / commands / tools / 路由；
2. 把每个回调**委派**给 `event_handler` 或对应 manager。

入口里**不写任何业务逻辑、不做条件判断之外的计算**。好处：

- 换框架（astrbot → FastAPI → CLI）时，只重写薄壳，业务层一行不动 → 呼应「不限于 astrbot」。
- 框架热重载时，业务状态集中在组合根，便于干净重建。

---

## 3. 组合根模式（Composition Root）

**所有对象的创建与装配集中在一个地方**：`core/plugin_initializer.example.py`（组合根）。

- 按**依赖顺序**构造：先建无依赖的（config、repository），再建依赖它们的（managers、pipelines），最后建薄壳引用。
- **构造器注入**：每个组件通过构造参数接收依赖，**自己绝不 new 依赖**、绝不读全局单例。
  - 好处：组件可被单测独立实例化，注入 mock；依赖关系在组合根一目了然。
- **生命周期对称**：用 `AsyncExitStack`（或等价机制）注册资源，`teardown` 时**反序**释放。
  - `initialize()`：构造 → start → 注册定时任务。
  - `teardown()`：cancel 任务 → stop 子系统 → 关闭连接（与构造顺序相反）。

> 判断「装配代码该放哪」：凡是 `X = SomeClass(...)` 把零件接起来的代码，都属于组合根，不属于业务层。

---

## 4. 接口先行（Interface-First）

每一层用**抽象基类（ABC）**定义契约，实现与契约分离：

```
repository/
  base.py      # ABC：定义方法签名 + docstring 契约（唯一真相源）
  sqlite.py    # 生产实现
  memory.py    # 内存实现（测试用，无 I/O）
managers/
  base.py      # ABC：BaseManager → BaseXxxManager（抽象方法 + 契约）
  xxx.py       # 具体编排实现
```

- **生产实现 + 测试实现共用同一接口** → 「接口对换测试」：测试里注入 `memory` 实现，无需真实 DB/网络。
- 契约（同步顺序、主键约定、返回 None 的语义等）写在 `base.py` 的 docstring 里，是该层的**唯一真相源**。
- 改接口 = 改契约：必须同时更新 `base.py` docstring、所有实现、所有调用方、相关测试。

---

## 5. 类型化配置（Typed Config）

原始配置（dict / JSON / 环境变量）**只在一个地方**被解析成结构化对象：

```
原始 dict ──► Config（core/config）──► get_xxx_config() ──► XxxConfig (dataclass)
                                                              ▲
                                          各子系统只接收自己的 XxxConfig
```

- 杜绝业务代码里散落的 `cfg.get("some_key", default)`：键名、默认值、类型集中在 `Config`。
- 每个子系统拿到**专属的 dataclass**，可独立单测，IDE 有补全与类型检查。
- 配置项的 schema/默认值与 UI（如 `_conf_schema.json`）保持同源。

---

## 6. 持久化与迁移

- 数据库 schema 用**编号迁移**演进：`migrations/NNN_描述.sql`（`001`, `002`, …）。
- 一个**幂等 runner**：每次启动按文件名顺序应用未执行的迁移，用 `_migrations` 跟踪表去重。
- 详见 `migrations/README.md`。

---

## 7. 可选全栈（web）

带 WebUI 的项目遵循「**业务门面 + 路由委派**」：

- `core/api.py`：**框架无关**的纯业务函数（不含 HTTP 概念）。
- `web/`：HTTP 层，把请求参数翻译后**委派给 `core/api`**，再把结果包装成响应。
- `web/registry.py`：可选的面板/扩展注册中心（供第三方挂载）。
- `web/frontend/`：前端源码；构建产物同步到 `pages/`（运行时静态资源）。

详见 `web/README.md`。

---

## 8. ✅ 新增子系统清单（Agent 落地代码时照此执行）

向项目加入一个新业务能力（如 "notifier"）时，按序执行：

1. **定位层级**：它是编排逻辑（→ `managers/` 或 `pipelines/`）、持久化（→ `repository/`）还是纯模型（→ `domain/`）？
2. **先定接口**：在该层 `base.py` 增加 ABC / 抽象方法，**用 docstring 写清契约**（输入、输出、副作用、错误语义）。
3. **写实现**：生产实现 + （若涉及 I/O）内存/桩实现各一份，满足同一接口。
4. **加配置**：若需配置，在 `core/config` 增加 `XxxConfig` dataclass 与 `get_xxx_config()`，并在 `_conf_schema.json` 登记字段。
5. **在组合根注入**：在 `plugin_initializer` 按依赖顺序构造它、传入依赖、注册生命周期/定时任务。
6. **接薄壳**（若需框架触发）：在 `main`/`event_handler` 注册回调并委派，**不在薄壳写业务**。
7. **写测试**：用内存实现做接口对换测试，覆盖契约。
8. **更新治理**：在 `TODO.md` 勾对应 Phase；收尾在 `CHANGELOG.md` 追加条目（点名新增文件/模块）。

> 任一步缺失（尤其 2、5、7）都视为未完成——这是「可视性」不被 vibe coding 侵蚀的保证。
