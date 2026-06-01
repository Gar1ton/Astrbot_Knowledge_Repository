import os
import shutil
import tempfile

import aiosqlite
import pytest

from core.config import Config
from core.domain.models import DocumentChunk, SourceDocument
from core.pipelines.retrieval_orchestrator import RetrievalOrchestrator
from core.repository.kb_reader.base import KnowledgeBaseReader
from core.repository.source_store.sqlite import SQLiteSourceDocumentStore
from core.repository.vector_store.milvus_lite import MilvusLiteVectorStore


class MockKnowledgeBaseReader(KnowledgeBaseReader):
    def __init__(self, chunks=None):
        self.chunks = chunks or []

    async def list_collections(self) -> list[str]:
        return ["col1"]

    async def list_chunks(self, collection: str) -> list[DocumentChunk]:
        return self.chunks

    async def search(self, collection: str, query: str, top_k: int) -> list[DocumentChunk]:
        return self.chunks[:top_k]


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def sqlite_store(temp_dir):
    db_path = os.path.join(temp_dir, "test_source.db")
    db = await aiosqlite.connect(db_path)
    await db.execute("PRAGMA foreign_keys = ON")
    
    # Run the SQL migrations / tables setup manually or just basic schema
    await db.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        title TEXT,
        file_path TEXT,
        content_type TEXT,
        size_bytes INTEGER,
        content_hash TEXT,
        collection TEXT,
        tags TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        doc_id TEXT REFERENCES documents(doc_id) ON DELETE CASCADE,
        ordinal INTEGER,
        text TEXT,
        content_hash TEXT
    )
    """)
    
    store = SQLiteSourceDocumentStore(db)
    yield store
    await db.close()


@pytest.mark.asyncio
async def test_milvus_lite_vector_store_lifecycle(temp_dir):
    db_path = os.path.join(temp_dir, "milvus_lite_test.db")
    store = MilvusLiteVectorStore(db_path=db_path, dim=4)
    
    # 1. Register document mapping
    store.set_doc_collection_mapping("doc_1", "col_1")
    store.set_doc_collection_mapping("doc_2", "col_1")
    
    chunks = [
        DocumentChunk("c1", "doc_1", 0, "attention neural network", "h1"),
        DocumentChunk("c2", "doc_2", 0, "milvus vector database", "h2"),
    ]
    embeddings = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    
    # 2. Upsert
    await store.upsert_chunks(chunks, embeddings)
    
    # 3. Search
    results = await store.search("col_1", [0.9, 0.1, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0][0] == "c1"
    
    # 4. Search with metadata filtering
    results_filtered = await store.search(
        "col_1", [0.9, 0.1, 0.0, 0.0], top_k=2, filter_metadata={"doc_id": "doc_2"}
    )
    assert len(results_filtered) == 1
    assert results_filtered[0][0] == "c2"
    
    # 5. Delete chunks
    await store.delete_chunks(["c1"])
    results_after_delete = await store.search("col_1", [1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(results_after_delete) == 1
    assert results_after_delete[0][0] == "c2"
    
    # 6. Delete collection
    await store.delete_collection("col_1")
    results_col_deleted = await store.search("col_1", [0.0, 1.0, 0.0, 0.0], top_k=2)
    assert len(results_col_deleted) == 0
    
    # 7. Close
    await store.close()


@pytest.mark.asyncio
async def test_retrieval_orchestrator_lexical_fallback(sqlite_store):
    # Setup document and chunks in SQLite source store
    doc = SourceDocument(
        doc_id="doc1",
        title="Attention Paper",
        file_path="attention.pdf",
        content_type="application/pdf",
        size_bytes=1000,
        content_hash="hash1",
        collection="papers",
    )
    await sqlite_store.add_document(doc)
    
    chunks = [
        DocumentChunk(
            "c1", "doc1", 0, "transformer model relies entirely on attention mechanisms", "hc1"
        ),
        DocumentChunk("c2", "doc1", 1, "dense vectors are used for semantic search", "hc2"),
    ]
    await sqlite_store.replace_chunks("doc1", chunks)
    
    config = Config(raw={})
    kb_reader = MockKnowledgeBaseReader()
    
    orchestrator = RetrievalOrchestrator(
        source_store=sqlite_store,
        kb_reader=kb_reader,
        config=config,
    )
    
    # Test Lexical road search via RetrievalOrchestrator
    results = await orchestrator.retrieve("papers", "attention mechanisms", top_k=2)
    assert len(results) >= 1
    assert results[0].chunk_id == "c1"
    assert "attention" in results[0].text
