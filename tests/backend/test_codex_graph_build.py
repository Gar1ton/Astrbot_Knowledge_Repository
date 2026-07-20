"""Codex-driven LightRAG build task protocol tests."""

from __future__ import annotations

from typing import Any

import pytest

from kacore.api import KnowledgeRepositoryApi
from kacore.domain.models import DocumentChunk, SourceDocument
from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
from kacore.repository.source_store.memory import InMemorySourceDocumentStore


class FakeLightRAGRegistry:
    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks or ["Alice founded Acme.", "Bob joined Acme."]
        self.inserted: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_once = False
        self.reset_calls: list[str] = []

    def has_workspace(self, collection: str) -> bool:
        del collection
        return False

    async def reset_workspace(self, collection: str) -> None:
        self.reset_calls.append(collection)

    async def chunk_document(self, collection: str, text: str) -> tuple[list[str], str]:
        assert collection == "papers"
        assert text
        return list(self.chunks), "lrag_chunks"

    async def insert_custom_kg(
        self, collection: str, doc_id: str, custom_kg: dict[str, Any]
    ) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("embedding unavailable")
        self.inserted.append((collection, doc_id, custom_kg))


async def _make_api(
    registry: FakeLightRAGRegistry,
) -> tuple[KnowledgeRepositoryApi, InMemorySourceDocumentStore]:
    store = InMemorySourceDocumentStore()
    await store.add_document(
        SourceDocument(
            doc_id="doc-1",
            title="Alpha Paper",
            file_path="/data/alpha.pdf",
            content_type="application/pdf",
            size_bytes=10,
            content_hash="hash",
            collection="papers",
        )
    )
    await store.replace_chunks(
        "doc-1",
        [
            DocumentChunk(
                chunk_id="source-1",
                doc_id="doc-1",
                ordinal=0,
                text="Alice founded Acme. Bob joined Acme.",
                content_hash="chunk-hash",
            )
        ],
    )
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=registry,  # type: ignore[arg-type]
    )
    return api, store


def _result() -> dict[str, Any]:
    return {
        "entities": [
            {
                "entity_name": "Alice",
                "entity_type": "PERSON",
                "description": "Founder of Acme",
                "source_id": "untrusted",
                "file_path": "/untrusted/path",
            },
            {
                "entity_name": "Acme",
                "entity_type": "ORGANIZATION",
                "description": "Company",
            },
        ],
        "relationships": [
            {
                "src_id": "Alice",
                "tgt_id": "Acme",
                "description": "Alice founded Acme",
                "keywords": ["founded", "company"],
                "weight": 2,
            }
        ],
    }


async def test_codex_build_requires_confirmation_and_creates_bounded_tasks() -> None:
    registry = FakeLightRAGRegistry()
    api, store = await _make_api(registry)

    with pytest.raises(ValueError, match="confirmed=true"):
        await api.build_graph_with_codex("papers")

    started = await api.build_graph_with_codex("papers", confirmed=True)
    tasks = await store.list_codex_graph_tasks(started["job_id"])
    next_task = await api.get_next_codex_graph_task(started["job_id"])

    assert started["engine"] == "lightrag_codex"
    assert started["status"] == "waiting_agent"
    assert started["plugin_llm_used"] is False
    assert started["total_chunks"] == 2
    assert len(tasks) == 2
    assert next_task["task"]["content"] == "Alice founded Acme."
    assert next_task["plugin_llm_used"] is False
    assert registry.inserted == []


async def test_submissions_use_trusted_provenance_and_complete_the_job() -> None:
    registry = FakeLightRAGRegistry()
    api, store = await _make_api(registry)
    started = await api.build_graph_with_codex("papers", confirmed=True)
    job_id = started["job_id"]

    first = await api.get_next_codex_graph_task(job_id)
    first_id = first["task"]["task_id"]
    accepted = await api.submit_codex_graph_task(job_id, first_id, _result())
    second = await api.get_next_codex_graph_task(job_id)
    second_id = second["task"]["task_id"]
    completed = await api.submit_codex_graph_task(
        job_id, second_id, {"entities": [], "relationships": []}
    )
    final = await api.get_next_codex_graph_task(job_id)

    assert accepted["job"]["status"] == "waiting_agent"
    assert completed["job"]["status"] == "success"
    assert final["task"] is None and final["complete"] is True
    assert len(registry.inserted) == 2
    first_kg = registry.inserted[0][2]
    assert first_kg["chunks"][0]["source_id"] == first_id
    assert first_kg["chunks"][0]["file_path"] == "/data/alpha.pdf"
    assert first_kg["entities"][0]["source_id"] == first_id
    assert first_kg["entities"][0]["file_path"] == "/data/alpha.pdf"
    assert first_kg["relationships"][0]["keywords"] == "founded, company"
    status = await store.get_lightrag_index_status("doc-1")
    assert status is not None and status["status"] == "indexed"


async def test_invalid_agent_payload_is_rejected_before_embedding_write() -> None:
    registry = FakeLightRAGRegistry(chunks=["Only one chunk."])
    api, _store = await _make_api(registry)
    started = await api.build_graph_with_codex("papers", confirmed=True)
    task = (await api.get_next_codex_graph_task(started["job_id"]))["task"]

    with pytest.raises(ValueError, match="description must not be empty"):
        await api.submit_codex_graph_task(
            started["job_id"],
            task["task_id"],
            {
                "entities": [],
                "relationships": [
                    {
                        "src_id": "Alice",
                        "tgt_id": "Acme",
                        "description": "",
                        "keywords": "founded",
                    }
                ],
            },
        )
    assert registry.inserted == []


async def test_failed_embedding_is_retryable_and_waiting_job_restores() -> None:
    registry = FakeLightRAGRegistry(chunks=["Only one chunk."])
    api, store = await _make_api(registry)
    started = await api.build_graph_with_codex("papers", confirmed=True)
    job_id = started["job_id"]
    task = (await api.get_next_codex_graph_task(job_id))["task"]

    registry.fail_once = True
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await api.submit_codex_graph_task(
            job_id, task["task_id"], {"entities": [], "relationships": []}
        )
    failed = await api.get_next_codex_graph_task(job_id)
    assert failed["task"]["previous_status"] == "error"

    restored = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=registry,  # type: ignore[arg-type]
    )
    await restored.restore_paused_build_job()
    restored_task = await restored.get_next_codex_graph_task(job_id)
    assert restored_task["job"]["engine"] == "lightrag_codex"
    assert restored_task["task"]["task_id"] == task["task_id"]

    retried = await restored.retry_codex_graph_task(job_id, task["task_id"])
    assert retried["status"] == "pending"
    completed = await restored.submit_codex_graph_task(
        job_id, task["task_id"], {"entities": [], "relationships": []}
    )
    assert completed["job"]["status"] == "success"
