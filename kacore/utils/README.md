# core/utils/ — 横切工具

## 职责

放**无业务语义**的通用工具：缓存、重试、限流、格式化、版本读取、i18n、性能计时等。

## 典型成员（参考）

```
utils/
  cache.py      # TTLCache / LRU / 有界 key mixin
  retry.py      # 重试 / 退避
  formatter.py  # token 估算、文本格式化
  i18n.py       # 多语言字符串
  version.py    # 从 metadata 读取版本号
  perf.py       # 计时 / 埋点
```

## 约定

- **不含业务规则**：utils 只做通用计算。带业务语义的逻辑属于 managers/pipelines。
- 尽量是**纯函数或无状态类**，可独立单测。
- 任意层都可依赖 utils；utils **不反向依赖**业务层（不 import managers/repository 的具体实现）。
- 同一段逻辑被 ≥3 处复制时，迁入此处统一。
