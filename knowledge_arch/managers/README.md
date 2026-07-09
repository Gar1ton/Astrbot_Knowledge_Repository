# core/managers/ — 编排服务层

## 职责

承载**用例编排 / 业务流程**：协调 `repository`、`pipelines`、`adapters`、`domain` 完成一个完整业务动作。
这是「业务逻辑」的主战场。

## 结构（ABC 基类层级）

```
managers/
  base.py            # 抽象基类层级：BaseManager → BaseXxxManager（公共能力 + 抽象契约）
  xxx_manager.py     # 具体 manager，继承对应 base，实现抽象方法
```

- `base.py` 提供公共能力（如统一 logger）并用抽象方法定义子类契约。
- 每个 manager **单一职责**：名字即职责（`recall_manager` 只管检索召回，不顺手干别的）。

## 约定

- **构造器注入**：依赖（repository、config dataclass、其它 manager、provider getter）全部经构造参数传入；**绝不自己 new、绝不读全局单例**。
- **不直接 import 框架 SDK**：需要框架数据时，由薄壳/`event_handler` 经 `adapters` 翻译成 `domain` 再传入。
- 配置以**专属 dataclass**注入（来自 `core/config` 的 `get_xxx_config()`），不在内部到处 `cfg.get(...)`。
- 跨多步骤、可独立复用的算法流水线下沉到 `pipelines/`，manager 负责编排它们。

## 测试

用 `repository/memory.py` 做接口对换，独立实例化 manager 注入 mock 依赖，覆盖每条契约。
