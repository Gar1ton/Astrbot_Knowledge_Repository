"""GraphBuildPipeline 单元测试。

验证图谱构建管线：增量对比跳过、过期数据级联清理、大模型不匹配类型对齐、外键完整性实体自动打桩等业务逻辑。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from core.adapters.llm import LLMAdapter
from core.config import GraphConfig
from core.domain.models import DocumentChunk, SourceDocument
from core.pipelines.graph_build_pipeline import GraphBuildPipeline
from core.repository.graph_store.sqlite import SQLiteGraphStore
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from migrations.runner import run_migrations


@pytest.fixture
async def db_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys = ON")
    await run_migrations(conn)

    # 播种集合
    await conn.execute(
        "INSERT INTO collections (name, created_at) VALUES ('papers', '2026-01-01T00:00:00Z')"
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
        entity_types=["Method", "Dataset", "Metric"],
    )


@pytest.mark.asyncio
async def test_graph_build_pipeline_first_run_and_incremental(
    db_conn: aiosqlite.Connection,
    source_store: SQLiteSourceDocumentStore,
    graph_store: SQLiteGraphStore,
    graph_config: GraphConfig,
) -> None:
    # 1) 插入两个测试文档与分块
    doc1 = SourceDocument("d1", "doc1", "/p1", "pdf", 100, "hash1", "papers", ["t1"])
    await source_store.add_document(doc1)
    await source_store.replace_chunks(
        "d1",
        [
            DocumentChunk("c1", "d1", 0, "Transformers are powerful.", "chash1"),
            DocumentChunk("c2", "d1", 1, "BLEU score evaluates metrics.", "chash2"),
        ],
    )

    # 2) 模拟 LLM 结构化输出
    mock_llm = MagicMock(spec=LLMAdapter)
    mock_llm.extract_graph = AsyncMock()
    mock_llm.extract_graph.side_effect = [
        # c1 提取结果
        {
            "entities": [
                {"name": "Transformers", "type": "Method", "description": "GNN style method."}
            ],
            "relations": []
        },
        # c2 提取结果
        {
            "entities": [
                {"name": "BLEU", "type": "Metric", "description": "N-gram matching metric."}
            ],
            "relations": []
        }
    ]

    pipeline = GraphBuildPipeline(
        source_store=source_store,
        graph_store=graph_store,
        llm_adapter=mock_llm,
        config=graph_config,
    )

    # 3) 执行首次构建
    res = await pipeline.build_graph("papers")
    assert res["status"] == "success"
    assert res["total_chunks"] == 2
    assert res["extracted_chunks"] == 2
    assert res["skipped_chunks"] == 0

    # 验证实体成功保存
    e1 = await graph_store.get_entity("transformers")
    e2 = await graph_store.get_entity("bleu")
    assert e1 is not None and e1.name == "Transformers"
    assert e2 is not None and e2.name == "BLEU"

    # 4) 二次执行（增量测试，内容哈希未变）
    mock_llm.extract_graph.reset_mock()
    res_inc = await pipeline.build_graph("papers")
    assert res_inc["skipped_chunks"] == 2
    assert res_inc["extracted_chunks"] == 0
    # 验证 LLM 未被重复调用
    mock_llm.extract_graph.assert_not_called()


@pytest.mark.asyncio
async def test_graph_build_pipeline_obsolete_pruning(
    db_conn: aiosqlite.Connection,
    source_store: SQLiteSourceDocumentStore,
    graph_store: SQLiteGraphStore,
    graph_config: GraphConfig,
) -> None:
    doc1 = SourceDocument("d1", "doc1", "/p1", "pdf", 100, "hash1", "papers")
    await source_store.add_document(doc1)
    await source_store.replace_chunks(
        "d1",
        [DocumentChunk("c1", "d1", 0, "Old Transformer text.", "hash_old")],
    )

    mock_llm = MagicMock(spec=LLMAdapter)
    mock_llm.extract_graph = AsyncMock()
    mock_llm.extract_graph.side_effect = [
        # 首次提取 (c1)
        {
            "entities": [{"name": "OldConcept", "type": "Method", "description": "old"}],
            "relations": []
        },
        # 修改后重新提取 (c1)
        {
            "entities": [{"name": "NewConcept", "type": "Method", "description": "new"}],
            "relations": []
        }
    ]

    pipeline = GraphBuildPipeline(
        source_store=source_store,
        graph_store=graph_store,
        llm_adapter=mock_llm,
        config=graph_config,
    )

    # 首次构建
    await pipeline.build_graph("papers")
    assert await graph_store.get_entity("oldconcept") is not None

    # 修改内容哈希，触发二次构建
    await source_store.replace_chunks(
        "d1",
        [DocumentChunk("c1", "d1", 0, "New BERT text.", "hash_new")],
    )
    res = await pipeline.build_graph("papers")
    assert res["deleted_stale_chunks"] == 1
    assert res["extracted_chunks"] == 1

    # 验证旧节点由于失去所有支撑 chunk 而被级联彻底清除，新节点被添加
    assert await graph_store.get_entity("oldconcept") is None
    assert await graph_store.get_entity("newconcept") is not None


@pytest.mark.asyncio
async def test_graph_build_pipeline_type_alignment_and_foreign_key_stubs(
    db_conn: aiosqlite.Connection,
    source_store: SQLiteSourceDocumentStore,
    graph_store: SQLiteGraphStore,
    graph_config: GraphConfig,
) -> None:
    doc1 = SourceDocument("d1", "doc1", "/p1", "pdf", 100, "hash1", "papers")
    await source_store.add_document(doc1)
    await source_store.replace_chunks(
        "d1",
        [DocumentChunk("c1", "d1", 0, "BERT belongs to Method.", "hash_v1")],
    )

    mock_llm = MagicMock(spec=LLMAdapter)
    mock_llm.extract_graph = AsyncMock(
        return_value={
            # 1) BERT 的类型是大模型编造的 "SuperNeuralNetwork" (非法类别)
            # 2) 提取了 BERT -> PyTorch 的关系，但 PyTorch 悬空（未出现在 entities 列表）
            "entities": [
                {"name": "BERT", "type": "SuperNeuralNetwork", "description": "BERT Model"}
            ],
            "relations": [
                {
                    "src": "BERT",
                    "dst": "PyTorch",
                    "relation": "built_on",
                    "description": "BERT is built on PyTorch framework",
                    "weight": 1.0,
                }
            ]
        }
    )

    pipeline = GraphBuildPipeline(
        source_store=source_store,
        graph_store=graph_store,
        llm_adapter=mock_llm,
        config=graph_config,
    )

    res = await pipeline.build_graph("papers")
    assert res["status"] == "success"

    # 1) 验证类型对齐：BERT 的类型强制对齐到默认类别 "Method"
    bert = await graph_store.get_entity("bert")
    assert bert is not None and bert.entity_type == "Method"

    # 2) 验证外键打桩保护：PyTorch 自动被动态创建为 Placeholder 实体桩以防止外键冲突！
    pytorch = await graph_store.get_entity("pytorch")
    assert pytorch is not None
    assert pytorch.entity_type == "Method"
    assert "Placeholder" in pytorch.description

    # 验证度数degree重新被正确计算
    assert bert.degree == 1
    assert pytorch.degree == 1
