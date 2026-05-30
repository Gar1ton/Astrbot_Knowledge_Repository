# tests/mocks/ — 测试替身

放**可注入的测试替身**，与 `core/` 的 `base.py` 接口严格一致，用于接口对换测试。

典型成员：

```
mocks/
  in_memory_repository.py   # 实现 repository/base 的接口，纯内存、无 I/O
  fake_provider.py          # LLM/embedding provider 桩，返回可控结果
  fake_encoder.py           # 确定性向量编码桩
```

约定：

- 替身**实现真实接口**（继承同一 ABC 或满足同一协议），保证「换上即可跑业务」。
- 行为可控、确定性强（无随机、无网络），让测试可重复。
- 替身归属测试代码，**不出现在生产 import 路径**（生产用 `core/repository/memory.py` 之类时除外）。
