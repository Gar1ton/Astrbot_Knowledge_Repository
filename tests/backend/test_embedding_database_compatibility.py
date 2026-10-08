"""在已建 SQLite 库上验证真实外部适配/组合根接线，向量库用禁止破坏操作的桩。"""
from __future__ import annotations

import json
import sqlite3

import aiosqlite
import pytest

from kacore.config import EmbeddingConfig
from kacore.domain.models import Collection, DocumentChunk, SourceDocument
from kacore.index_compatibility import IndexCompatibilityStore, embedding_fingerprint
from kacore.managers.artifact_provenance import PROCESSING_VERSION
from kacore.migration_runner import run_migrations
from kacore.plugin_initializer import PluginInitializer
from kacore.repository.source_store.sqlite import SQLiteSourceDocumentStore
from kacore.repository.vector_store.milvus_lite import MilvusSchemaMismatchError
from tests.backend.test_external_embedding_contract import http, response  # noqa: F401


@pytest.mark.parametrize("old_dimension", [2048, 1024])
async def test_existing_source_and_index_survive_external_provider_upgrade(
    http, tmp_path, monkeypatch, old_dimension,
):
    source_path = tmp_path / "knowledge_repository.db"
    chunk = DocumentChunk("legacy-c0", "doc", 0, "Old text", "hash", {
        "start_char": 0, "end_char": 8, "pages": [1], "chunk_kind": "body",
    })
    async with aiosqlite.connect(source_path) as db:
        await run_migrations(db)
        store = SQLiteSourceDocumentStore(db)
        await store.upsert_collection(Collection(name="default"))
        await store.add_document(SourceDocument(
            "doc", "Existing article", "/original.pdf", "application/pdf", 8, "hash", "default",
            local_meta={"processing_version": PROCESSING_VERSION},
        ))
        await store.replace_chunks("doc", [chunk])
    with sqlite3.connect(source_path) as db:
        schema_before = db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()

    embedding = EmbeddingConfig(provider="external", model="alias", base_url="https://api.test/v1")
    compat_path = tmp_path / "index_compatibility.json"
    compat = IndexCompatibilityStore(compat_path)
    old_fingerprint = embedding_fingerprint(embedding, old_dimension)
    compat.mark_milvus_compatible(old_fingerprint)
    compat.mark_lightrag_compatible("default", old_fingerprint)
    index_dir = tmp_path / "vector_store.db"
    index_dir.mkdir()
    marker = index_dir / "existing-data"
    marker.write_bytes(b"existing-index")
    constructed = []

    class ExistingMilvus:
        created_collection = False

        def __init__(self, *, db_path, dim):
            constructed.append(dim)
            self.dim = dim

        def validate_schema(self):
            if self.dim != old_dimension:
                raise MilvusSchemaMismatchError("Existing index dimension mismatch; rebuild required")

        def set_doc_collection_mapping(self, *_args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(
        "kacore.repository.vector_store.milvus_lite.MilvusLiteVectorStore", ExistingMilvus,
    )
    monkeypatch.setattr("kacore.plugin_initializer.milvus_runtime_status", lambda: {"ready": True})
    http[0].append(response([[0.1] * 2048]))
    raw = {
        "embedding": {"provider": "external", "model": "alias", "base_url": embedding.base_url},
        "vector_db": {"backend": "milvus", "auto_rebuild_enabled": False},
        "graph": {"enabled": False},
        "notion_sync": {"enabled": False}, "r2_sync": {"enabled": False},
    }
    initializer = PluginInitializer(object(), raw, tmp_path)
    try:
        await initializer.initialize()
        assert initializer.embedding_dimension == 2048 and constructed == [2048]
        assert initializer.config.get_embedding_config().base_url == embedding.base_url
        assert await initializer.source_store.list_chunks("doc") == [chunk]
        doc = await initializer.source_store.get_document("doc")
        assert doc.content_hash == "hash" and doc.file_path == "/original.pdf"
        assert doc.local_meta == {"processing_version": PROCESSING_VERSION}
        assert doc.needs_reindex is (old_dimension != 2048)
        assert initializer.index_compatibility.is_milvus_compatible(
            initializer.embedding_fingerprint,
        ) is (old_dimension == 2048)
        assert marker.read_bytes() == b"existing-index"
        state = json.loads(compat_path.read_text())
        assert state["lightrag"]["collections"]["default"] == old_fingerprint
    finally:
        await initializer.teardown()
    with sqlite3.connect(source_path) as db:
        assert db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == schema_before

