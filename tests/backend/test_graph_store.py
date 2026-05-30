"""GraphStore 契约测试（接口对换：内存属性图 与 SQLite 属性图）。

覆盖：增量 upsert 合并语义、degree 维护、chunk 状态、按 chunk 级联删除、图邻域扩展。
"""
from __future__ import annotations

import aiosqlite
import pytest

from core.domain.models import GraphEntity, GraphRelation
from core.repository.graph_store.base import GraphStore
from core.repository.graph_store.memory import InMemoryGraphStore
from core.repository.graph_store.sqlite import SQLiteGraphStore
from migrations.runner import run_migrations


@pytest.fixture(params=["memory", "sqlite"])
async def store(request) -> GraphStore:
    if request.param == "memory":
        return InMemoryGraphStore()
    else:
        # SQLite store setup
        conn = await aiosqlite.connect(":memory:")
        await conn.execute("PRAGMA foreign_keys = ON")
        await run_migrations(conn)

        # 播种父级记录以满足外键约束 (graph_chunk_status.chunk_id -> chunks.chunk_id)
        await conn.execute(
            "INSERT INTO collections (name, created_at) VALUES ('default', '2026-01-01T00:00:00Z')"
        )
        await conn.execute(
            """
            INSERT INTO documents (
                doc_id, title, file_path, content_type, size_bytes,
                content_hash, collection, created_at, updated_at
            )
            VALUES (
                'doc', 'doc', '/path', 'pdf', 100, 'hash', 'default',
                '2026-01-01', '2026-01-01'
            )
            """
        )
        await conn.execute(
            "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash) "
            "VALUES ('c0', 'doc', 0, 'text0', 'h0')"
        )
        await conn.execute(
            "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash) "
            "VALUES ('c1', 'doc', 1, 'text1', 'h1')"
        )
        await conn.commit()

        sqlite_store = SQLiteGraphStore(conn)
        return sqlite_store


async def test_upsert_entities_merges(store: GraphStore) -> None:
    await store.upsert_entities([GraphEntity("e1", "Alice", "person", "desc-a", ["c0"])])
    await store.upsert_entities([GraphEntity("e1", "Alice", "", "desc-b", ["c1"])])
    ent = await store.get_entity("e1")
    assert ent is not None
    assert set(ent.source_chunk_ids) == {"c0", "c1"}
    assert "desc-a" in ent.description and "desc-b" in ent.description
    assert ent.entity_type == "person"  # 已有类型不被空值覆盖


async def test_upsert_relations_accumulates_weight_and_degree(store: GraphStore) -> None:
    await store.upsert_entities(
        [GraphEntity("e1", "A", source_chunk_ids=["c0"]),
         GraphEntity("e2", "B", source_chunk_ids=["c0"])]
    )
    await store.upsert_relations(
        [GraphRelation("r1", "e1", "e2", "knows", weight=1.0, source_chunk_ids=["c0"])]
    )
    await store.upsert_relations(
        [GraphRelation("r1", "e1", "e2", "knows", weight=2.0, source_chunk_ids=["c1"])]
    )
    neighbors = await store.get_neighbors("e1", depth=1)
    assert len(neighbors) == 1
    assert neighbors[0].weight == pytest.approx(3.0)
    assert set(neighbors[0].source_chunk_ids) == {"c0", "c1"}
    e1 = await store.get_entity("e1")
    assert e1 is not None and e1.degree == 1


async def test_chunk_status_roundtrip(store: GraphStore) -> None:
    assert await store.get_chunk_status("c0") is None
    await store.set_chunk_status("c0", "hashA")
    assert await store.get_chunk_status("c0") == "hashA"
    await store.set_chunk_status("c0", "hashB")
    assert await store.get_chunk_status("c0") == "hashB"


async def test_find_entities_by_name(store: GraphStore) -> None:
    await store.upsert_entities([GraphEntity("e1", "Alice ", source_chunk_ids=["c0"])])
    assert [e.entity_id for e in await store.find_entities_by_name("alice")] == ["e1"]
    assert await store.find_entities_by_name("bob") == []


async def test_list_entities_and_relations_ordered(store: GraphStore) -> None:
    await store.upsert_entities([
        GraphEntity("e1", "Beta", source_chunk_ids=["c0"]),
        GraphEntity("e2", "Alpha", source_chunk_ids=["c0"]),
        GraphEntity("e3", "Gamma", source_chunk_ids=["c0"]),
    ])
    await store.upsert_relations([
        GraphRelation("r1", "e1", "e2", "to", weight=1.0, source_chunk_ids=["c0"]),
        GraphRelation("r2", "e1", "e3", "to", weight=3.0, source_chunk_ids=["c0"]),
    ])

    assert [e.entity_id for e in await store.list_entities()] == ["e1", "e2", "e3"]
    assert [r.relation_id for r in await store.list_relations()] == ["r2", "r1"]


async def test_delete_by_chunk_prunes_dangling(store: GraphStore) -> None:
    await store.upsert_entities(
        [GraphEntity("e1", "A", source_chunk_ids=["c0"]),
         GraphEntity("e2", "B", source_chunk_ids=["c0", "c1"])]
    )
    await store.upsert_relations(
        [GraphRelation("r1", "e1", "e2", "knows", source_chunk_ids=["c0"])]
    )
    await store.set_chunk_status("c0", "h")

    await store.delete_by_chunk("c0")
    # e1 仅由 c0 支撑 → 删除；其边 r1 随之删除
    assert await store.get_entity("e1") is None
    assert await store.get_neighbors("e2", depth=1) == []
    # e2 还有 c1 支撑 → 保留，但来源中 c0 被移除
    e2 = await store.get_entity("e2")
    assert e2 is not None and e2.source_chunk_ids == ["c1"]
    assert await store.get_chunk_status("c0") is None


async def test_get_neighbors_depth_and_edges(store: GraphStore) -> None:
    await store.upsert_entities(
        [GraphEntity(eid, eid, source_chunk_ids=["c0"]) for eid in ("e1", "e2", "e3")]
    )
    await store.upsert_relations(
        [
            GraphRelation("r1", "e1", "e2", "to", source_chunk_ids=["c0"]),
            GraphRelation("r2", "e2", "e3", "to", source_chunk_ids=["c0"]),
        ]
    )
    assert {r.relation_id for r in await store.get_neighbors("e1", depth=1)} == {"r1"}
    assert {r.relation_id for r in await store.get_neighbors("e1", depth=2)} == {"r1", "r2"}
    assert await store.get_neighbors("e1", depth=0) == []
    assert await store.get_neighbors("missing", depth=1) == []
