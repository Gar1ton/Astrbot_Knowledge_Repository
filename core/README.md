# core/ — 全部业务逻辑（单向分层）

本目录承载项目的**所有业务逻辑**。框架（astrbot/FastAPI/CLI…）只在薄壳层出现，越往内越纯粹。

## 分层与依赖方向

```
main(薄壳) → event_handler(分发) → managers/pipelines(编排) → repository(仓储) → domain(纯模型)
                                         └────────── 横切：adapters · mixins · utils · config ──────────┘
```

**依赖只能指向内层（向下），永不反向。** 详见根目录 [`../ARCHITECTURE.md`](../ARCHITECTURE.md)。

## 本目录成员

| 路径 | 角色 | 说明 |
|------|------|------|
| `main.example.py` | 薄壳层 | 框架注册 + 委派，零业务。复制后改为框架要求的入口名。 |
| `plugin_initializer.example.py` | **组合根** | 按依赖序构造全部子系统 + 生命周期管理。 |
| `event_handler.README.md` | 事件分发 | 框架事件 → 子系统调用。 |
| `config.README.md` | 类型化配置 | 原始 dict → `get_xxx_config()` dataclass。 |
| `api.README.md` | 业务门面 | 框架无关纯函数；`web/` 委派于此。 |
| `domain/` | 领域模型 | 纯数据，零依赖（依赖方向的圆心）。 |
| `repository/` | 仓储 | 接口先行：`base`(ABC) + `sqlite`(生产) + `memory`(测试)。 |
| `managers/` | 编排服务 | 用例编排，含 ABC 基类层级。 |
| `adapters/` | 适配翻译 | 框架数据 ↔ `domain` 对象。 |
| `mixins/` | 可复用行为 | 横切行为（序列化/校验等）。 |
| `pipelines/` | 领域管线 | 多步骤业务流水线（抽取/检索/任务等）。 |
| `utils/` | 工具 | 无业务语义的横切工具。 |

## 在此新增代码？

照 [`../ARCHITECTURE.md` §8 新增子系统清单](../ARCHITECTURE.md) 执行：定层级 → 先定接口 → 写实现 → 加配置 → 组合根注入 → 接薄壳 → 写测试 → 更新治理三件套。
