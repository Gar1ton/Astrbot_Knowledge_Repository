"""SQLite 仓储实现。

基于 aiosqlite 进行异步数据库交互，完成图谱实体与关系的增量更新、合并、级联删除与图扩展查询。
遵循 GraphStore 接口，执行参数化查询防止 SQL 注入。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.domain.models import GraphEntity, GraphRelation
from core.repository.graph_store.base import GraphStore

if TYPE_CHECKING:
    import aiosqlite


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    """保序去重并入 extra 到 base，返回新列表。"""
    seen = dict.fromkeys(base)
    for item in extra:
        seen.setdefault(item, None)
    return list(seen)


class SQLiteGraphStore(GraphStore):
    """基于 SQLite/aiosqlite 的生产 GraphStore 实现。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── 写入（增量）──────────────────────────────────────────────

    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        for ent in entities:
            # 1) 检查实体是否已存在
            async with self._db.execute(
                "SELECT entity_type, description, source_chunk_ids, degree "
                "FROM graph_entities WHERE entity_id = ?",
                (ent.entity_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                # 不存在，直接插入
                source_chunks_str = json.dumps(ent.source_chunk_ids)
                await self._db.execute(
                    """
                    INSERT INTO graph_entities (
                        entity_id, name, entity_type, description, source_chunk_ids, degree
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ent.entity_id,
                        ent.name,
                        ent.entity_type,
                        ent.description,
                        source_chunks_str,
                        ent.degree,
                    ),
                )
            else:
                # 已存在，执行合并逻辑
                existing_type = row[0]
                existing_desc = row[1]
                existing_chunks = json.loads(row[2])

                merged_chunks = _merge_unique(existing_chunks, ent.source_chunk_ids)
                merged_desc = existing_desc
                if ent.description and ent.description not in existing_desc:
                    merged_desc = f"{existing_desc}\n{ent.description}".strip()

                final_type = existing_type or ent.entity_type

                await self._db.execute(
                    """
                    UPDATE graph_entities
                    SET entity_type = ?, description = ?, source_chunk_ids = ?
                    WHERE entity_id = ?
                    """,
                    (final_type, merged_desc, json.dumps(merged_chunks), ent.entity_id),
                )

        await self._recompute_degrees()
        await self._db.commit()

    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        for rel in relations:
            # 1) 检查关系是否已存在
            async with self._db.execute(
                "SELECT weight, source_chunk_ids, description "
                "FROM graph_relations WHERE relation_id = ?",
                (rel.relation_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                # 不存在，直接插入
                source_chunks_str = json.dumps(rel.source_chunk_ids)
                await self._db.execute(
                    """
                    INSERT INTO graph_relations (
                        relation_id, src_entity_id, dst_entity_id, relation, description,
                        weight, source_chunk_ids
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rel.relation_id,
                        rel.src_entity_id,
                        rel.dst_entity_id,
                        rel.relation,
                        rel.description,
                        rel.weight,
                        source_chunks_str,
                    ),
                )
            else:
                # 已存在，累加权重、合并 chunk 和描述
                existing_weight = row[0]
                existing_chunks = json.loads(row[1])
                existing_desc = row[2]

                merged_chunks = _merge_unique(existing_chunks, rel.source_chunk_ids)
                merged_weight = existing_weight + rel.weight
                merged_desc = existing_desc
                if rel.description and rel.description not in existing_desc:
                    merged_desc = f"{existing_desc}\n{rel.description}".strip()

                await self._db.execute(
                    """
                    UPDATE graph_relations
                    SET weight = ?, source_chunk_ids = ?, description = ?
                    WHERE relation_id = ?
                    """,
                    (merged_weight, json.dumps(merged_chunks), merged_desc, rel.relation_id),
                )

        await self._recompute_degrees()
        await self._db.commit()

    async def delete_by_chunk(self, chunk_id: str) -> None:
        # 1) 先处理关系：从关系的 source_chunk_ids 移除该 chunk。若清空则删除关系
        async with self._db.execute(
            "SELECT relation_id, source_chunk_ids FROM graph_relations"
        ) as cursor:
            rel_rows = await cursor.fetchall()

        for row in rel_rows:
            rel_id, sc_ids_json = row
            sc_ids = json.loads(sc_ids_json)
            if chunk_id in sc_ids:
                sc_ids = [c for c in sc_ids if c != chunk_id]
                if not sc_ids:
                    await self._db.execute(
                        "DELETE FROM graph_relations WHERE relation_id = ?", (rel_id,)
                    )
                else:
                    await self._db.execute(
                        "UPDATE graph_relations SET source_chunk_ids = ? WHERE relation_id = ?",
                        (json.dumps(sc_ids), rel_id),
                    )

        # 2) 再处理实体：从实体的 source_chunk_ids 移除该 chunk。若清空则删除节点（级联删除边）
        async with self._db.execute(
            "SELECT entity_id, source_chunk_ids FROM graph_entities"
        ) as cursor:
            ent_rows = await cursor.fetchall()

        for row in ent_rows:
            ent_id, sc_ids_json = row
            sc_ids = json.loads(sc_ids_json)
            if chunk_id in sc_ids:
                sc_ids = [c for c in sc_ids if c != chunk_id]
                if not sc_ids:
                    await self._db.execute(
                        "DELETE FROM graph_entities WHERE entity_id = ?", (ent_id,)
                    )
                else:
                    await self._db.execute(
                        "UPDATE graph_entities SET source_chunk_ids = ? WHERE entity_id = ?",
                        (json.dumps(sc_ids), ent_id),
                    )

        # 3) 移除 chunk 状态登记
        await self._db.execute(
            "DELETE FROM graph_chunk_status WHERE chunk_id = ?", (chunk_id,)
        )

        await self._recompute_degrees()
        await self._db.commit()

    # ── 增量状态 ────────────────────────────────────────────────

    async def get_chunk_status(self, chunk_id: str) -> str | None:
        async with self._db.execute(
            "SELECT content_hash FROM graph_chunk_status WHERE chunk_id = ?", (chunk_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row is not None else None

    async def set_chunk_status(self, chunk_id: str, content_hash: str) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO graph_chunk_status (chunk_id, content_hash, extracted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                extracted_at = excluded.extracted_at
            """,
            (chunk_id, content_hash, now_str),
        )
        await self._db.commit()

    # ── 读取（dual-level 召回 + 图扩展）──────────────────────────

    async def get_entity(self, entity_id: str) -> GraphEntity | None:
        async with self._db.execute(
            "SELECT name, entity_type, description, source_chunk_ids, degree "
            "FROM graph_entities WHERE entity_id = ?",
            (entity_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return GraphEntity(
                entity_id=entity_id,
                name=row[0],
                entity_type=row[1],
                description=row[2],
                source_chunk_ids=json.loads(row[3]),
                degree=row[4],
            )

    async def find_entities_by_name(self, name: str) -> list[GraphEntity]:
        key = name.strip().lower()
        async with self._db.execute(
            """
            SELECT entity_id, name, entity_type, description, source_chunk_ids, degree
            FROM graph_entities
            WHERE LOWER(TRIM(name)) = ?
            """,
            (key,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                GraphEntity(
                    entity_id=row[0],
                    name=row[1],
                    entity_type=row[2],
                    description=row[3],
                    source_chunk_ids=json.loads(row[4]),
                    degree=row[5],
                )
                for row in rows
            ]

    async def get_neighbors(
        self, entity_id: str, depth: int = 1
    ) -> list[GraphRelation]:
        # 验证实体是否存在
        entity = await self.get_entity(entity_id)
        if depth <= 0 or entity is None:
            return []

        visited: set[str] = {entity_id}
        frontier: set[str] = {entity_id}
        collected_relations: dict[str, GraphRelation] = {}

        for _ in range(depth):
            if not frontier:
                break

            # 动态构造批量 IN 查询以执行高效 BFS 扩展
            placeholders = ",".join("?" for _ in frontier)
            query = f"""
                SELECT relation_id, src_entity_id, dst_entity_id, relation,
                       description, weight, source_chunk_ids
                FROM graph_relations
                WHERE src_entity_id IN ({placeholders})
            """
            async with self._db.execute(query, list(frontier)) as cursor:
                rows = await cursor.fetchall()

            next_frontier: set[str] = set()
            for row in rows:
                rel_id, src, dst, relation, desc, weight, sc_ids_json = row
                rel = GraphRelation(
                    relation_id=rel_id,
                    src_entity_id=src,
                    dst_entity_id=dst,
                    relation=relation,
                    description=desc,
                    weight=weight,
                    source_chunk_ids=json.loads(sc_ids_json),
                )
                collected_relations[rel_id] = rel
                if dst not in visited:
                    next_frontier.add(dst)

            visited |= next_frontier
            frontier = next_frontier

        return list(collected_relations.values())

    # ── 内部维护 ────────────────────────────────────────────────

    async def _recompute_degrees(self) -> None:
        """根据边连接状态动态重算全图所有实体的度。"""
        # 1) 获取所有实体的 degree dict，初始化为 0
        async with self._db.execute("SELECT entity_id FROM graph_entities") as cursor:
            rows = await cursor.fetchall()
            degrees = {r[0]: 0 for r in rows}

        # 2) 统计所有关系的连接度
        async with self._db.execute(
            "SELECT src_entity_id, dst_entity_id FROM graph_relations"
        ) as cursor:
            rel_rows = await cursor.fetchall()

        for src, dst in rel_rows:
            if src in degrees:
                degrees[src] += 1
            if dst in degrees:
                degrees[dst] += 1

        # 3) 批量回写数据库
        for ent_id, deg in degrees.items():
            await self._db.execute(
                "UPDATE graph_entities SET degree = ? WHERE entity_id = ?",
                (deg, ent_id),
            )
