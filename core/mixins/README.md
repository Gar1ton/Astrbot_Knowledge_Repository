# core/mixins/ — 可复用横切行为

## 职责

提供可被多个类**混入**的小而正交的行为，避免在各处重复实现同一段逻辑。

## 典型成员

```
mixins/
  base.py     # 如 SerializableMixin（统一 to_dict）、ValidationMixin（区间校验）
```

示例：

```python
class SerializableMixin:
    """为领域模型提供一致的 JSON 序列化。"""
    def to_dict(self) -> dict: ...

class ValidationMixin:
    """提供有界数值的共享校验逻辑。"""
    __slots__ = ()
    @staticmethod
    def _check_unit(name: str, value: float) -> None: ...
```

## 约定

- 每个 mixin **单一正交职责**，命名 `XxxMixin`。
- 保持**无状态或极轻状态**；需要状态时用 `__slots__` 控制。
- mixin 不应制造跨层依赖（给 `domain` 用的 mixin 自身也得零业务依赖）。
- 「重复 3 次」是抽 mixin / util 的信号；但不要为单次使用过度抽象。
