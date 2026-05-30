"""GraphSearchPipeline 单元测试。

验证图谱检索管线：向量检索召回、关键词精确实体检索、
1-hop 边邻居扩展、RRF 互惠排名打分及上下文生成逻辑。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from core.config import GraphConfig
from core.domain.models import DocumentChunk, GraphEntity, GraphRelation
from core.pipelines.graph_search_pipeline import GraphSearchPipeline
from core.repository.graph_store.sqlite import SQLiteGraphStore
from core.repository.kb_reader.base import KnowledgeBaseReader
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from migrations.runner import run_migrations


@pytest.fixture
async def db_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")
    await run_migrations(conn)

    # 播种集合与测试文档/分块，满足外键和反查 chunks 逻辑
    await conn.execute(
        "INSERT INTO collections (name, created_at) VALUES ('papers', '2026-01-01T00:00:00Z')"
    )
    await conn.execute(
        """
        INSERT INTO documents (
            doc_id, title, file_path, content_type, size_bytes,
            content_hash, collection, created_at, updated_at
        )
        VALUES ('d1', 'title1', '/p1', 'pdf', 100, 'hash1', 'papers', '2026-01-01', '2026-01-01')
        """
    )
    await conn.execute(
        "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash) "
        "VALUES ('c1', 'd1', 0, 'Transformer is deep.', 'chash1')"
    )
    await conn.execute(
        "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, content_hash) "
        "VALUES ('c2', 'd1', 1, 'Attention is powerful.', 'chash2')"
    )
    await conn.commit()
    return conn


@pytest.fixture
def source_store(db_conn: aiosqlite.Connection) -> SQLiteSourceDocumentStore:
    return SQLiteSourceDocumentStore(db_conn)


@pytest.fixture
def graph_store(db_conn: aiosqlite.Connection) -> SQLiteGraphStore:
    return SQLiteGraphStore(db_conn)


@pytest.fixture
def graph_config() -> GraphConfig:
    return GraphConfig(
        enabled=True,
        incremental=True,
        rrf_k=60,
        query_top_k=5,
        entity_types=["Method", "Dataset", "Metric"],
    )


@pytest.mark.asyncio
async def test_graph_search_pipeline_hybrid_rrf_and_context(
    db_conn: aiosqlite.Connection,
    source_store: SQLiteSourceDocumentStore,
    graph_store: SQLiteGraphStore,
    graph_config: GraphConfig,
) -> None:
    # 1) 播种知识图谱实体与关系
    # e1: Transformer (Method), 支撑 chunk: c1
    # e2: Attention (Method), 支撑 chunk: c2
    # r1: Transformer --(uses)--> Attention, 支撑 chunk: c1
    await graph_store.upsert_entities([
        GraphEntity("transformer", "Transformer", "Method", "Self-attention model.", ["c1"]),
        GraphEntity("attention", "Attention", "Method", "Alignment mapping.", ["c2"]),
    ])
    await graph_store.upsert_relations([
        GraphRelation(
            "transformer:attention:uses",
            "transformer",
            "attention",
            "uses",
            "Transformer uses attention.",
            1.0,
            ["c1"],
        )
    ])

    # 2) 模拟 Stream 1 (向量搜索)，让其返回 chunk c2
    mock_reader = MagicMock(spec=KnowledgeBaseReader)
    mock_reader.search = AsyncMock(
        return_value=[
            DocumentChunk("c2", "d1", 1, "Attention is powerful.", "chash2")
        ]
    )

    pipeline = GraphSearchPipeline(
        source_store=source_store,
        graph_store=graph_store,
        kb_reader=mock_reader,
        config=graph_config,
    )

    # 3) 执行检索查询
    # 查询词 "Transformer" 将会：
    # - 激活向量检索 (返回 c2)
    # - 匹配关键字实体 "Transformer" (匹配 e1 -> 获取 c1)
    # - 拓扑扩展 1-hop 关系 r1 (获取 c1)
    res = await pipeline.search("papers", "Transformer", top_k=5)
    assert res["status"] == "success"
    assert res["query"] == "Transformer"

    # 4) 验证实体与关系召回
    # 关键字召回了 "transformer" 实体
    entities = {e.entity_id for e in res["entities"]}
    assert "transformer" in entities
    # 1-hop 召回了关联关系
    relations = {r.relation_id for r in res["relations"]}
    assert "transformer:attention:uses" in relations

    # 5) 验证 RRF 融合与去重
    # 最终召回分块列表包含了向量召回 (c2) 与实体/邻居反查召回 (c1)
    chunks = {ch.chunk_id for ch in res["chunks"]}
    assert chunks == {"c1", "c2"}

    # 6) 验证学术上下文生成格式
    context = res["context"]
    assert "=== 检索到的知识图谱实体 (Related Entities) ===" in context
    assert "Transformer: Self-attention model." in context
    assert "=== 检索到的知识图谱关系 (Related Relations) ===" in context
    assert "transformer --(uses)--> attention" in context
    assert "=== 精准检索文本分块 (Retrieved Text Chunks) ===" in context
    assert "Transformer is deep." in context

    debug_res = await pipeline.search("papers", "Transformer", top_k=5, debug=True)
    assert debug_res["debug"]["vector_chunk_ids"] == ["c2"]
    assert debug_res["debug"]["keyword_chunk_ids"] == ["c1"]
    assert debug_res["debug"]["graph_chunk_ids"] == ["c1"]
    assert set(debug_res["debug"]["rrf_scores"]) == {"c1", "c2"}
