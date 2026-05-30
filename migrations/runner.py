"""幂等数据库迁移执行器。

每次启动时按文件名顺序应用尚未执行的 *.sql 迁移。
使用 `_migrations` 表跟踪已执行的迁移，确保幂等性。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


async def run_migrations(db: aiosqlite.Connection) -> list[str]:
    """按文件名顺序应用所有未执行的 *.sql 迁移。

    返回新应用的迁移文件名列表。
    """
    # 1) 创建迁移跟踪表
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
    )
    await db.commit()

    # 2) 查找所有的 .sql 迁移文件
    migrations_dir = Path(__file__).resolve().parent
    sql_files = sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))

    # 3) 获取已执行的迁移列表
    async with db.execute("SELECT name FROM _migrations") as cursor:
        rows = await cursor.fetchall()
        applied = {row[0] for row in rows}

    applied_new = []
    # 4) 按序应用未执行的迁移
    for file in sql_files:
        name = file.name
        if name in applied:
            continue

        print(f"Applying migration: {name}")
        with open(file, encoding="utf-8") as f:
            sql_script = f.read()

        # aiosqlite executescript runs multiple SQL statements
        # split by semicolon inside a transaction
        await db.executescript(sql_script)

        # 记录迁移已应用
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
            (name, now),
        )
        await db.commit()
        applied_new.append(name)

    return applied_new


__all__ = ["run_migrations"]
