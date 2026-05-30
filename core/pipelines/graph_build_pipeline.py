"""知识图谱增量构建管道（pipelines 层）。

编排增量文献切片比对、调用 LLM 结构化抽取、动态外键约束完整性保护（自动生成悬空实体桩）、
以及 SQLite 属性图的增量 upsert 事务闭环。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.domain.models import GraphEntity, GraphRelation

if TYPE_CHECKING:
    from core.adapters.llm import LLMAdapter
    from core.config import GraphConfig
    from core.repository.graph_store.base import GraphStore
    from core.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("GraphBuildPipeline")


def _normalize_id(name: str) -> str:
    """归一化实体名称生成稳定的 entity_id。"""
    return name.strip().lower()


class GraphBuildPipeline:
    """知识图谱构建管线。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        graph_store: GraphStore,
        llm_adapter: LLMAdapter,
        config: GraphConfig,
    ) -> None:
        self._source_store = source_store
        self._graph_store = graph_store
        self._llm_adapter = llm_adapter
        self._config = config

    async def build_graph(self, collection: str | None = None) -> dict[str, Any]:
        """增量分析文档切片，抽取实体与关系网织入图谱数据库。

        collection=None 时对全量文献执行增量构建。
        """
        # 1) 获取待处理的文档列表
        docs = await self._source_store.list_documents(collection=collection)

        # 2) 聚合文档分块
        all_chunks = []
        for doc in docs:
            chunks = await self._source_store.list_chunks(doc.doc_id)
            all_chunks.extend(chunks)

        total_chunks = len(all_chunks)
        extracted_chunks = 0
        skipped_chunks = 0
        deleted_stale_chunks = 0

        # 默认回退类别
        default_type = (
            self._config.entity_types[0]
            if self._config.entity_types
            else "Method/Algorithm"
        )

        # 3) 遍历分块执行增量比对与 LLM 抽取
        for chunk in all_chunks:
            chunk_id = chunk.chunk_id
            content_hash = chunk.content_hash

            last_hash = None
            if self._config.incremental:
                last_hash = await self._graph_store.get_chunk_status(chunk_id)
                # 增量比对：若文本哈希未改变，则跳过
                if last_hash == content_hash:
                    skipped_chunks += 1
                    continue

            # 若文本发生改变（且已存在旧记录），先安全删除该 chunk 以前提取出的所有边/点贡献
            # 防止老旧废弃数据在图谱数据库内堆积
            if last_hash is not None:
                await self._graph_store.delete_by_chunk(chunk_id)
                deleted_stale_chunks += 1

            # 4) 调用 LLM 适配器进行结构化图谱抽取
            result = await self._llm_adapter.extract_graph(
                text=chunk.text, entity_types=self._config.entity_types
            )

            extracted_entities = result.get("entities", [])
            extracted_relations = result.get("relations", [])

            # 5) 实体映射与类型过滤
            entities_to_upsert: dict[str, GraphEntity] = {}
            for ent in extracted_entities:
                name = ent.get("name", "").strip()
                if not name:
                    continue
                ent_id = _normalize_id(name)
                # 确保提取类型合法，不匹配时强制对齐
                ent_type = ent.get("type", "").strip()
                if ent_type not in self._config.entity_types:
                    ent_type = default_type

                entities_to_upsert[ent_id] = GraphEntity(
                    entity_id=ent_id,
                    name=name,
                    entity_type=ent_type,
                    description=ent.get("description", "").strip(),
                    source_chunk_ids=[chunk_id],
                )

            # 6) 关系映射与外键依赖自我修复（外键桩保护）
            relations_to_upsert: list[GraphRelation] = []
            for rel in extracted_relations:
                src_name = rel.get("src", "").strip()
                dst_name = rel.get("dst", "").strip()
                relation_name = rel.get("relation", "").strip()
                if not src_name or not dst_name or not relation_name:
                    continue

                src_id = _normalize_id(src_name)
                dst_id = _normalize_id(dst_name)
                rel_id = f"{src_id}:{dst_id}:{_normalize_id(relation_name)}"

                # 💡 外键完整性保护：若关系中的 src 或 dst 未出现在实体列表中，
                # 必须动态生成对应的实体桩（Placeholder），防止外键约束失败！
                if src_id not in entities_to_upsert:
                    existing_src = await self._graph_store.get_entity(src_id)
                    if existing_src is None:
                        entities_to_upsert[src_id] = GraphEntity(
                            entity_id=src_id,
                            name=src_name,
                            entity_type=default_type,
                            description=f"[Placeholder] Stub entity for {src_name}",
                            source_chunk_ids=[chunk_id],
                        )

                if dst_id not in entities_to_upsert:
                    existing_dst = await self._graph_store.get_entity(dst_id)
                    if existing_dst is None:
                        entities_to_upsert[dst_id] = GraphEntity(
                            entity_id=dst_id,
                            name=dst_name,
                            entity_type=default_type,
                            description=f"[Placeholder] Stub entity for {dst_name}",
                            source_chunk_ids=[chunk_id],
                        )

                relations_to_upsert.append(
                    GraphRelation(
                        relation_id=rel_id,
                        src_entity_id=src_id,
                        dst_entity_id=dst_id,
                        relation=relation_name,
                        description=rel.get("description", "").strip(),
                        weight=float(rel.get("weight", 1.0)),
                        source_chunk_ids=[chunk_id],
                    )
                )

            # 7) 写入图数据库持久层
            if entities_to_upsert:
                await self._graph_store.upsert_entities(list(entities_to_upsert.values()))
            if relations_to_upsert:
                await self._graph_store.upsert_relations(relations_to_upsert)

            # 8) 登记分块成功抽取状态
            await self._graph_store.set_chunk_status(chunk_id, content_hash)
            extracted_chunks += 1

        return {
            "status": "success",
            "message": (
                f"图谱构建成功。共处理 {total_chunks} 个分块，"
                f"抽取 {extracted_chunks} 个，跳过 {skipped_chunks} 个。"
            ),
            "total_chunks": total_chunks,
            "extracted_chunks": extracted_chunks,
            "skipped_chunks": skipped_chunks,
            "deleted_stale_chunks": deleted_stale_chunks,
        }
