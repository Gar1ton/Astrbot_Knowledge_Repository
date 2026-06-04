"""Plugin-owned SQLite migration runner.

The runner lives under ``core`` so AstrBot installations that provide another
top-level ``migrations`` package cannot shadow this plugin's migrations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
REQUIRED_TABLES = {"collections", "documents", "chunks"}


async def run_migrations(db: aiosqlite.Connection) -> list[str]:
    """Apply all pending plugin migrations in filename order."""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
    )
    await db.commit()

    sql_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not sql_files:
        raise RuntimeError(f"No plugin migration SQL files found in {MIGRATIONS_DIR}")

    async with db.execute("SELECT name FROM _migrations") as cursor:
        rows = await cursor.fetchall()
        applied = {row[0] for row in rows}

    applied_new = []
    for file in sql_files:
        name = file.name
        if name in applied:
            continue

        with file.open(encoding="utf-8") as migration_file:
            await db.executescript(migration_file.read())

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
            (name, now),
        )
        await db.commit()
        applied_new.append(name)

    async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        existing_tables = {row[0] for row in await cursor.fetchall()}
    missing_tables = REQUIRED_TABLES - existing_tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"Plugin database migrations incomplete; missing tables: {missing}")

    return applied_new


__all__ = ["run_migrations"]
