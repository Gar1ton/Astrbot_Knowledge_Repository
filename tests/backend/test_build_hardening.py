"""Tests for LightRAG build hardening: concurrent guard and CancelledError handling."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.lightrag_core import BuildJob


# ─── Concurrent build guard ────────────────────────────────────


class _FakeSourceStore:
    async def list_documents_for_collection(self, col: str):
        return []

    async def upsert_build_job(self, snapshot: dict):
        pass

    async def mark_interrupted_build_jobs(self) -> int:
        return 0


def _make_api():
    """Build a minimal KnowledgeRepositoryApi instance for testing build_graph()."""
    from core.api import KnowledgeRepositoryApi
    from core.domain.models import SourceDocument

    source_store = _FakeSourceStore()
    api = object.__new__(KnowledgeRepositoryApi)
    api._graph_build_jobs = {}
    api._build_pause_events = {}
    api._build_tasks = {}
    api._lightrag_registry = MagicMock()
    api._lightrag_registry.enabled = True
    api._source_store = source_store
    api._index_compatibility = None
    api._embedding_fingerprint = None

    async def _resolve_collection(col):
        return col or "papers"

    async def _lightrag_docs_for_build(col):
        return []

    api._resolve_collection = _resolve_collection
    api._lightrag_docs_for_build = _lightrag_docs_for_build
    return api


@pytest.mark.asyncio
async def test_concurrent_build_guard_raises_for_same_collection() -> None:
    """Second build_graph() call on the same collection raises RuntimeError."""
    api = _make_api()

    # Manually inject a running job for "papers"
    existing = BuildJob(job_id="existing", collection="papers")
    existing.status = "running"
    api._graph_build_jobs["existing"] = existing

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="papers"):
            await api.build_graph(collection="papers", confirmed=True)


@pytest.mark.asyncio
async def test_concurrent_build_guard_allows_different_collection() -> None:
    """build_graph() on a different collection succeeds even when another is running."""
    api = _make_api()

    existing = BuildJob(job_id="existing", collection="papers")
    existing.status = "running"
    api._graph_build_jobs["existing"] = existing

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock(return_value=None)):
        result = await api.build_graph(collection="books", confirmed=True)

    assert result["collection"] == "books"
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_concurrent_build_guard_allows_build_after_success() -> None:
    """A new build can be started once the previous one completed."""
    api = _make_api()

    done = BuildJob(job_id="done", collection="papers")
    done.status = "success"
    api._graph_build_jobs["done"] = done

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock(return_value=None)):
        result = await api.build_graph(collection="papers", confirmed=True)

    assert result["status"] == "queued"


# ─── CancelledError → interrupted status ──────────────────────


@pytest.mark.asyncio
async def test_cancelled_build_job_sets_status_interrupted() -> None:
    """If the build task is cancelled, job.status becomes 'interrupted'."""
    api = _make_api()

    interrupted_captured: list[str] = []

    async def _fake_build(job_id: str) -> None:
        job = api._graph_build_jobs[job_id]
        job.status = "running"
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            job.stage = "interrupted"
            job.status = "interrupted"
            raise

    with patch.object(api, "_run_lightrag_build_job", side_effect=_fake_build):
        result = await api.build_graph(collection="papers", confirmed=True)

    job_id = result["job_id"]
    # Give the task a moment to start
    await asyncio.sleep(0)

    # Cancel and wait
    task = api._build_tasks.get(job_id)
    assert task is not None, "build task handle must be saved"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    job = api._graph_build_jobs[job_id]
    assert job.status == "interrupted"


@pytest.mark.asyncio
async def test_cancel_build_tasks_clears_handles() -> None:
    """cancel_build_tasks() cancels all running tasks and clears _build_tasks."""
    api = _make_api()

    # Create a real long-running task and inject it
    async def _long():
        await asyncio.sleep(60)

    task = asyncio.create_task(_long())
    api._build_tasks["fake-job"] = task

    await api.cancel_build_tasks()

    assert len(api._build_tasks) == 0
    assert task.cancelled()
