"""EmbeddingProvider 单元与契约测试。"""
import os
import shutil

import pytest

from core.repository.embedding.base import EmbeddingProvider
from core.repository.embedding.cached import CachedEmbeddingProvider
from core.repository.embedding.external import ExternalEmbeddingProvider
from core.repository.embedding.local import LocalEmbeddingProvider


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


def test_local_provider_lazy_dimension() -> None:
    # 不初始化模型时，应能通过映射字典获取默认维度，实现极速免加载零开销
    provider = LocalEmbeddingProvider(model_name="BAAI/bge-large-en-v1.5")
    assert provider.get_dimension() == 1024


@pytest.mark.asyncio
async def test_external_provider_mock() -> None:
    # 验证 ExternalEmbeddingProvider 能正确解析配置
    provider = ExternalEmbeddingProvider(
        api_key="mock_key",
        base_url="https://api.openai.com/v1",
        model_name="text-embedding-3-small"
    )
    assert provider.get_dimension() == 1536
