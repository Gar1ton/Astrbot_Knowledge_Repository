"""知识图谱存储接口（repository 层，接口先行）。

定义 LightRAG 风格属性图的持久化契约：实体/关系增量 upsert、按 chunk 级联删除、增量状态跟踪、
相似实体召回与图邻域扩展。生产实现 sqlite.py（SQLite 属性图），测试实现 memory.py 共用本接口。

「增量」核心在 chunk 状态：set/get_chunk_status 记录每个 chunk 上次抽取时的 content_hash，
pipeline 据此跳过未变 chunk，避免重复 LLM 抽取。本层只依赖 domain。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.models import GraphEntity, GraphRelation


class GraphStore(ABC):
    """实体/关系属性图仓储。

    标识约定：entity_id / relation_id 稳定唯一。upsert 语义为「存在则合并，否则新建」，
    合并细节（描述拼接、source_chunk_ids 取并集、weight 累加、degree 重算）由实现保证。
    """

    # ── 写入（增量）──────────────────────────────────────────────

    @abstractmethod
    async def upsert_entities(self, entities: list[GraphEntity]) -> None:
        """批量 upsert 实体。已存在（同 entity_id）时合并：描述拼接、source_chunk_ids 取并集。"""
        ...

    @abstractmethod
    async def upsert_relations(self, relations: list[GraphRelation]) -> None:
        """批量 upsert 关系。已存在（同 relation_id）时合并：weight 累加、source_chunk_ids 取并集。

        实现须据关系增量维护两端实体的 degree。
        """
        ...

    @abstractmethod
    async def delete_by_chunk(self, chunk_id: str) -> None:
        """删除某 chunk 的贡献：从相关实体/关系的 source_chunk_ids 移除该 chunk。

        同步顺序：先处理关系（source 清空的边删除）→ 再处理实体（source 清空的节点连同其边删除）。
        chunk 不存在为无操作（非异常）。
        """
        ...

    # ── 增量状态 ────────────────────────────────────────────────

    @abstractmethod
    async def get_chunk_status(self, chunk_id: str) -> str | None:
        """返回该 chunk 上次抽取时记录的 content_hash；未抽取过返回 None。"""
        ...

    @abstractmethod
    async def set_chunk_status(self, chunk_id: str, content_hash: str) -> None:
        """登记/更新某 chunk 的抽取状态（content_hash）。"""
        ...

    # ── 读取（dual-level 召回 + 图扩展）──────────────────────────

    @abstractmethod
    async def get_entity(self, entity_id: str) -> GraphEntity | None:
        """按 entity_id 取一条；不存在返回 None。"""
        ...

    @abstractmethod
    async def find_entities_by_name(self, name: str) -> list[GraphEntity]:
        """按规范化 name 精确匹配实体（用于归并与 low-level 关键词召回）。无匹配返回空列表。"""
        ...

    @abstractmethod
    async def list_entities(self) -> list[GraphEntity]:
        """列出全部实体，按 degree 降序、name 升序返回。无数据返回空列表。"""
        ...

    @abstractmethod
    async def list_relations(self) -> list[GraphRelation]:
        """列出全部关系，按 weight 降序、relation_id 升序返回。无数据返回空列表。"""
        ...

    @abstractmethod
    async def get_neighbors(
        self, entity_id: str, depth: int = 1
    ) -> list[GraphRelation]:
        """返回以 entity_id 为起点、depth 跳内可达的关系边（图邻域扩展）。

        depth<=0 返回空列表；实体不存在返回空列表。
        """
        ...


__all__ = ["GraphStore"]
