"""EmbeddingProvider 单元与契约测试。"""
import os
import shutil
import time

import pytest

from kacore.repository.embedding.base import EmbeddingProvider
from kacore.repository.embedding.cached import CachedEmbeddingProvider
from kacore.repository.embedding.external import ExternalEmbeddingProvider
from kacore.repository.embedding.local import LocalEmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """用于测试缓存装饰器的基准 Mock 实现。"""

    def __init__(self, dimension: int = 4) -> None:
        self._dimension = dimension
        self.call_count = 0

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [[float(i) / 10.0] * self._dimension for i in range(len(texts))]

    def get_dimension(self) -> int:
        return self._dimension


@pytest.fixture
def cache_db_dir() -> str:
    db_dir = "./tests/mock_data/embedding_test_cache"
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)
    os.makedirs(db_dir, exist_ok=True)
    yield db_dir
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)


@pytest.mark.asyncio
async def test_cached_embedding_flow(cache_db_dir: str) -> None:
    inner = MockEmbeddingProvider(dimension=4)
    db_path = f"{cache_db_dir}/cache.db"
    cached = CachedEmbeddingProvider(inner=inner, db_path=db_path)
    
    texts = ["apple", "banana", "cherry"]
    
    # 第一次查询：缓存未命中，内部 provider call_count 应加 1
    res1 = await cached.embed_documents(texts)
    assert len(res1) == 3
    assert inner.call_count == 1
    assert res1[0] == [0.0] * 4
    
    # 第二次查询：完全命中，call_count 不变，瞬间返回
    res2 = await cached.embed_documents(texts)
    assert len(res2) == 3
    assert inner.call_count == 1
    assert res2[1] == [0.1] * 4
    
    # 混合查询：部分命中，部分未命中 ("durian" 缺失)
    mixed_texts = ["apple", "durian", "banana"]
    res3 = await cached.embed_documents(mixed_texts)
    assert len(res3) == 3
    # 仅向 inner 请求未命中的 "durian"，call_count 应加 1
    assert inner.call_count == 2
    assert res3[0] == [0.0] * 4  # apple 的原缓存值
    assert res3[1] == [0.0] * 4  # 新计算的 durian 值 (第一项)


@pytest.mark.asyncio
async def test_cached_embedding_namespace_and_dimension_prevent_stale_reuse(
    cache_db_dir: str,
) -> None:
    db_path = f"{cache_db_dir}/cache.db"
    first_inner = MockEmbeddingProvider(dimension=4)
    first = CachedEmbeddingProvider(first_inner, db_path=db_path, namespace="model-a")
    await first.embed_documents(["same text"])

    other_model_inner = MockEmbeddingProvider(dimension=7)
    other_model = CachedEmbeddingProvider(
        other_model_inner,
        db_path=db_path,
        namespace="model-b",
    )
    other_model_result = await other_model.embed_documents(["same text"])

    changed_dimension_inner = MockEmbeddingProvider(dimension=8)
    changed_dimension = CachedEmbeddingProvider(
        changed_dimension_inner,
        db_path=db_path,
        namespace="model-a",
    )
    changed_dimension_result = await changed_dimension.embed_documents(["same text"])

    assert other_model_inner.call_count == 1
    assert len(other_model_result[0]) == 7
    assert changed_dimension_inner.call_count == 1
    assert len(changed_dimension_result[0]) == 8


def test_local_provider_lazy_dimension() -> None:
    # 不初始化模型时，应能通过映射字典获取默认维度，实现极速免加载零开销
    provider = LocalEmbeddingProvider(model_name="BAAI/bge-large-en-v1.5")
    assert provider.get_dimension() == 1024


def test_local_provider_dimensions_and_e5_retrieval_prefixes() -> None:
    assert LocalEmbeddingProvider(model_name="BAAI/bge-small-zh-v1.5").get_dimension() == 512

    provider = LocalEmbeddingProvider(model_name="intfloat/multilingual-e5-small")
    assert provider.get_dimension() == 384
    assert provider._prepare_query("where is the answer") == "query: where is the answer"
    assert provider._prepare_documents(["the answer"]) == ["passage: the answer"]


