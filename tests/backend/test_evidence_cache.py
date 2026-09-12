"""单次请求内检索/重排/embedding 缓存原语的测试（无 I/O）。

覆盖验收矩阵 R03/R04 相关场景：并发同键调用只触发一次真实计算、排除集合变化发起新检索
而不是错误复用旧结果、失败的计算不会长期挡住重试。
"""
from __future__ import annotations

import asyncio

import pytest

from kacore.pipelines.evidence_cache import (
    EmbeddingCacheKey,
    EvidenceSessionCache,
    RerankCacheKey,
    RetrievalCacheKey,
    SingleFlightCache,
)


async def test_cache_hit_does_not_recompute() -> None:
    cache: SingleFlightCache[str, int] = SingleFlightCache()
    call_count = 0

    async def compute() -> int:
        nonlocal call_count
        call_count += 1
        return 42

    first = await cache.get_or_compute("k", compute)
    second = await cache.get_or_compute("k", compute)

    assert first == second == 42
    assert call_count == 1


async def test_concurrent_same_key_calls_are_coalesced() -> None:
    """R03：多个子查询并发命中同段，文本只存/计算一次。"""
    cache: SingleFlightCache[str, int] = SingleFlightCache()
    call_count = 0

    async def compute() -> int:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)
        return 7

    results = await asyncio.gather(
        cache.get_or_compute("k", compute),
        cache.get_or_compute("k", compute),
        cache.get_or_compute("k", compute),
    )

    assert results == [7, 7, 7]
    assert call_count == 1


async def test_different_keys_compute_independently() -> None:
    cache: SingleFlightCache[str, int] = SingleFlightCache()
    calls: list[str] = []

    async def compute_for(key: str) -> int:
        calls.append(key)
        return len(key)

    await cache.get_or_compute("a", lambda: compute_for("a"))
    await cache.get_or_compute("bb", lambda: compute_for("bb"))

    assert calls == ["a", "bb"]
    assert len(cache) == 2


async def test_failed_compute_is_not_cached_and_can_retry() -> None:
    cache: SingleFlightCache[str, int] = SingleFlightCache()
    attempts = 0

    async def flaky() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient failure")
        return 99

    with pytest.raises(RuntimeError):
        await cache.get_or_compute("k", flaky)

    assert "k" not in cache
    result = await cache.get_or_compute("k", flaky)
    assert result == 99
    assert attempts == 2


async def test_concurrent_failure_propagates_to_all_waiters() -> None:
    cache: SingleFlightCache[str, int] = SingleFlightCache()

    async def always_fails() -> int:
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    results = await asyncio.gather(
        cache.get_or_compute("k", always_fails),
        cache.get_or_compute("k", always_fails),
        return_exceptions=True,
    )

    assert all(isinstance(r, RuntimeError) for r in results)


def test_retrieval_cache_key_changes_with_excluded_chunk_ids() -> None:
    """R04：新一轮相同 query + 新排除集合必须发起新检索，不能复用旧缓存键。"""
    base = RetrievalCacheKey(
        query="q",
        scope="doc:1",
        generation_id="gen-1",
        excluded_chunk_ids=frozenset(),
        candidate_budget=32,
        model_config_digest="m1",
    )
    with_exclusion = RetrievalCacheKey(
        query="q",
        scope="doc:1",
        generation_id="gen-1",
        excluded_chunk_ids=frozenset({"c1"}),
        candidate_budget=32,
        model_config_digest="m1",
    )

    assert base != with_exclusion
    assert hash(base) != hash(with_exclusion)


async def test_retrieval_cache_key_drives_actual_recomputation() -> None:
    session = EvidenceSessionCache()
    call_count = 0

    async def compute() -> list[str]:
        nonlocal call_count
        call_count += 1
        return [f"chunk-{call_count}"]

    key_no_exclusion = RetrievalCacheKey(
        query="q", scope="s", generation_id="g1", excluded_chunk_ids=frozenset(),
        candidate_budget=10, model_config_digest="m",
    )
    key_with_exclusion = RetrievalCacheKey(
        query="q", scope="s", generation_id="g1", excluded_chunk_ids=frozenset({"c1"}),
        candidate_budget=10, model_config_digest="m",
    )

    first = await session.retrieval.get_or_compute(key_no_exclusion, compute)
    second = await session.retrieval.get_or_compute(key_with_exclusion, compute)
    third = await session.retrieval.get_or_compute(key_no_exclusion, compute)  # 命中缓存

    assert first != second
    assert third == first
    assert call_count == 2


def test_rerank_cache_key_ignores_candidate_pool_composition() -> None:
    """重排缓存只按 (query, content_hash, model) 键入，不含候选池信息——池内排名不缓存。"""
    a = RerankCacheKey(query="q", content_hash="h1", model="bge")
    b = RerankCacheKey(query="q", content_hash="h1", model="bge")
    assert a == b
    assert hash(a) == hash(b)


def test_embedding_cache_key_distinguishes_model_config() -> None:
    a = EmbeddingCacheKey(query="q", model_config_digest="m1")
    b = EmbeddingCacheKey(query="q", model_config_digest="m2")
    assert a != b


async def test_evidence_session_cache_isolates_retrieval_rerank_embedding() -> None:
    session = EvidenceSessionCache()
    assert len(session.retrieval) == 0
    assert len(session.rerank) == 0
    assert len(session.embedding) == 0

    await session.rerank.get_or_compute(
        RerankCacheKey(query="q", content_hash="h", model="m"), lambda: _const(1.0)
    )
    assert len(session.rerank) == 1
    assert len(session.retrieval) == 0  # 互不干扰


async def _const(value: float) -> float:
    return value
