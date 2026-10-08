"""OpenAI 文本协议、冷启动缓存及旧库身份的回归测试，无真实网络或模型依赖。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.repository.embedding import external
from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.cached import CachedEmbeddingProvider
from kacore.repository.embedding.external import ExternalEmbeddingProvider


def response(vectors, indices=None):
    indices = list(range(len(vectors))) if indices is None else indices
    return {"data": [{"index": index, "embedding": vector}
                     for index, vector in zip(indices, vectors)]}


@pytest.fixture
def http(monkeypatch):
    """模拟 aiohttp 公共调用边界，记录实际 URL/请求并按顺序提供响应。"""
    queue = []
    calls = []

    class Response:
        def __init__(self, body, status=200):
            self.body, self.status = body, status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def json(self):
            if isinstance(self.body, Exception):
                raise self.body
            return self.body

    class Session:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, tuple):
                return Response(*item)
            return Response(item)

    monkeypatch.setattr(external.aiohttp, "ClientSession", Session)
    monkeypatch.setattr(external, "_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setenv("KR_EMBEDDING_API_KEY", "test-secret-do-not-log")
    return queue, calls


@pytest.mark.parametrize("base, endpoint", [
    ("https://example.org/v1", "https://example.org/v1/embeddings"),
    ("https://example.org/api/v1/", "https://example.org/api/v1/embeddings"),
    ("https://example.org/v1/embeddings", "https://example.org/v1/embeddings"),
    ("https://example.org/v1/embeddings/", "https://example.org/v1/embeddings"),
    ("http://localhost:8899", "http://localhost:8899/embeddings"),
    ("https://example.org/proxy?route=x", "https://example.org/proxy/embeddings?route=x"),
])
async def test_endpoint_and_text_contract(http, base, endpoint):
    queue, calls = http
    queue.append(response([[1, 2], [3, 4]], [1, 0]))
    provider = ExternalEmbeddingProvider(base, "multimodal-alias")
    assert await provider.embed_documents(["first", "second"]) == [[3, 4], [1, 2]]
    assert provider.get_dimension() == 2 and provider.dimension_verified
    assert calls[0][0] == endpoint
    assert calls[0][1]["json"] == {
        "model": "multimodal-alias", "input": ["first", "second"], "encoding_format": "float",
    }
    assert "dimensions" not in calls[0][1]["json"]
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-secret-do-not-log"


async def test_existing_openai_dimension_request_is_preserved(http):
    queue, calls = http
    queue.append(response([[0.1] * 1536]))
    provider = ExternalEmbeddingProvider(model_name="text-embedding-3-small")
    assert len(await provider.embed_query("query")) == 1536
    assert calls[0][1]["json"]["dimensions"] == 1536


@pytest.mark.parametrize("bad", [
    None, [], {}, {"data": {}}, response([]),
    response([[1], [2]], [0, 0]), response([[1], [2]], [-1, 1]),
    response([[1], [2]], [False, 1]), response([[1], [2]], [0.0, 1]),
    response([[1], [2]], [0, 2]), {"data": [{"embedding": [1]}, {"index": 1}]},
    response([[], [1]]), response([None, [1]]), response(["encoded", [1]]),
    response([[True], [1]]), response([["secret-response"], [1]]),
    response([[float("nan")], [1]]), response([[float("inf")], [1]]),
    response([[1], [1, 2]]), ValueError("secret-response"),
])
async def test_bad_batch_does_not_lock_dimension_or_retry(http, bad, caplog):
    queue, calls = http
    queue.append(bad)
    provider = ExternalEmbeddingProvider(model_name="unknown")
    with pytest.raises(RuntimeError) as caught:
        await provider.embed_documents(["secret-input", "other"])
    assert len(calls) == 1 and not provider.dimension_verified
    assert provider.get_dimension() == 1536
    for secret in ("secret-response", "secret-input", "test-secret-do-not-log"):
        assert secret not in str(caught.value) + caplog.text
    assert caught.value.__suppress_context__


async def test_dimension_drift_is_rejected_and_previous_dimension_retained(http):
    queue, calls = http
    queue.extend([response([[1, 2]]), response([[1, 2, 3]]), response([[3, 4]])])
    provider = ExternalEmbeddingProvider(model_name="alias")
    await provider.embed_query("first")
    with pytest.raises(RuntimeError, match="维度漂移"):
        await provider.embed_query("second")
    assert provider.get_dimension() == 2
    assert await provider.embed_query("third") == [3, 4]
    assert len(calls) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_client_errors_do_not_retry(http, status):
    queue, calls = http
    queue.append(({"error": "secret-response"}, status))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        await ExternalEmbeddingProvider().embed_query("query")
    assert len(calls) == 1


async def test_transient_failure_has_a_bounded_retry_and_redacted_exception(http, caplog):
    queue, calls = http
    queue.extend([OSError("https://user:secret@example.org"), OSError("secret-body")])
    with pytest.raises(RuntimeError) as caught:
        await ExternalEmbeddingProvider().embed_query("query")
    assert len(calls) == 2
    assert "secret" not in str(caught.value) + caplog.text
    assert caught.value.__suppress_context__
    queue.extend([({"error": "secret"}, 503), response([[1, 2]])])
    assert await ExternalEmbeddingProvider().embed_query("query") == [1, 2]


async def test_exhausted_server_error_preserves_safe_http_status(http):
    queue, calls = http
    queue.extend([({"error": "secret-response"}, 503)] * 2)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await ExternalEmbeddingProvider().embed_query("query")
    assert len(calls) == 2


async def test_empty_batch_has_no_network_or_cache_side_effect(http, tmp_path):
    provider = ExternalEmbeddingProvider()
    cached = CachedEmbeddingProvider(provider, str(tmp_path / "cache.db"))
    assert await cached.embed_documents([]) == []
    assert http[1] == [] and not (tmp_path / "cache.db").exists()


def seed_cache(path: Path, namespace: str, values: dict):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE embedding_cache (content_hash TEXT PRIMARY KEY, vector TEXT NOT NULL)")
        for text, encoded in values.items():
            key = hashlib.sha256(f"{namespace}\0{text}".encode()).hexdigest()
            db.execute("INSERT INTO embedding_cache VALUES (?, ?)", (key, encoded))


async def test_unknown_2048_dimension_reuses_legacy_cache_and_mixes_misses(http, tmp_path):
    queue, calls = http
    vector = [0.125] * 2048
    namespace = "external:arc:embedvl:http://localhost:8899/v1"
    path = tmp_path / "cache.db"
    seed_cache(path, namespace, {"old": json.dumps(vector)})
    queue.extend([response([vector]), response([[0.25] * 2048])])
    provider = ExternalEmbeddingProvider("http://localhost:8899/v1", "arc:embedvl")
    cached = CachedEmbeddingProvider(provider, str(path), namespace)
    result = await cached.embed_documents(["old", "new", "old"])
    assert result == [vector, [0.25] * 2048, vector]
    assert [call[1]["json"]["input"] for call in calls] == [["old"], ["new"]]
    assert await cached.embed_documents(["new", "old"]) == [result[1], vector]
    assert len(calls) == 2 and cached.identity == {}
    with sqlite3.connect(path) as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(embedding_cache)")] == [
            "content_hash", "vector",
        ]
        assert db.execute("SELECT count(*) FROM embedding_cache").fetchone()[0] == 2


@pytest.mark.parametrize("encoded", [
    "invalid-json", "null", '"string"', "[]", "[true, 1]", "[NaN, 1]", "[Infinity, 1]", "[1]",
])
async def test_corrupt_cache_is_a_miss(http, tmp_path, encoded):
    queue, calls = http
    path = tmp_path / "cache.db"
    seed_cache(path, "legacy", {"old": encoded})
    queue.extend([response([[1, 2]]), response([[3, 4]])])
    cached = CachedEmbeddingProvider(ExternalEmbeddingProvider(), str(path), "legacy")
    assert await cached.embed_documents(["old"]) == [[3, 4]]
    assert len(calls) == 2


async def test_bad_calculated_batch_is_not_partially_persisted(http, tmp_path):
    queue, _ = http
    path = tmp_path / "cache.db"
    queue.extend([response([[1, 2]]), response([[3, 4], [float("nan"), 0]])])
    cached = CachedEmbeddingProvider(ExternalEmbeddingProvider(), str(path))
    with pytest.raises(RuntimeError):
        await cached.embed_documents(["first", "second"])
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM embedding_cache").fetchone()[0] == 0


async def test_concurrent_cold_cache_has_one_probe_and_one_fill(http, tmp_path):
    queue, calls = http
    queue.extend([response([[1, 2]]), response([[3, 4]])])
    cached = CachedEmbeddingProvider(ExternalEmbeddingProvider(), str(tmp_path / "cache.db"))
    first, second = await asyncio.gather(
        cached.embed_documents(["same"]), cached.embed_documents(["same"]),
    )
    assert first == second == [[3, 4]] and len(calls) == 2


class ChangingDimensionProvider(EmbeddingProvider):
    def __init__(self):
        self.dim = 2
        self.batches = []

    def get_dimension(self):
        return self.dim

    async def embed_query(self, text):
        return [1] * self.dim

    async def embed_documents(self, texts):
        self.batches.append(texts)
        self.dim = 3
        return [[1, 2, 3] for _ in texts]


async def test_changed_lazy_dimension_does_not_merge_old_hits(tmp_path):
    path = tmp_path / "cache.db"
    seed_cache(path, "legacy", {"old": "[8, 9]"})
    provider = ChangingDimensionProvider()
    cached = CachedEmbeddingProvider(provider, str(path), "legacy")
    assert await cached.embed_documents(["old", "new"]) == [[1, 2, 3], [1, 2, 3]]
    assert provider.batches == [["new"], ["old", "new"]]


@pytest.mark.parametrize("bad", [[[1, 2]], [[1, 2], [True, 0]], [[1, 2], [1, 2, 3]]])
async def test_cache_validates_custom_provider_before_any_write(tmp_path, bad):
    class BadProvider(ChangingDimensionProvider):
        async def embed_documents(self, texts):
            return bad

    path = tmp_path / "cache.db"
    cached = CachedEmbeddingProvider(BadProvider(), str(path))
    with pytest.raises(ValueError):
        await cached.embed_documents(["first", "second"])
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM embedding_cache").fetchone()[0] == 0


async def test_connection_probe_uses_production_validation(http):
    queue, calls = http
    api = object.__new__(KnowledgeRepositoryApi)
    queue.extend([response([[1, 2]]), response([[float("nan")]])])
    assert await api.test_embedding_connection("https://example.org/v1/embeddings", "alias") == {
        "status": "ok", "dimension": 2, "model": "alias",
    }
    assert calls[0][0] == "https://example.org/v1/embeddings"
    bad = await api.test_embedding_connection("https://example.org/v1", "alias")
    assert bad["status"] == "error"
    assert (await api.test_embedding_connection("not-a-url", "alias"))["status"] == "error"
    assert (await api.test_embedding_connection("https://example.org", ""))["status"] == "error"
