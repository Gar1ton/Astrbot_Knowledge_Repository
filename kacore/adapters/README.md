# core/adapters/ — 适配翻译层

## 职责

在**外部框架 / 外部数据格式**与**项目内部 `domain` 模型**之间做双向翻译。它是「防腐层」（Anti-Corruption Layer）。

## 为什么需要

业务层（managers）约定**不直接 import 框架 SDK**。框架事件/消息进入业务前，必须先在 adapters 翻译成干净的 `domain` 对象；
业务结果回到框架前，也在此翻译回框架要的形状。好处：换框架时只改 adapters，业务层不动。

## 典型成员

```
adapters/
  <framework>.py        # 框架专属适配（如消息路由、事件取参）
  identity.py           # 外部身份 → 内部 Persona/用户标识解析
  message_normalizer.py # 异构消息 → 统一内部结构
```

## 约定

- 依赖方向：adapters 可 import 框架 SDK + `domain`；**业务层不反过来依赖具体框架**。
- 翻译是**纯映射**，不夹带业务决策（业务决策属于 managers）。
- 框架 API 形状多变时，用「安全取值」helper（`getattr`/`try` 包装），把脆弱性隔离在本层。
