# CONVENTIONS — 编码与可视性公约

> 本文件规定**怎么写才「可视」**。`ARCHITECTURE.md` 管「放哪」，本文件管「怎么写」。
> 目标：约束 vibe coding，使任何文件「看名字知职责、看 import 知层级、看 docstring 知契约」。

---

## 1. 命名约定（名字即地图）

- **目录 = 层 / 关注点**：`domain` / `repository` / `managers` / `adapters` / `pipelines` / `utils` / `mixins`。
- **文件 = 单一职责**：文件名是名词短语，描述它**唯一**负责的东西（`event_handler.py`、`recall_manager.py`）。
- **`base.py` = 该层接口**：每层的抽象基类/契约统一放 `base.py`，是该层唯一真相源。
- **实现按后端命名**：`sqlite.py`（生产）、`memory.py`（测试/内存）满足同一 `base.py` 接口。
- **`*.example.*` = 模板占位**：复制项目后改名启用；不会被 CI/lint 当真实代码。
- 类名 `PascalCase`，函数/变量 `snake_case`，常量 `UPPER_SNAKE`，私有前缀 `_`。
- 裸字符串若被多处比较，**提为模块常量**（如 `INTERNAL_PLATFORM = "internal"`），杜绝魔法字面量散落。

## 2. docstring 纪律（契约写在代码里）

- **每个模块**顶部 docstring：这个文件是哪一层、负责什么、**为什么存在**。
- **每个类**（尤其 `base.py` 的 ABC）docstring：写清**契约**——
  - 输入/输出语义、副作用、错误与边界（如「未找到返回 None」「返回 False 表示 id 不存在」）；
  - 涉及顺序的操作写清**同步顺序**（如「INSERT → 索引 upsert → 提交」）；
  - 主键/标识约定（如「外部用 UUID，内部用 rowid」）。
- docstring 解释 **why 与契约**，不复述 what（代码已自明的不写）。
- 中文叙述 + 英文标识符。

示例（接口先行 + 契约式 docstring）：

```python
class EventRepository(ABC):
    @abstractmethod
    async def delete(self, event_id: str) -> bool:
        """删除一个事件及其索引项。

        同步顺序：先删向量索引 → 再删主表（FTS 由触发器联动）。
        返回 False 表示 event_id 不存在（非异常）。
        """
        ...
```

## 3. 代码风格

- Python 文件首行 `from __future__ import annotations`（统一延迟注解）。
- **仅类型用途的 import 放进 `if TYPE_CHECKING:`**，避免运行时循环依赖与无谓加载。
- 用 **ASCII 分隔符**标记文件内区块，提升可扫读性：

  ```python
  # ── Event CRUD ──────────────────────────────────────────────
  ```

- 显式 `__all__`（对外模块）或保持私有 `_` 前缀，明确公开面。
- 异步项目里 I/O 一律 `async`；阻塞调用下放到 executor，不阻塞事件循环。

## 4. 单一职责 + 文件大小红线（直接约束 vibe coding）

> vibe coding 最常见的腐坏是「一个文件什么都干、越写越长」。用硬阈值对抗：

- **一个文件一个职责**：无法用一句话概括它的职责，就该拆。
- **建议红线**（超出即评估拆分，非死规定）：
  - 单文件 **> 400 行** → 警告：是否混了多个职责？
  - 单文件 **> 600 行** → 必须拆分或在 `TODO.md` 登记拆分计划。
  - 单函数 **> 60 行** 或圈复杂度过高 → 抽小函数。
- **薄壳/组合根例外**：`main` 因要注册大量回调可较长，但每个回调体应是「一行委派」。
- 重复 3 次的逻辑 → 提取到 `utils` 或 `mixins`。

## 5. 依赖与边界（与 ARCHITECTURE 联动）

- 业务层（managers/pipelines）**不直接 import 框架 SDK**；框架数据经 `adapters` 翻译为 `domain`。
- 组件**不自造依赖、不读全局单例**；一律构造器注入（装配只在组合根）。
- `domain` 保持零依赖；发现它 import 了 repository/框架/DB 驱动 = 立即修正。

## 6. 测试约定

- 每个公开契约都有测试；改接口必须同步改测试。
- 优先**接口对换测试**：注入内存实现（`memory.py`）跑业务逻辑，不依赖真实 I/O。
- `[x]` 标完成的前提是相关测试**已过**（见 `TODO.md`）。

## 7. 提交前自检清单

- [ ] import 方向合法（只向内层）？`domain` 仍零依赖？
- [ ] 新接口已写进 `base.py` 且 docstring 含契约？
- [ ] 装配只发生在组合根？无组件自造依赖？
- [ ] 无魔法字面量散落？无超红线巨型文件？
- [ ] 相关测试已过？
- [ ] `TODO.md` 已勾、`CHANGELOG.md` 已追加？
