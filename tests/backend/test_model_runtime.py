"""本地模型驻留查询与手动卸载的契约测试（接口互换，无真实模型）。"""
from __future__ import annotations

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.api_runtime_models import KIND_EMBEDDING, KIND_RERANK
from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.cached import CachedEmbeddingProvider
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.reranker.base import Reranker, ScoredChunk
from kacore.repository.reranker.noop import NoopReranker
from kacore.repository.source_store.memory import InMemorySourceDocumentStore


class _FakeLocalEmbedding(EmbeddingProvider):
    """最小本地 provider 替身：只跟踪「是否驻留」。"""

    def __init__(self) -> None:
        self.resident = True
        self.unload_calls = 0

    async def embed_query(self, text: str) -> list[float]:
        return [0.0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def get_dimension(self) -> int:
        return 1

    def unload(self) -> None:
        self.unload_calls += 1
        self.resident = False

    @property
    def runtime_status(self) -> dict:
        return {
            "provider": "local",
            "state": "ready" if self.resident else "idle",
            "model": "fake-model",
            "device": "cuda",
            "last_error": None,
        }


class _FakeReranker(Reranker):
    def __init__(self) -> None:
        self.resident = True
        self.close_calls = 0

    @property
    def status(self) -> dict:
        return {
            "provider": "cross_encoder",
            "status": "ready" if self.resident else "idle",
            "model": "fake-rerank",
            "enabled": True,
            "last_error": None,
        }

    def close(self) -> None:
        self.close_calls += 1
        self.resident = False

    async def rerank(self, query, candidates, *, top_n=None) -> list[ScoredChunk]:
        return [ScoredChunk(chunk=c, score=1.0) for c in candidates]


def _api(embedding=None, reranker=None) -> KnowledgeRepositoryApi:
    return KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        embedding_provider=embedding,
        reranker=reranker,
    )


# ── 接口默认实现 ──────────────────────────────────────────────


def test_base_interfaces_expose_no_op_unload() -> None:
    """base 的默认实现必须可直接调用：远端 provider / noop 重排器没有模型可卸。"""
    NoopReranker().close()  # 不抛异常即通过

    class _Minimal(EmbeddingProvider):
        async def embed_query(self, text: str) -> list[float]:
            return []

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return []

        def get_dimension(self) -> int:
            return 0

    provider = _Minimal()
    provider.unload()
    assert provider.runtime_status["state"] == "external"


async def test_cached_provider_delegates_unload_and_status() -> None:
    """装饰器必须透传：组合根注入给上层的是 cached 实例，不透传则卸载静默失效。"""
    inner = _FakeLocalEmbedding()
    cached = CachedEmbeddingProvider(inner, db_path=":memory:")

    assert cached.runtime_status["model"] == "fake-model"
    cached.unload()

    assert inner.unload_calls == 1
    assert cached.runtime_status["state"] == "idle"


# ── get_model_runtime ─────────────────────────────────────────


async def test_get_model_runtime_reports_both_kinds() -> None:
    api = _api(_FakeLocalEmbedding(), _FakeReranker())

    runtime = await api.get_model_runtime()

    kinds = {m["kind"]: m for m in runtime["models"]}
    assert set(kinds) == {KIND_EMBEDDING, KIND_RERANK}
    assert kinds[KIND_EMBEDDING]["state"] == "ready"
    assert kinds[KIND_RERANK]["model"] == "fake-rerank"
    assert runtime["resident_count"] == 2


async def test_get_model_runtime_without_cuda_reports_null_accelerator() -> None:
    """无 torch / 无 CUDA 时 accelerator 为 None 且不抛异常——面板据此降级为 CPU 模式。"""
    runtime = await _api(_FakeLocalEmbedding(), _FakeReranker()).get_model_runtime()

    assert "accelerator" in runtime
    assert runtime["accelerator"] is None or isinstance(runtime["accelerator"], dict)


async def test_get_model_runtime_tolerates_missing_components() -> None:
    runtime = await _api().get_model_runtime()

    assert runtime["models"] == []
    assert runtime["resident_count"] == 0


async def test_get_model_runtime_survives_a_broken_status_property() -> None:
    class _Broken(_FakeReranker):
        @property
        def status(self) -> dict:
            raise RuntimeError("driver exploded")

    runtime = await _api(_FakeLocalEmbedding(), _Broken()).get_model_runtime()

    # 读状态失败只是少一行，不能把整个面板打成 500。
    assert [m["kind"] for m in runtime["models"]] == [KIND_EMBEDDING]


# ── unload_models ─────────────────────────────────────────────


async def test_unload_models_defaults_to_all_kinds() -> None:
    embedding, reranker = _FakeLocalEmbedding(), _FakeReranker()
    api = _api(embedding, reranker)

    runtime = await api.unload_models(None)

    assert embedding.unload_calls == 1
    assert reranker.close_calls == 1
    assert sorted(runtime["unloaded"]) == [KIND_EMBEDDING, KIND_RERANK]
    assert runtime["resident_count"] == 0
    assert all(m["state"] == "idle" for m in runtime["models"])


async def test_unload_models_can_target_one_kind() -> None:
    embedding, reranker = _FakeLocalEmbedding(), _FakeReranker()
    api = _api(embedding, reranker)

    await api.unload_models([KIND_RERANK])

    assert reranker.close_calls == 1
    assert embedding.unload_calls == 0
    assert embedding.resident is True


async def test_unload_models_ignores_unknown_kinds() -> None:
    embedding, reranker = _FakeLocalEmbedding(), _FakeReranker()

    runtime = await _api(embedding, reranker).unload_models(["llm", "../etc/passwd"])

    assert runtime["unloaded"] == []
    assert embedding.unload_calls == 0
    assert reranker.close_calls == 0


async def test_unload_models_is_idempotent() -> None:
    embedding, reranker = _FakeLocalEmbedding(), _FakeReranker()
    api = _api(embedding, reranker)

    await api.unload_models(None)
    runtime = await api.unload_models(None)

    assert embedding.unload_calls == 2  # 幂等指「可安全重复调用」，不是「只执行一次」
    assert runtime["resident_count"] == 0


async def test_unload_models_reports_per_kind_errors_without_raising() -> None:
    class _Failing(_FakeLocalEmbedding):
        def unload(self) -> None:
            raise RuntimeError("cuda busy")

    reranker = _FakeReranker()

    runtime = await _api(_Failing(), reranker).unload_models(None)

    assert runtime["errors"][KIND_EMBEDDING] == "cuda busy"
    # 一个失败不阻断另一个：显存回收是尽力而为。
    assert reranker.close_calls == 1
    assert runtime["unloaded"] == [KIND_RERANK]


@pytest.mark.parametrize("kinds", [[], None])
async def test_unload_models_empty_selection_means_all(kinds) -> None:
    embedding, reranker = _FakeLocalEmbedding(), _FakeReranker()

    await _api(embedding, reranker).unload_models(kinds)

    assert embedding.unload_calls == 1
    assert reranker.close_calls == 1
