"""Tests for LightRAG build hardening: concurrent guard and CancelledError handling."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
async def test_concurrent_build_guard_blocks_different_collection() -> None:
    """Any active build blocks new builds because LightRAG uses a linear queue."""
    api = _make_api()

    existing = BuildJob(job_id="existing", collection="papers")
    existing.status = "running"
    api._graph_build_jobs["existing"] = existing

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="papers"):
            await api.build_graph(collection="books", confirmed=True)


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


# ─── Pause / resume persistence ───────────────────────────────────────────────


def _job_snapshot(job_id: str, status: str, collection: str = "papers") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "job_id": job_id,
        "collection": collection,
        "status": status,
        "stage": status,
        "processed_docs": 0,
        "failed_docs": 0,
        "total_docs": 1,
        "processed_chunks": 0,
        "failed_chunks": 0,
        "total_chunks": 1,
        "recent_error": "",
        "started_at": (now - timedelta(seconds=30)).isoformat(timespec="seconds"),
        "finished_at": None,
        "pause_requested": status == "pause_requested",
        "paused_at": now.isoformat(timespec="seconds") if status == "paused" else None,
        "paused_seconds": 0,
        "progress_current": 0,
        "progress_total": 2,
    }


@pytest.mark.asyncio
async def test_mark_interrupted_preserves_paused_jobs() -> None:
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    store = InMemorySourceDocumentStore()
    for status in ["queued", "running", "pause_requested", "paused", "success"]:
        await store.upsert_build_job(_job_snapshot(f"job-{status}", status))

    changed = await store.mark_interrupted_build_jobs()
    jobs = {job["job_id"]: job for job in await store.list_build_jobs(limit=10)}

    assert changed == 3
    assert jobs["job-paused"]["status"] == "paused"
    assert jobs["job-success"]["status"] == "success"
    assert jobs["job-queued"]["status"] == "interrupted"
    assert jobs["job-running"]["status"] == "interrupted"
    assert jobs["job-pause_requested"]["status"] == "interrupted"
    resumable = await store.get_latest_resumable_build_job()
    assert resumable and resumable["job_id"] == "job-paused"


@pytest.mark.asyncio
async def test_pause_requested_is_persisted_while_llm_call_is_running() -> None:
    from core.api import KnowledgeRepositoryApi
    from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    store = InMemorySourceDocumentStore()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=MagicMock(),  # type: ignore[arg-type]
    )
    job = BuildJob(job_id="job", collection="papers", status="running")
    job.in_llm_call = True
    api._graph_build_jobs[job.job_id] = job
    event = asyncio.Event()
    event.set()
    api._build_pause_events[job.job_id] = event

    await api.pause_build_job("job")

    assert job.status == "pause_requested"
    assert job.pause_requested is True
    assert not event.is_set()
    active = await api.get_active_build_job()
    assert active and active["pause_requested"] is True
    history = await store.list_build_jobs()
    assert history[0]["status"] == "pause_requested"
    assert history[0]["pause_requested"] is True


@pytest.mark.asyncio
async def test_pause_gate_enters_paused_and_resume_accumulates_seconds() -> None:
    from core.api import KnowledgeRepositoryApi
    from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    api = KnowledgeRepositoryApi(
        source_store=InMemorySourceDocumentStore(),
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=MagicMock(),  # type: ignore[arg-type]
    )
    job = BuildJob(job_id="job", collection="papers", status="running")
    job.pause_requested = True
    api._graph_build_jobs[job.job_id] = job
    event = asyncio.Event()
    event.set()
    api._build_pause_events[job.job_id] = event

    gate_task = asyncio.create_task(api._build_pause_gate(job, "before_document"))
    api._build_tasks[job.job_id] = gate_task
    await asyncio.sleep(0)

    assert job.status == "paused"
    assert job.paused is True
    assert not gate_task.done()
    elapsed = job.to_dict()["elapsed_seconds"]
    await asyncio.sleep(0.02)
    assert job.to_dict()["elapsed_seconds"] == elapsed

    await api.resume_build_job("job")
    await asyncio.wait_for(gate_task, timeout=1)

    assert job.status == "running"
    assert job.paused is False
    assert job.paused_seconds > 0


@pytest.mark.asyncio
async def test_restore_paused_job_resumes_same_job_id_and_only_pending_docs(tmp_path) -> None:
    from core.api import KnowledgeRepositoryApi
    from core.domain.models import DocumentChunk, SourceDocument
    from core.index_compatibility import IndexCompatibilityStore
    from core.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from core.repository.source_store.memory import InMemorySourceDocumentStore

    inserted: list[str] = []

    class Registry:
        def has_workspace(self, collection: str) -> bool:
            return True

        async def insert_document(
            self,
            collection: str,
            doc_id: str,
            text: str,
            *,
            lrag_chunks=None,
            progress_callback=None,
            pause_gate=None,
        ) -> None:
            inserted.append(doc_id)
            if progress_callback:
                progress_callback({"status": "start"})
                progress_callback({"status": "ok"})

    def doc(doc_id: str) -> SourceDocument:
        return SourceDocument(
            doc_id=doc_id,
            title=doc_id,
            file_path=f"/tmp/{doc_id}.md",
            content_type="text/markdown",
            size_bytes=1,
            content_hash=doc_id,
            collection="papers",
        )

    store = InMemorySourceDocumentStore()
    for doc_id, status in [("d1", "indexed"), ("d2", "pending")]:
        await store.add_document(doc(doc_id))
        await store.replace_chunks(
            doc_id,
            [DocumentChunk(f"chunk-{doc_id}", doc_id, 0, f"text {doc_id}", f"h-{doc_id}")],
        )
        await store.set_lightrag_index_status(doc_id, "papers", status)
    snapshot = _job_snapshot("paused-job", "paused")
    snapshot.update(
        {"processed_docs": 1, "total_docs": 2, "processed_chunks": 1, "total_chunks": 2}
    )
    await store.upsert_build_job(snapshot)

    compatibility = IndexCompatibilityStore(tmp_path / "compat.json")
    compatibility.mark_lightrag_compatible("papers", "fp")
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=Registry(),  # type: ignore[arg-type]
        index_compatibility=compatibility,
        embedding_fingerprint="fp",
    )

    await api.restore_paused_build_job()
    active = await api.get_active_build_job()
    assert active and active["job_id"] == "paused-job" and active["status"] == "paused"

    await api.resume_build_job("paused-job")
    task = api._build_tasks["paused-job"]
    await asyncio.wait_for(task, timeout=1)

    assert inserted == ["d2"]
    job = api._graph_build_jobs["paused-job"]
    assert job.status == "success"
    assert job.job_id == "paused-job"
    history = await store.list_build_jobs()
    assert history[0]["job_id"] == "paused-job"
    assert history[0]["status"] == "success"


def test_progress_does_not_reach_100_before_finalize() -> None:
    api = _make_api()
    job = BuildJob(
        job_id="job",
        collection="papers",
        status="running",
        stage="finalizing",
        processed_docs=1,
        total_docs=1,
        processed_chunks=6,
        total_chunks=6,
    )

    api._refresh_build_progress(job, label="finalizing")
    assert job.to_dict()["progress_percent"] < 100

    job.status = "success"
    api._refresh_build_progress(job, label="done")
    assert job.to_dict()["progress_percent"] == 100
