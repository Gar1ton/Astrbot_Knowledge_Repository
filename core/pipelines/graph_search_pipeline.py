"""知识图谱混合检索管道（pipelines 层）。

整合三路检索流：向量相似度召回（bge-m3 语义分块）、本地关键词精确召回（实体匹配）、
以及图邻域单步扩展召回（1-hop 边关联分块）。
采用互惠排名融合（RRF）算法，科学对齐排序权重，产出面向学术大模型（LLM）的高保真上下文。
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from core.domain.models import DocumentChunk

if TYPE_CHECKING:
    from core.config import GraphConfig
    from core.repository.graph_store.base import GraphStore
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("GraphSearchPipeline")


class GraphSearchPipeline:
    """属性图混合检索与 RRF 融合管道。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        graph_store: GraphStore,
        kb_reader: KnowledgeBaseReader,
        config: GraphConfig,
    ) -> None:
        self._source_store = source_store
        self._graph_store = graph_store
        self._kb_reader = kb_reader
        self._config = config

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        """执行混合图谱检索。

        合并：向量搜索分块、实体关联分块和邻居图谱分块，返回 RRF 排序后的 Top-K 结果与丰富上下文。
        """
        limit = top_k or self._config.query_top_k
        rrf_k = self._config.rrf_k

        # ── 1. 向量相似度召回（Stream 1） ──────────────────────────────────
        vector_chunks = await self._kb_reader.search(collection, query, limit * 2)

        # ── 2. 关键词实体召回（Stream 2） ──────────────────────────────────
        # 简单清洗并分词
        terms = [t.strip().lower() for t in re.split(r"\s+", query) if t.strip()]
        matched_entities = []
        seen_entity_ids = set()

        for term in terms:
            ents = await self._graph_store.find_entities_by_name(term)
            for ent in ents:
                if ent.entity_id not in seen_entity_ids:
                    seen_entity_ids.add(ent.entity_id)
                    matched_entities.append(ent)

        # 提取关键词实体直接支撑的 Chunks
        keyword_chunks: list[DocumentChunk] = []
        seen_chunk_ids_kw = set()
        for ent in matched_entities:
            for ch_id in ent.source_chunk_ids:
                if ch_id not in seen_chunk_ids_kw:
                    seen_chunk_ids_kw.add(ch_id)
                    # 💡 高效防错机制：尝试从本地 SourceDocumentStore 提取文本分块
                    chunk_meta = await self._find_local_chunk(ch_id)
                    if chunk_meta:
                        keyword_chunks.append(chunk_meta)

        # ── 3. 邻域图谱扩展（Stream 3） ────────────────────────────────────
        graph_chunks: list[DocumentChunk] = []
        seen_chunk_ids_graph = set()
        matched_relations = []
        seen_relation_ids = set()

        for ent in matched_entities:
            # 扩展 1 跳（1-hop）邻域内的关联边
            relations = await self._graph_store.get_neighbors(ent.entity_id, depth=1)
            for rel in relations:
                if rel.relation_id not in seen_relation_ids:
                    seen_relation_ids.add(rel.relation_id)
                    matched_relations.append(rel)

                for ch_id in rel.source_chunk_ids:
                    if ch_id not in seen_chunk_ids_graph:
                        seen_chunk_ids_graph.add(ch_id)
                        chunk_meta = await self._find_local_chunk(ch_id)
                        if chunk_meta:
                            graph_chunks.append(chunk_meta)

        # ── 4. 互惠排名融合（RRF）计算 ──────────────────────────────────────
        # rrf_scores 结构: {chunk_id: (chunk_obj, score)}
        rrf_scores: dict[str, tuple[DocumentChunk, float]] = {}

        # 辅助排序打分
        def _add_rrf_rank(chunk_list: list[DocumentChunk]) -> None:
            for rank, ch in enumerate(chunk_list):
                ch_id = ch.chunk_id
                score = 1.0 / (rrf_k + (rank + 1))
                if ch_id in rrf_scores:
                    curr_ch, curr_score = rrf_scores[ch_id]
                    rrf_scores[ch_id] = (curr_ch, curr_score + score)
                else:
                    rrf_scores[ch_id] = (ch, score)

        # 分别对三路检索结果注入排序打分
        _add_rrf_rank(vector_chunks)
        _add_rrf_rank(keyword_chunks)
        _add_rrf_rank(graph_chunks)

        # 按照 RRF 累加得分从高到低排序
        sorted_items = sorted(rrf_scores.values(), key=lambda item: item[1], reverse=True)
        final_chunks = [item[0] for item in sorted_items[:limit]]

        # ── 5. 上下文合成（Context Generation） ─────────────────────────────
        # 合成包含图谱实体、关系与排序后分块的富文本上下文，喂给学术大模型
        context_parts = []

        if matched_entities:
            context_parts.append("=== 检索到的知识图谱实体 (Related Entities) ===")
            for ent in matched_entities[:10]:  # 限制数量防超限
                context_parts.append(
                    f"- [{ent.entity_type}] {ent.name}: {ent.description} (Degree: {ent.degree})"
                )

        if matched_relations:
            context_parts.append("\n=== 检索到的知识图谱关系 (Related Relations) ===")
            for rel in matched_relations[:10]:
                context_parts.append(
                    f"- {rel.src_entity_id} --({rel.relation})--> {rel.dst_entity_id}: "
                    f"{rel.description} (Weight: {rel.weight})"
                )

        if final_chunks:
            context_parts.append("\n=== 精准检索文本分块 (Retrieved Text Chunks) ===")
            for rank, ch in enumerate(final_chunks):
                context_parts.append(
                    f"[Chunk {rank+1}] (DocID: {ch.doc_id}, Ordinal: {ch.ordinal})\n"
                    f"{ch.text}\n"
                )

        full_context = "\n".join(context_parts)

        result = {
            "status": "success",
            "query": query,
            "chunks": final_chunks,
            "entities": matched_entities,
            "relations": matched_relations,
            "context": full_context,
        }
        if debug:
            result["debug"] = {
                "vector_chunk_ids": [ch.chunk_id for ch in vector_chunks],
                "keyword_chunk_ids": [ch.chunk_id for ch in keyword_chunks],
                "graph_chunk_ids": [ch.chunk_id for ch in graph_chunks],
                "rrf_scores": {
                    chunk_id: score
                    for chunk_id, (_, score) in sorted(
                        rrf_scores.items(),
                        key=lambda item: item[1][1],
                        reverse=True,
                    )
                },
            }
        return result

    async def _find_local_chunk(self, chunk_id: str) -> DocumentChunk | None:
        """根据 chunk_id 从 SQLite 文档库中反查文本分块详情。"""
        # 由于 SourceDocumentStore 的基础接口没有 list_chunks 以外的单 chunk 反查
        # 故我们在这里做一个强健的反查方法：列出该分块可能所属文档的所有分块，然后过滤。
        # 为提高性能，我们从 chunks 表查出该 chunk_id 所属的 doc_id，再列出。
        try:
            # SQLite 数据库底层反查，若 store 是 SQLiteSourceDocumentStore 则性能极高
            # 如果是 InMemoryStore 也是无缝兼容的
            db_conn = getattr(self._source_store, "_db", None)
            if db_conn is not None:
                async with db_conn.execute(
                    "SELECT doc_id, ordinal, text, content_hash FROM chunks WHERE chunk_id = ?",
                    (chunk_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return DocumentChunk(
                            chunk_id=chunk_id,
                            doc_id=row[0],
                            ordinal=row[1],
                            text=row[2],
                            content_hash=row[3],
                        )
        except Exception as e:
            logger.error(f"Failed to find local chunk {chunk_id} directly: {e}")

        return None
