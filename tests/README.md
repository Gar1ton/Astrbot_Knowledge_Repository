# tests/ — 测试分层

## 结构

```
tests/
  backend/     # 后端单元/集成测试（按被测模块命名 test_xxx.py）
  frontend/    # 前端测试（若有）
  mocks/       # 可注入的测试替身：内存 repo、provider 桩、假 encoder
  mock_data/   # 测试夹具数据
```

## 核心做法：接口对换测试

依赖「接口先行」（见 `../ARCHITECTURE.md`）：测试时把生产实现换成 `mocks/` 里的内存实现，
无需真实 DB / 网络 / LLM 即可覆盖业务契约。

```python
repo = InMemoryEventRepository()      # 来自 tests/mocks（与 repository/base 同接口）
mgr = RecallManager(repo, cfg=...)    # 构造器注入桩
assert await mgr.recall("q") == [...]
```

## 约定

- 测试文件 `test_<被测模块>.py`，与 `core/` 结构对应。
- 每条公开契约都有测试；**改接口必须同步改测试**。
- `TODO.md` 里把条目标 `[x]` 的前提是相关测试**已过**。
- pytest 配置在根 `pyproject.toml`（`asyncio_mode = "auto"`、`pythonpath`、`testpaths`）。
- CI（`.github/workflows/tests.yml`）在 push/PR 时自动跑全量测试。
