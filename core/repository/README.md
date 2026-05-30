# core/repository/ — 仓储层（接口先行）

## 职责

封装**一切持久化访问**（数据库、文件、缓存）。业务层只依赖本层的**接口**，不知道背后是 SQLite 还是别的。

## 接口先行结构

```
repository/
  base.py     # ABC：定义每个 Repository 的方法签名 + docstring 契约（唯一真相源）
  sqlite.py   # 生产实现（真实 I/O）
  memory.py   # 内存实现（无 I/O，供测试做「接口对换」）
```

- **生产实现与测试实现共用 `base.py` 接口** → 测试注入 `memory.py`，无需真实 DB。
- 契约（同步顺序、主键约定、`None`/`False` 语义）**写在 `base.py` 的 docstring**，改契约必须同步改全部实现 + 调用方 + 测试。

## 契约书写要点（示例）

```python
class XxxRepository(ABC):
    @abstractmethod
    async def get(self, id: str) -> Xxx | None:
        """按外部 UUID 取一条；不存在返回 None（非异常）。"""
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """删除；同步顺序：先删索引 → 再删主表。返回 False 表示 id 不存在。"""
        ...
```

## 约定

- 只依赖 `domain`，不依赖 `managers`/框架。
- 外部标识用稳定 ID（UUID），内部连接键（如 rowid）只在本层暴露给需要的调用方，并在 docstring 写明。
- 复杂查询尽量**下推到存储**（SQL/索引），而非加载全量到内存再过滤。
