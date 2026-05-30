# tests/backend/ — 后端测试

- 按被测模块组织：`test_<module>.py`（如 `test_recall_manager.py`、`test_sqlite_repo.py`）。
- 单元测试优先用 `../mocks/` 的内存实现做接口对换；涉及真实持久化语义（ACID、索引）时再用真实后端写**集成测试**。
- 一个测试只验证一件事；命名 `test_<行为>_<条件>_<期望>`。
- 异步测试依赖根 `pyproject.toml` 的 `asyncio_mode = "auto"`，无需手写事件循环样板。
