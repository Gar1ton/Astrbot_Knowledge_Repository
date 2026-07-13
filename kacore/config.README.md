# core/config — 类型化配置

> 真实项目中体现为 `core/config.py`。本文件说明「类型化配置」模式。

## 职责

把**原始配置**（框架传入的 dict / `_conf_schema.json` / 环境变量 / 运行时覆盖）**集中解析**为
**结构化、带类型的子配置对象**，供各子系统消费。

## 模式

```
原始 dict ──► Config ──► get_xxx_config() ──► XxxConfig (dataclass)
                                                 ▲
                              每个子系统只接收自己的 XxxConfig（构造器注入）
```

```python
@dataclass
class RetrievalConfig:
    bm25_limit: int = 20
    vec_limit: int = 20
    rrf_k: int = 60

class Config:
    def __init__(self, raw: dict) -> None:
        self._raw = raw
    def get_retrieval_config(self) -> RetrievalConfig:
        return RetrievalConfig(
            bm25_limit=int(self._raw.get("bm25_limit", 20)),
            ...
        )
```

## 约定

- **键名、默认值、类型转换集中在此**，杜绝业务代码里散落 `raw.get("key", default)`。
- 每个子系统拿到**专属 dataclass**，可独立单测、IDE 可补全。
- 配置项与 `_conf_schema.json`（UI/校验来源）**保持同源**：新增配置同时改两处。
- 支持运行时覆盖时（如 WebUI 改配置），在此统一合并优先级，下游无感。
