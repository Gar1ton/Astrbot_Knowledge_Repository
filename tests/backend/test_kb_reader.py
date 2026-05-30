"""KnowledgeBaseReader 契约测试（接口对换：内存只读 KB）。"""
from __future__ import annotations

import pytest

from core.domain.models import DocumentChunk
from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader


@pytest.fixture
def reader() -> InMemoryKnowledgeBaseReader:
    return InMemoryKnowledgeBaseReader(
        {
            "kb1": [
                DocumentChunk("c0", "d1", 0, "alpha beta alpha", "h0"),
                DocumentChunk("c1", "d1", 1, "beta gamma", "h1"),
                DocumentChunk("c2", "d2", 0, "delta", "h2"),
            ],
            "kb2": [DocumentChunk("c3", "d3", 0, "epsilon", "h3")],
        }
    )


async def test_list_collections_sorted(reader: InMemoryKnowledgeBaseReader) -> None:
    assert await reader.list_collections() == ["kb1", "kb2"]


async def test_list_chunks(reader: InMemoryKnowledgeBaseReader) -> None:
    assert len(await reader.list_chunks("kb1")) == 3
    assert await reader.list_chunks("missing") == []


async def test_search_ranks_by_hit_count(reader: InMemoryKnowledgeBaseReader) -> None:
    results = await reader.search("kb1", "alpha", top_k=5)
    assert [c.chunk_id for c in results] == ["c0"]  # 仅 c0 命中 alpha


async def test_search_respects_top_k(reader: InMemoryKnowledgeBaseReader) -> None:
    results = await reader.search("kb1", "beta", top_k=1)
    assert len(results) == 1
    assert results[0].chunk_id in {"c0", "c1"}


async def test_search_empty_cases(reader: InMemoryKnowledgeBaseReader) -> None:
    assert await reader.search("kb1", "nomatch", top_k=5) == []
    assert await reader.search("missing", "alpha", top_k=5) == []
    assert await reader.search("kb1", "alpha", top_k=0) == []