@pytest.mark.asyncio
async def test_external_provider_mock() -> None:
    # 验证 ExternalEmbeddingProvider 能正确解析配置
    provider = ExternalEmbeddingProvider(
        base_url="https://api.openai.com/v1",
        model_name="text-embedding-3-small"
    )
    assert provider.get_dimension() == 1536


def test_local_provider_idle_timeout_unloads_model() -> None:
    """空闲超时后 _model 应被置 None，并可在下次调用时重新加载。"""
    import unittest.mock as mock

    provider = LocalEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        idle_timeout=1,  # 1 秒，仅用于测试
    )

    fake_model = mock.MagicMock()
    fake_model.encode.return_value = [0.1] * 384

    provider._model = fake_model

    # 手动触发一次 encode + 计时器重置
    provider._embed_query_sync("hello")

    assert provider._model is not None
    assert provider._idle_timer is not None

    # 等待超时触发卸载
    time.sleep(1.5)

    assert provider._model is None


def test_local_provider_idle_timeout_zero_never_unloads() -> None:
    """idle_timeout=0 时不应创建计时器，模型永久驻留。"""
    import unittest.mock as mock

    provider = LocalEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        idle_timeout=0,
    )

    fake_model = mock.MagicMock()
    fake_model.encode.return_value = [0.1] * 384
    provider._model = fake_model

    provider._embed_query_sync("hello")

    assert provider._idle_timer is None
    assert provider._model is not None


# ── 加载超时闸（v1.0.9）──────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_provider_first_call_times_out_while_model_loads() -> None:
    """模型未加载时，首次调用受 load_timeout 约束，超时给中文可读错误。"""

    def _never_returns(_payload: object) -> list[float]:
        time.sleep(5)  # 模拟卡在 HuggingFace 下载
        return [0.1] * 384

    provider = LocalEmbeddingProvider(model_name="BAAI/bge-large-en-v1.5", load_timeout=0.2)
    provider._embed_query_sync = _never_returns  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as excinfo:
        await provider.embed_query("hello")

    assert "加载超时" in str(excinfo.value)
    assert "BAAI/bge-large-en-v1.5" in str(excinfo.value)


@pytest.mark.asyncio
async def test_local_provider_loaded_model_is_not_time_boxed() -> None:
    """模型已加载后不再加闸：慢 encode 不应被误判为加载卡死。"""
    import unittest.mock as mock

    provider = LocalEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        idle_timeout=0,
        load_timeout=0.05,
    )
    fake_model = mock.MagicMock()

    def _slow_encode(*_args: object, **_kwargs: object) -> list[float]:
        time.sleep(0.2)  # 比 load_timeout 长
        return [0.1] * 384

    fake_model.encode.side_effect = _slow_encode
    provider._model = fake_model

    assert len(await provider.embed_query("hello")) == 384


@pytest.mark.asyncio
async def test_local_provider_load_timeout_zero_disables_guard() -> None:
    """load_timeout<=0 保留旧的无限等待行为（给愿意等下载的用户）。"""
    import unittest.mock as mock

    provider = LocalEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        idle_timeout=0,
        load_timeout=0,
    )
    fake_model = mock.MagicMock()
    fake_model.encode.return_value = [[0.1] * 384]

    def _load_then_encode(texts: list[str]) -> list[list[float]]:
        time.sleep(0.15)
        provider._model = fake_model
        return [[0.1] * 384 for _ in texts]

    provider._embed_documents_sync = _load_then_encode  # type: ignore[method-assign]

    assert len(await provider.embed_documents(["hello"])) == 1


@pytest.mark.asyncio
async def test_local_provider_fails_fast_while_another_load_is_in_flight() -> None:
    """加载进行中时后续调用快速失败，不再往线程池堆积会卡死的线程。

    超时只让 await 放弃等待，底层线程仍卡在 _lock 上；不拦住并发调用会耗尽默认 executor，
    把「一个模型加载慢」放大成「所有 to_thread 操作都卡住」。
    """
    provider = LocalEmbeddingProvider(model_name="BAAI/bge-large-en-v1.5", load_timeout=5)
    provider._loading = True  # 模拟已有一次加载在跑

    def _should_not_run(_payload: object) -> list[float]:
        raise AssertionError("加载进行中不应再投递新线程")

    provider._embed_query_sync = _should_not_run  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as excinfo:
        await provider.embed_query("hello")
    assert "仍在后台加载" in str(excinfo.value)
