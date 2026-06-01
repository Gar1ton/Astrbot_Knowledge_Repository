"""统一检索编排器 (Retrieval Orchestrator) 的实现。

作为检索中枢，并发/顺序调度 Dense Vector、SQLite Lexical(词汇硬匹配) 与 Graph-RAG 多路召回，
并通过互惠排名融合（RRF）算法进行科学打分与去重，最终输出面向大模型的最优标准证据段。
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from core.domain.models import DocumentChunk

if TYPE_CHECKING:
    from core.config import Config
    from core.repository.embedding.base import EmbeddingProvider
    from core.repository.graph_store.base import GraphStore
    from core.repository.kb_reader.base import KnowledgeBaseReader
    from core.repository.source_store.base import SourceDocumentStore
    from core.repository.vector_store.base import VectorStore

logger = logging.getLogger("RetrievalOrchestrator")


class RetrievalOrchestrator:
    """整合多路检索、RRF 排序融合以及去重的业务编排核心。"""

    def __init__(
        self,
        *,
        source_store: SourceDocumentStore,
        kb_reader: KnowledgeBaseReader,
        config: Config,
        vector_store: VectorStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        graph_store: GraphStore | None = None,
    ) -> None:
        self._source_store = source_store
        self._kb_reader = kb_reader
        self._config = config
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._graph_store = graph_store

    async def retrieve(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> list[DocumentChunk]:
        """执行大一统混合检索。

        整合 Dense, Lexical, Graph-RAG 多路召回并采用 RRF 打分融合，截取 top_k 最优分块。
        """
        if top_k <= 0:
            return []

        # 获取当前系统的 RRF 常量（复用既有图谱 RRF K，默认 60）
        graph_config = self._config.get_graph_config()
        rrf_k = getattr(graph_config, "rrf_k", 60)

        # ── 1. 密向量召回路 (Dense Vector Road) ───────────────────────────
        dense_chunks: list[DocumentChunk] = []
        vdb = self._config.get_vector_db_config()
        
        if vdb.backend == "milvus" and self._vector_store and self._embedding_provider:
            logger.info("Executing local Milvus Lite dense vector search...")
            try:
                # 将 Query 进行 Embedding 向量化转换
                query_vector = await self._embedding_provider.embed_query(query)
                # 执行本地向量库检索，返回 (chunk_id, score)
                vec_results = await self._vector_store.search(
                    collection=collection,
                    query_vector=query_vector,
                    top_k=top_k * 2
                )
                # 从 SQLite 事实源批量反查，组装成 clean domain DocumentChunk 实体
                for cid, _ in vec_results:
                    chunk_meta = await self._find_local_chunk(cid)
                    if chunk_meta:
                        dense_chunks.append(chunk_meta)
            except Exception as e:
                logger.error(f"Local Milvus Lite dense search failed: {e}. Falling back...")
        
        # 如果不是 milvus 后端，或者 milvus 发生异常，回退到主框架内置检索
        if not dense_chunks:
            logger.info("Executing AstrBot native knowledge base search...")
            try:
                dense_chunks = await self._kb_reader.search(collection, query, top_k * 2)
            except Exception as e:
                logger.error(f"AstrBot native search fallback failed: {e}")

        # ── 2. 词汇硬匹配召回路 (Lexical Road - 学术名词防空防线) ─────────────
        lexical_chunks: list[DocumentChunk] = []
        try:
            lexical_chunks = await self._search_lexical_sqlite(collection, query, top_k * 2)
            if lexical_chunks:
                logger.info(
                    f"Successfully retrieved {len(lexical_chunks)} chunks via Lexical road."
                )
        except Exception as e:
            logger.error(f"SQLite Lexical search failed: {e}")

        # ── 3. 知识图谱召回路 (Graph-RAG Road - 深度语义关联) ───────────────
        graph_chunks: list[DocumentChunk] = []
        if self._graph_store and graph_config.enabled:
            logger.info("Executing Graph-RAG association search...")
            try:
                # 简单分词，清洗出实体词汇
                terms = [t.strip().lower() for t in re.split(r"\s+", query) if t.strip()]
                matched_entities = []
                seen_entity_ids = set()
                
                for term in terms:
                    # 匹配长度大于 2 的关键词
                    if len(term) >= 2:
                        ents = await self._graph_store.find_entities_by_name(term)
                        for ent in ents:
                            if ent.entity_id not in seen_entity_ids:
                                seen_entity_ids.add(ent.entity_id)
                                matched_entities.append(ent)

                # 提取关键词实体直接支撑的 Chunks 与 1-hop 邻域关联 Chunks
                seen_chunk_ids = set()
                for ent in matched_entities:
                    # 实体贡献的 chunks
                    for ch_id in ent.source_chunk_ids:
                        if ch_id not in seen_chunk_ids:
                            seen_chunk_ids.add(ch_id)
                            chunk_meta = await self._find_local_chunk(ch_id)
                            if chunk_meta:
                                graph_chunks.append(chunk_meta)
                                
                    # 1-hop 关联关系中支撑的 chunks
                    neighbors = await self._graph_store.get_neighbors(ent.entity_id, depth=1)
                    for rel in neighbors:
                        for ch_id in rel.source_chunk_ids:
                            if ch_id not in seen_chunk_ids:
                                seen_chunk_ids.add(ch_id)
                                chunk_meta = await self._find_local_chunk(ch_id)
                                if chunk_meta:
                                    graph_chunks.append(chunk_meta)
            except Exception as e:
                logger.error(f"Graph-RAG association search failed: {e}")

        # ── 4. 互惠排名融合 (RRF) 计算与去重 ─────────────────────────────
        rrf_scores: dict[str, tuple[DocumentChunk, float]] = {}

        def _add_rrf_rank(chunk_list: list[DocumentChunk]) -> None:
            for rank, ch in enumerate(chunk_list):
                cid = ch.chunk_id
                score = 1.0 / (rrf_k + (rank + 1))
                if cid in rrf_scores:
                    curr_ch, curr_score = rrf_scores[cid]
                    rrf_scores[cid] = (curr_ch, curr_score + score)
                else:
                    rrf_scores[cid] = (ch, score)

        _add_rrf_rank(dense_chunks)
        _add_rrf_rank(lexical_chunks)
        _add_rrf_rank(graph_chunks)

        # 按照 RRF 得分由高到低排序，截取 Top-K
        sorted_results = sorted(
            rrf_scores.values(), key=lambda item: item[1], reverse=True
        )
        return [item[0] for item in sorted_results[:top_k]]

    async def _search_lexical_sqlite(
        self, collection: str, query: str, limit: int
    ) -> list[DocumentChunk]:
        """从 SQLite 文档库中对指定集合的 Chunks 执行精确的词汇硬匹配检索。"""
        # 分词过滤
        terms = [t.strip().lower() for t in re.split(r"\s+", query) if t.strip()]
        if not terms:
            return []

        db_conn = getattr(self._source_store, "_db", None)
        if db_conn is None:
            return []

        # 1. 查询当前集合下所有的 doc_id
        doc_ids: list[str] = []
        async with db_conn.execute(
            "SELECT doc_id FROM documents WHERE collection = ?", (collection,)
        ) as cursor:
            async for row in cursor:
                doc_ids.append(row[0])

        if not doc_ids:
            return []

        # 2. 构造 LIKE 子句
        doc_placeholders = ",".join("?" for _ in doc_ids)
        like_parts = []
        params = list(doc_ids)

        for term in terms:
            # 仅匹配有意义的长名词
            if len(term) >= 2:
                like_parts.append("text LIKE ?")
                params.append(f"%{term}%")

        if not like_parts:
            return []

        like_query = " OR ".join(like_parts)
        sql = (
            f"SELECT chunk_id, doc_id, ordinal, text, content_hash "
            f"FROM chunks "
            f"WHERE doc_id IN ({doc_placeholders}) AND ({like_query}) "
            f"LIMIT {limit * 2}"
        )

        # 3. 执行词匹配检索并动态计算匹配频次打分
        matched_chunks: list[tuple[DocumentChunk, int]] = []
        async with db_conn.execute(sql, params) as cursor:
            async for row in cursor:
                chunk = DocumentChunk(
                    chunk_id=row[0],
                    doc_id=row[1],
                    ordinal=row[2],
                    text=row[3],
                    content_hash=row[4],
                )
                
                # 计算总的关键词匹配出现次数作为粗略相关性打分
                lower_text = chunk.text.lower()
                match_count = sum(lower_text.count(term) for term in terms)
                matched_chunks.append((chunk, match_count))

        # 按匹配频次降序排序
        matched_chunks.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in matched_chunks[:limit]]

    async def _find_local_chunk(self, chunk_id: str) -> DocumentChunk | None:
        """根据 chunk_id 直接从 SQLite 反查文本分块详情。"""
        db_conn = getattr(self._source_store, "_db", None)
        if db_conn is None:
            return None
        try:
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


__all__ = ["RetrievalOrchestrator"]
