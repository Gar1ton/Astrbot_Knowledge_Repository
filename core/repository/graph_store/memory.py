"""GraphStore 的内存实现（无 I/O，供接口对换测试）。

实现 upsert 合并语义、按 chunk 级联删除、增量状态与图邻域扩展（BFS），确定性、无外部依赖。
不含向量相似度（那属于生产 sqlite.py + numpy）；本实现以 name 精确匹配支撑归并与召回契约。
"""
from __future__ import annotations

import copy

from core.domain.models import GraphEntity, GraphRelation
from core.repository.graph_store.base import GraphStore


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    """保序去重并入 extra 到 base，返回新列表。"""
    seen = dict.fromkeys(base)
    for item in extra:
        seen.setdefault(item, None)
    return list(seen)


class InMemoryGraphStore(GraphStore):
    """纯内存属性图：实体/关系 dict + chunk 状态 dict。"""

    def __init__(self) -> None:
        self._entities: dict[str, GraphEntity] = {}
        self._relations: dict[str, GraphRelation] = {}
        self._chunk_status: dict[str, str] = {}

    # ── 写入（增量）──────────────────────────────────────────────

    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        for ent in entities:
            existing = self._entities.get(ent.entity_id)
            if existing is None:
                self._entities[ent.entity_id] = copy.deepcopy(ent)
            else:
                existing.source_chunk_ids = _merge_unique(
                    existing.source_chunk_ids, ent.source_chunk_ids
                )
                if ent.description and ent.description not in existing.description:
                    existing.description = (
                        f"{existing.description}\n{ent.description}".strip()
                    )
                if not existing.entity_type:
                    existing.entity_type = ent.entity_type
        self._recompute_degrees()

    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        for rel in relations:
            existing = self._relations.get(rel.relation_id)
            if existing is None:
                self._relations[rel.relation_id] = copy.deepcopy(rel)
            else:
                existing.weight += rel.weight
                existing.source_chunk_ids = _merge_unique(
                    existing.source_chunk_ids, rel.source_chunk_ids
                )
        self._recompute_degrees()

    async def delete_by_chunk(self, chunk_id: str) -> None:
        # 先处理关系：source 清空的边删除
        for rel_id in list(self._relations):
            rel = self._relations[rel_id]
            if chunk_id in rel.source_chunk_ids:
                rel.source_chunk_ids = [c for c in rel.source_chunk_ids if c != chunk_id]
                if not rel.source_chunk_ids:
                    del self._relations[rel_id]
        # 再处理实体：source 清空的节点连同其边删除
        for ent_id in list(self._entities):
            ent = self._entities[ent_id]
            if chunk_id in ent.source_chunk_ids:
                ent.source_chunk_ids = [c for c in ent.source_chunk_ids if c != chunk_id]
                if not ent.source_chunk_ids:
                    self._remove_entity(ent_id)
        self._chunk_status.pop(chunk_id, None)
        self._recompute_degrees()

    # ── 增量状态 ────────────────────────────────────────────────

    async def get_chunk_status(self, chunk_id: str) -> str | None:
        return self._chunk_status.get(chunk_id)

    async def set_chunk_status(self, chunk_id: str, content_hash: str) -> None:
        self._chunk_status[chunk_id] = content_hash

    # ── 读取 ────────────────────────────────────────────────────

    async def get_entity(self, entity_id: str) -> GraphEntity | None:
        ent = self._entities.get(entity_id)
        return copy.deepcopy(ent) if ent is not None else None

    async def find_entities_by_name(self, name: str) -> list[GraphEntity]:
        key = name.strip().lower()
        return [
            copy.deepcopy(e)
            for e in self._entities.values()
            if e.name.strip().lower() == key
        ]

    async def list_entities(self) -> list[GraphEntity]:
        ordered = sorted(
            self._entities.values(),
            key=lambda e: (-e.degree, e.name.lower(), e.entity_id),
        )
        return [copy.deepcopy(e) for e in ordered]

    async def list_relations(self) -> list[GraphRelation]:
        ordered = sorted(
            self._relations.values(),
            key=lambda r: (-r.weight, r.relation_id),
        )
        return [copy.deepcopy(r) for r in ordered]

    async def get_neighbors(self, entity_id: str, depth: int = 1) -> list[GraphRelation]:
        if depth <= 0 or entity_id not in self._entities:
            return []
        visited: set[str] = {entity_id}
        frontier: set[str] = {entity_id}
        collected: dict[str, GraphRelation] = {}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for rel in self._relations.values():
                if rel.src_entity_id in frontier:
                    collected.setdefault(rel.relation_id, rel)
                    if rel.dst_entity_id not in visited:
                        next_frontier.add(rel.dst_entity_id)
            visited |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        return [copy.deepcopy(r) for r in collected.values()]

    # ── 内部维护 ────────────────────────────────────────────────

    def _remove_entity(self, entity_id: str) -> None:
        del self._entities[entity_id]
        for rel_id in list(self._relations):
            rel = self._relations[rel_id]
            if entity_id in (rel.src_entity_id, rel.dst_entity_id):
                del self._relations[rel_id]

    def _recompute_degrees(self) -> None:
        degree: dict[str, int] = {eid: 0 for eid in self._entities}
        for rel in self._relations.values():
            if rel.src_entity_id in degree:
                degree[rel.src_entity_id] += 1
            if rel.dst_entity_id in degree:
                degree[rel.dst_entity_id] += 1
        for eid, deg in degree.items():
            self._entities[eid].degree = deg


__all__ = ["InMemoryGraphStore"]
