# core/domain/ — 领域模型（依赖方向的圆心）

## 职责

定义项目的**纯数据模型**：实体、值对象、枚举、领域常量。这是依赖图的最内层。

## 铁律

- **零依赖**：本层**不 import** 框架 SDK、数据库驱动、HTTP 库、其它业务层。只允许标准库与类型注解。
  - 自检：`domain/` 里若出现 `import sqlite3` / 框架 API / `from ..repository import` → 立即修正。
- 模型用 `dataclass`（或等价不可变结构）；校验逻辑可由 `mixins`（如 `ValidationMixin`）提供。
- 领域常量在此定义并对外导出（如 `INTERNAL_PLATFORM = "internal"`），杜绝魔法字面量散落各层。

## 典型文件

```
domain/
  models.py     # 实体 / 值对象 / 枚举 / 领域常量
```

## 为什么零依赖很重要

domain 被所有层依赖却不依赖任何层 → 它最稳定、最可单测、最可移植（换框架/换存储都不影响）。
保持它纯净，是整个架构「可视且可换」的地基。
