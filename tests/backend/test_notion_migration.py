"""Regression coverage for the Notion ledger schema migration."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def _apply(conn: aiosqlite.Connection, *names: str) -> None:
    for name in names:
        sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.commit()


@pytest.mark.asyncio
async def test_notion_archived_status_migration_preserves_existing_rows() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        before_021 = sorted(
            path.name
            for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
            if path.name < "021"
        )
        await _apply(conn, *before_021)
        await conn.execute(
            "INSERT INTO notion_entity_map "
            "(entity_type, entity_key, page_id, status) VALUES (?, ?, ?, ?)",
            ("document", "d1", "page-1", "failed"),
        )
        await conn.commit()

        await _apply(conn, "021_notion_archived_status.sql")
        await conn.execute(
            "INSERT INTO notion_entity_map "
            "(entity_type, entity_key, status) VALUES (?, ?, ?)",
            ("document", "d2", "archived"),
        )
        await conn.commit()

        async with conn.execute(
            "SELECT entity_key, page_id, status "
            "FROM notion_entity_map ORDER BY entity_key"
        ) as cursor:
            rows = await cursor.fetchall()
        assert rows == [("d1", "page-1", "failed"), ("d2", "", "archived")]
    finally:
        await conn.close()
