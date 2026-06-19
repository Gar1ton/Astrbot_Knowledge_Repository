"""migration 018（统一多归属集合树）的回填与数据迁移契约测试。

模拟一个「018 之前」的旧库：先只跑 001-017，灌入扁平集合 + 单值归属文档，
再单独执行 018，断言：每行获得唯一 coll_key、document_collections 由旧单值归属正确派生。
"""
from __future__ import annotations

from pathlib import Path

import aiosqlite

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def _apply(conn: aiosqlite.Connection, *names: str) -> None:
    for name in names:
        sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.commit()


async def test_018_backfills_keys_and_migrates_memberships() -> None:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")

    # 1) 只跑到 017（模拟旧库，collections 尚无 coll_key 列）
    pre_018 = sorted(p.name for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    pre_018 = [n for n in pre_018 if n < "018"]
    await _apply(conn, *pre_018)

    # 2) 灌入旧风格数据：两个扁平集合 + 各一篇文档（单值归属）
    await conn.execute(
        "INSERT INTO collections (name, description, created_at) VALUES ('A', '', '2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO collections (name, description, created_at) VALUES ('B', '', '2026-01-01')"
    )
    for doc_id, coll in (("d1", "A"), ("d2", "A"), ("d3", "B")):
        await conn.execute(
            "INSERT INTO documents (doc_id, title, file_path, content_type, size_bytes, "
            "content_hash, collection, created_at, updated_at) "
            "VALUES (?, ?, '/x.pdf', 'application/pdf', 1, 'h', ?, '2026-01-01', '2026-01-01')",
            (doc_id, doc_id, coll),
        )
    await conn.commit()

    # 3) 应用 018
    await _apply(conn, "018_unified_collection_tree.sql")

    # 每个集合获得唯一非空 coll_key
    async with conn.execute("SELECT name, coll_key, parent_key, library_id FROM collections") as c:
        rows = await c.fetchall()
    keys = {name: ck for name, ck, _, _ in rows}
    assert all(ck for ck in keys.values()), "所有集合都应回填非空 coll_key"
    assert len(set(keys.values())) == len(keys), "coll_key 必须唯一"
    assert all(pk == "" for _, _, pk, _ in rows), "现有集合均回填为顶层"

    # 旧单值归属正确迁移进多对多表
    async with conn.execute(
        "SELECT doc_id, coll_key FROM document_collections ORDER BY doc_id"
    ) as c:
        memberships = await c.fetchall()
    assert sorted(memberships) == sorted(
        [("d1", keys["A"]), ("d2", keys["A"]), ("d3", keys["B"])]
    )

    await conn.close()
