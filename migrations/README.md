# migrations/ — 编号迁移

> 仅当项目有数据库 schema 时需要。纯无状态程序可删除本目录。

## 约定

- 每个 schema 变更是一个**编号 SQL 文件**：`NNN_简短描述.sql`，三位零填充、严格递增：
  ```
  migrations/
    001_initial_schema.sql
    002_add_status_column.sql
    003_add_index.sql
    runner.py            # 幂等执行器
  ```
- **一个幂等 runner**：启动时按文件名顺序应用**尚未执行**的迁移；用 `_migrations` 跟踪表（`name` 主键 + `applied_at`）去重。
  ```python
  async def run_migrations(db) -> list[str]:
      """按文件名顺序应用所有未执行的 *.sql；幂等，可在每次启动调用。返回新应用的迁移名列表。"""
  ```

## 规则

- 迁移**只增不改**：已发布的迁移文件视为不可变历史；修正错误用新的更高编号迁移。
- 每个迁移**单一意图**，可独立回顾。
- 编号即顺序：不要跳号、不要复用编号。
- 大变更前可触发自动备份（见 `tools/` 的备份脚本约定）。
