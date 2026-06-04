"""VectorStore 契约测试（接口对换：内存向量检索库）。"""
import sys
from types import SimpleNamespace

import pytest

from core.domain.models import DocumentChunk
from core.repository.vector_store.memory import InMemoryVectorStore
from core.repository.vector_store.milvus_lite import MilvusLiteVectorStore


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    # 注册测试模拟数据：doc1/doc2 -> collection1; doc3 -> collection2
    store.set_doc_collection_mapping("doc1", "col1")
    store.set_doc_collection_mapping("doc2", "col1")
    store.set_doc_collection_mapping("doc3", "col2")
    return store


@pytest.mark.asyncio
async def test_upsert_and_search_basic(vector_store: InMemoryVectorStore) -> None:
    chunks = [
        DocumentChunk("c1", "doc1", 0, "text one", "h1"),
        DocumentChunk("c2", "doc2", 1, "text two", "h2"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    
    await vector_store.upsert_chunks(chunks, embeddings)
    
    # 检索 col1, 查询向量靠近 c1
    results = await vector_store.search("col1", [0.9, 0.1, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0][0] == "c1"
    assert results[0][1] > 0.8  # 高余弦相似度
    assert results[1][0] == "c2"


@pytest.mark.asyncio
async def test_search_respects_collection(vector_store: InMemoryVectorStore) -> None:
    chunks = [
        DocumentChunk("c1", "doc1", 0, "text one", "h1"),
        DocumentChunk("c3", "doc3", 0, "text three", "h3"),
    ]
    # c1 与 c3 的向量完全一样，但归属于不同 collection
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
    ]
    
    await vector_store.upsert_chunks(chunks, embeddings)
    
    # 检索 col1，只能检索到 c1
    res_col1 = await vector_store.search("col1", [1.0, 0.0, 0.0, 0.0], top_k=5)
    assert len(res_col1) == 1
    assert res_col1[0][0] == "c1"
    
    # 检索 col2，只能检索到 c3
    res_col2 = await vector_store.search("col2", [1.0, 0.0, 0.0, 0.0], top_k=5)
    assert len(res_col2) == 1
    assert res_col2[0][0] == "c3"


@pytest.mark.asyncio
async def test_delete_chunks(vector_store: InMemoryVectorStore) -> None:
    chunks = [
        DocumentChunk("c1", "doc1", 0, "text one", "h1"),
        DocumentChunk("c2", "doc2", 1, "text two", "h2"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    await vector_store.upsert_chunks(chunks, embeddings)
    
    # 删除 c1
    await vector_store.delete_chunks(["c1"])
    
    # 检索 col1，只剩下 c2
    results = await vector_store.search("col1", [1.0, 0.0, 0.0, 0.0], top_k=5)
    assert len(results) == 1
    assert results[0][0] == "c2"


@pytest.mark.asyncio
async def test_delete_collection(vector_store: InMemoryVectorStore) -> None:
    chunks = [
        DocumentChunk("c1", "doc1", 0, "text one", "h1"),
        DocumentChunk("c3", "doc3", 0, "text three", "h3"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    await vector_store.upsert_chunks(chunks, embeddings)
    
    # 删除 col1 集合所有向量
    await vector_store.delete_collection("col1")
    
    # 检索 col1 应为空
    res_col1 = await vector_store.search("col1", [1.0, 0.0, 0.0, 0.0], top_k=5)
    assert len(res_col1) == 0
    
    # col2 的 c3 应完好
    res_col2 = await vector_store.search("col2", [0.0, 1.0, 0.0, 0.0], top_k=5)
    assert len(res_col2) == 1
    assert res_col2[0][0] == "c3"


@pytest.mark.asyncio
async def test_metadata_filtering(vector_store: InMemoryVectorStore) -> None:
    chunks = [
        DocumentChunk("c1", "doc1", 0, "text one", "h1"),
        DocumentChunk("c2", "doc2", 1, "text two", "h2"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
    ]
    await vector_store.upsert_chunks(chunks, embeddings)
    
    # 带 metadata 过滤检索
    results = await vector_store.search(
        "col1", [1.0, 0.0, 0.0, 0.0], top_k=5, filter_metadata={"doc_id": "doc2"}
    )
    assert len(results) == 1
    assert results[0][0] == "c2"


def test_milvus_rejects_existing_schema_dimension_mismatch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        def __init__(self, path: str) -> None:
            self.path = path

        def has_collection(self, name: str) -> bool:
            return True

        def describe_collection(self, name: str) -> dict:
            return {"fields": [{"name": "vector", "params": {"dim": 3}}]}

    monkeypatch.setitem(
        sys.modules,
        "pymilvus",
        SimpleNamespace(DataType=SimpleNamespace(), MilvusClient=Client),
    )
    store = MilvusLiteVectorStore(str(tmp_path / "milvus.db"), dim=7)

    with pytest.raises(RuntimeError, match="dimension is 3"):
        store.validate_schema()


@pytest.mark.asyncio
async def test_milvus_clear_recreates_mismatched_schema(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"exists": True, "dim": 3, "drops": 0}

    class Schema:
        dim = 0

        def add_field(self, **kwargs) -> None:
            if kwargs.get("field_name") == "vector":
                self.dim = kwargs["dim"]

    class IndexParams:
        def add_index(self, **kwargs) -> None:
            pass

    class Client:
        def __init__(self, path: str) -> None:
            self.path = path

        def has_collection(self, name: str) -> bool:
            return state["exists"]

        def describe_collection(self, name: str) -> dict:
            return {"fields": [{"name": "vector", "params": {"dim": state["dim"]}}]}

        def drop_collection(self, name: str) -> None:
            state["exists"] = False
            state["drops"] += 1

        def close(self) -> None:
            pass

        def create_schema(self, **kwargs) -> Schema:
            return Schema()

        def prepare_index_params(self) -> IndexParams:
            return IndexParams()

        def create_collection(self, *, schema: Schema, **kwargs) -> None:
            state["exists"] = True
            state["dim"] = schema.dim

    monkeypatch.setitem(
        sys.modules,
        "pymilvus",
        SimpleNamespace(
            DataType=SimpleNamespace(VARCHAR="varchar", FLOAT_VECTOR="float_vector"),
            MilvusClient=Client,
        ),
    )
    store = MilvusLiteVectorStore(str(tmp_path / "milvus.db"), dim=7)

    with pytest.raises(RuntimeError, match="dimension is 3"):
        store.validate_schema()

    await store.clear()

    assert state == {"exists": True, "dim": 7, "drops": 1}
    store.validate_schema()


def test_milvus_validates_every_vector_dimension(tmp_path) -> None:
    store = MilvusLiteVectorStore(str(tmp_path / "milvus.db"), dim=7)

    with pytest.raises(ValueError, match="expected 7, got 3"):
        store._validate_vector([0.1, 0.2, 0.3])
