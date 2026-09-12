"""单次请求内的检索/重排/embedding 缓存原语（pipelines 层，纯内存，请求作用域）。

Phase 2 契约：query embedding、检索、重排在本次请求内缓存并合并并发同键调用，正文只存
一次；检索缓存键必须含 query、scope、代次、排除集合、候选预算与模型配置——改变排除集合
不能命中旧结果；重排缓存只保存原始 (query, content_hash, model) 分数，候选池排名每次
重算，不缓存池内名次（避免排除集合变化后复用过期相对名次）。

由增强和深度模式的请求级 EvidenceSession 复用。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class SingleFlightCache(Generic[K, V]):
    """按键合并并发相同计算的请求作用域缓存。

    契约：命中直接返回缓存值；未命中且无并发在途时才真正调用 compute；并发同键调用
    共享同一次计算结果，不重复触发 I/O；compute 失败不缓存该键，下次调用会重新尝试
    （不会把失败结果当作有效缓存长期挡住重试）。非线程安全，仅供单个 event loop 内使用。
    """

    def __init__(self) -> None:
        self._values: dict[K, V] = {}
        self._inflight: dict[K, asyncio.Future[V]] = {}

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, key: K) -> bool:
        return key in self._values

    async def get_or_compute(self, key: K, compute: Callable[[], Awaitable[V]]) -> V:
        if key in self._values:
            return self._values[key]
        inflight = self._inflight.get(key)
        if inflight is not None:
            # 一个等待者取消不能取消共享 future，否则计算完成时 set_result 会失败。
            return await asyncio.shield(inflight)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[V] = loop.create_future()
        self._inflight[key] = future
        try:
            value = await compute()
        except BaseException as exc:
            future.set_exception(exc)
            # 立即标记已读：本调用方直接 raise，不经由 future 取异常；若没有并发等待者
            # 消费它，asyncio 会在垃圾回收时报 "exception was never retrieved"。
            future.exception()
            del self._inflight[key]
            raise
        self._values[key] = value
        future.set_result(value)
        del self._inflight[key]
        return value


@dataclass(frozen=True)
class RetrievalCacheKey:
    """检索缓存键：query、scope、代次、排除集合、候选预算与模型配置。

    excluded_chunk_ids 变化即视为不同键——发现性补查排除已命中 chunk 后必须发起新检索，
    绝不能因 query 相同就错误复用旧结果（见验收 R04）。
    """

    query: str
    scope: str
    generation_id: str
    excluded_chunk_ids: frozenset[str]
    candidate_budget: int
    model_config_digest: str


@dataclass(frozen=True)
class RerankCacheKey:
    """重排缓存键：只保存单条 (query, content_hash, model) 的原始分数。

    候选池整体排名不进本缓存——排名依赖当前候选集合，换了候选池必须重新归一化排序，
    只有「这条内容对这个 query 在这个模型下的原始分数」可以跨轮复用。
    """

    query: str
    content_hash: str
    model: str


@dataclass(frozen=True)
class EmbeddingCacheKey:
    """query embedding 缓存键：query 与模型配置摘要（换模型不得复用旧向量）。"""

    query: str
    model_config_digest: str


@dataclass
class EvidenceSessionCache:
    """单次请求内的检索/重排/embedding 缓存容器。

    契约：每个请求应实例化一份独立对象，不跨请求共享、不做成全局单例——避免不同问答的
    候选/分数互相污染。retrieval 缓存值类型由调用方决定（不同编排器的检索结果结构不同），
    故用 Any 而非耦合具体检索结果类型。
    """

    retrieval: SingleFlightCache[RetrievalCacheKey, Any] = field(
        default_factory=SingleFlightCache
    )
    rerank: SingleFlightCache[RerankCacheKey, float] = field(default_factory=SingleFlightCache)
    embedding: SingleFlightCache[EmbeddingCacheKey, list[float]] = field(
        default_factory=SingleFlightCache
    )


__all__ = [
    "SingleFlightCache",
    "RetrievalCacheKey",
    "RerankCacheKey",
    "EmbeddingCacheKey",
    "EvidenceSessionCache",
]
