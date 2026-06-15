"""Reranker 子系统与 adaptive_cutoff 的接口对换测试。

只覆盖可离线验证的契约：Noop 顺序/截断、cutoff 拐点与边界、工厂的缺依赖回退。
真实 cross-encoder 推理需下载模型，不在单测覆盖（薄封装，由集成环境验证）。
"""
from __future__ import annotations

import pytest

from core.domain.models import DocumentChunk
from core.repository.reranker import (
    PROVIDER_CROSS_ENCODER,
    PROVIDER_NOOP,
    NoopReranker,
    build_reranker,
)
from core.repository.reranker.base import ScoredChunk
from core.utils.cutoff import adaptive_cutoff


def _chunk(cid: str, text: str = "x") -> DocumentChunk:
    return DocumentChunk(cid, "doc1", 0, text, f"h-{cid}")


# ── NoopReranker ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_noop_preserves_order_and_scores_descending():
    chunks = [_chunk("c1"), _chunk("c2"), _chunk("c3")]
    out = await NoopReranker().rerank("q", chunks)
    assert [s.chunk.chunk_id for s in out] == ["c1", "c2", "c3"]
    assert out[0].score > out[1].score > out[2].score


@pytest.mark.asyncio
async def test_noop_top_n_truncates():
    chunks = [_chunk(f"c{i}") for i in range(5)]
    out = await NoopReranker().rerank("q", chunks, top_n=2)
    assert [s.chunk.chunk_id for s in out] == ["c0", "c1"]


@pytest.mark.asyncio
async def test_noop_empty():
    assert await NoopReranker().rerank("q", []) == []


def test_noop_status_reports_off():
    status = NoopReranker().status
    assert status["provider"] == "noop"
    assert status["status"] == "off"
    assert status["enabled"] is False


# ── adaptive_cutoff ─────────────────────────────────────────
def _scored(scores: list[float]) -> list[ScoredChunk]:
    return [ScoredChunk(chunk=_chunk(f"c{i}"), score=s) for i, s in enumerate(scores)]


def test_cutoff_empty():
    assert adaptive_cutoff([], keep_max=8) == []


def test_cutoff_respects_keep_max():
    scored = _scored([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    out = adaptive_cutoff(scored, keep_max=3, min_keep=3)
    assert len(out) <= 3


def test_cutoff_cuts_at_largest_gap():
    # 明显拐点在 index 3（0.9,0.85,0.8 | 0.2,0.1）。
    scored = _scored([0.9, 0.85, 0.8, 0.2, 0.1])
    out = adaptive_cutoff(scored, keep_max=5, min_keep=1)
    assert [s.score for s in out] == [0.9, 0.85, 0.8]


def test_cutoff_min_keep_floors_below_largest_gap():
    # 最大落差在 index 1，但 min_keep=2 强制至少保留 2 个。
    scored = _scored([0.9, 0.1, 0.05])
    out = adaptive_cutoff(scored, keep_max=5, min_keep=2)
    assert len(out) >= 2


# ── build_reranker 工厂 ─────────────────────────────────────
def test_build_default_is_noop():
    """默认 provider=noop——不重排，零模型零部署，不触发任何下载。"""
    assert isinstance(build_reranker(), NoopReranker)


def test_build_noop_returns_noop():
    assert isinstance(build_reranker(provider=PROVIDER_NOOP), NoopReranker)


def test_build_cross_encoder_falls_back_when_dep_missing(monkeypatch):
    """显式 cross_encoder 但 sentence-transformers 缺失时回退 Noop。"""
    monkeypatch.setattr("core.repository.reranker._has_sentence_transformers", lambda: False)
    assert isinstance(build_reranker(provider=PROVIDER_CROSS_ENCODER), NoopReranker)


def test_build_cross_encoder_lazy_when_dep_present(monkeypatch):
    """显式 cross_encoder + 有依赖 → 懒加载 CrossEncoderReranker（构造不加载模型）。"""
    monkeypatch.setattr("core.repository.reranker._has_sentence_transformers", lambda: True)
    from core.repository.reranker.bge_local import CrossEncoderReranker

    reranker = build_reranker(provider=PROVIDER_CROSS_ENCODER)
    assert isinstance(reranker, CrossEncoderReranker)
    assert reranker._model is None  # 懒加载：构造时尚未加载模型。
    assert reranker.status["status"] == "idle"
    assert reranker.status["model"] == "Alibaba-NLP/gte-reranker-modernbert-base"


@pytest.mark.asyncio
async def test_cross_encoder_failure_sets_failed_status(monkeypatch):
    from core.repository.reranker.bge_local import CrossEncoderReranker

    reranker = CrossEncoderReranker(model="missing-model")
    monkeypatch.setattr(
        reranker,
        "_ensure_model",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    out = await reranker.rerank("q", [_chunk("c1")])

    assert [item.chunk.chunk_id for item in out] == ["c1"]
    assert reranker.status["status"] == "failed"
    assert reranker.status["last_error"] == "boom"
    assert reranker.is_passthrough is True
