"""Tests for LightRAG build hardening: concurrent guard and CancelledError handling."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kacore.lightrag_core import BuildJob

# ─── Concurrent build guard ────────────────────────────────────


class _FakeSourceStore:
    async def list_documents_for_collection(self, col: str):
        return []

    async def upsert_build_job(self, snapshot: dict):
        pass

    async def mark_interrupted_build_jobs(self) -> int:
        return 0

    async def replace_codex_graph_tasks(self, job_id: str, tasks: list[dict]) -> None:
        pass

    async def list_codex_graph_tasks(self, job_id: str, status: str | None = None) -> list[dict]:
        return []

    async def set_lightrag_index_status(
        self, doc_id: str, collection: str, status: str, error: str = "", *, job_id=None
    ) -> None:
        pass

    async def delete_lightrag_index_status_by_job(self, job_id: str) -> int:
        return 0


def _make_api():
    """Build a minimal KnowledgeRepositoryApi instance for testing build_graph()."""
    from kacore.api import KnowledgeRepositoryApi

    source_store = _FakeSourceStore()
    api = object.__new__(KnowledgeRepositoryApi)
    api._graph_build_jobs = {}
    api._build_pause_events = {}
    api._build_tasks = {}
    api._lightrag_registry = MagicMock()
    api._lightrag_registry.enabled = True
    api._lightrag_registry.probe_llm_ready = AsyncMock(return_value=None)
    api._source_store = source_store
    api._index_compatibility = None
    api._embedding_fingerprint = None
    # Phase 4（v1.0.11）：build_graph()/build_graph_with_codex() 启动前会做就绪度探针，
    # 默认给一套「一切正常」的假实现；需要测试探针失败的用例可自行覆盖这两个属性。
    api._embedding_provider = AsyncMock()
    api._embedding_provider.embed_query = AsyncMock(return_value=[0.1])
    api._llm_adapter = AsyncMock()
    api._llm_adapter.generate = AsyncMock(return_value="pong")

    from kacore.runtime_events import RuntimeEventRecorder

    api._runtime_events = RuntimeEventRecorder(None)

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


# ─── Preflight readiness probe (v1.0.11) ──────────────────────


@pytest.mark.asyncio
async def test_build_graph_rejects_when_embedding_provider_missing() -> None:
    """Embedding 未配置时同步拒绝，不创建任何 job。"""
    api = _make_api()
    api._embedding_provider = None

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="Embedding"):
            await api.build_graph(collection="papers", confirmed=True)

    assert api._graph_build_jobs == {}


@pytest.mark.asyncio
async def test_build_graph_rejects_when_embedding_probe_fails() -> None:
    """Embedding 探针调用失败（超时/异常）时同步拒绝，不创建任何 job。"""
    api = _make_api()
    api._embedding_provider.embed_query = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="Embedding"):
            await api.build_graph(collection="papers", confirmed=True)

    assert api._graph_build_jobs == {}


@pytest.mark.asyncio
async def test_build_graph_rejects_when_llm_probe_fails() -> None:
    """图谱构建 LLM 未就绪时同步拒绝，不创建任何 job——而不是启动后才在逐文档循环里失败。"""
    api = _make_api()
    api._lightrag_registry.probe_llm_ready = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(api, "_run_lightrag_build_job", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="LLM"):
            await api.build_graph(collection="papers", confirmed=True)

    assert api._graph_build_jobs == {}


@pytest.mark.asyncio
async def test_build_graph_with_codex_does_not_probe_llm() -> None:
    """Codex 构建路径走 insert_custom_kg 官方非 LLM 接口，不应探测图谱构建 LLM。"""
    api = _make_api()
    api._lightrag_registry.probe_llm_ready = AsyncMock(
        side_effect=AssertionError("Codex 路径不应探测 LLM")
    )
    api._config = None
    api._index_compatibility = None

    async def _lightrag_text_for_doc(doc):
        return ""

    api._lightrag_text_for_doc = _lightrag_text_for_doc

    result = await api.build_graph_with_codex(collection="papers", confirmed=True)

    assert result["status"] == "success"  # 无文档，直接完成


@pytest.mark.asyncio
async def test_build_graph_with_codex_still_rejects_when_embedding_missing() -> None:
    """Codex 路径仍需要 Embedding 就绪（后续 entity/relationship 写入依赖它）。"""
    api = _make_api()
    api._embedding_provider = None

    with pytest.raises(RuntimeError, match="Embedding"):
        await api.build_graph_with_codex(collection="papers", confirmed=True)

    assert api._graph_build_jobs == {}


# ─── Circuit breaker on consecutive per-doc failures (v1.0.11) ─


@pytest.mark.asyncio
async def test_circuit_breaker_stops_after_consecutive_failures() -> None:
    """连续失败达阈值后提前终止，不把剩余文档全部跑坏才暴露问题。"""
    from kacore.domain.models import SourceDocument

    api = _make_api()

    docs = [
        SourceDocument(
            doc_id=f"d{i}",
            title=f"d{i}",
            file_path=f"/tmp/d{i}.md",
            content_type="text/markdown",
            size_bytes=1,
            content_hash=f"h{i}",
            collection="papers",
        )
        for i in range(6)
    ]

    async def _lightrag_docs_for_build(col):
        return docs

    async def _lightrag_text_for_doc(doc):
        return f"text for {doc.doc_id}"

    class Registry:
        enabled = True
        calls: list[str] = []

        def has_workspace(self, collection: str) -> bool:
            return False

        async def chunk_document(self, collection: str, text: str):
            return [text], "lrag_chunks"

        async def insert_document(self, collection, doc_id, text, **kwargs):
            Registry.calls.append(doc_id)
            raise RuntimeError("provider unreachable")

    api._lightrag_docs_for_build = _lightrag_docs_for_build
    api._lightrag_text_for_doc = _lightrag_text_for_doc
    api._lightrag_registry = Registry()
    api._config = None
    api._index_compatibility = None
    api._embedding_fingerprint = None

    job_id = "job-1"
    job = BuildJob(job_id=job_id, collection="papers", total_docs=len(docs))
    api._graph_build_jobs[job_id] = job
    event = asyncio.Event()
    event.set()
    api._build_pause_events[job_id] = event

    await api._run_lightrag_build_job(job_id)

    # 阈值为 3：应在第 3 篇失败后提前终止，未跑完全部 6 篇。
    assert len(Registry.calls) == 3
    assert job.failed_docs == 3
    assert job.processed_docs == 0
    assert job.status == "error"
    assert "连续" in job.recent_error


# ─── cancel_build_job (v1.0.11) ────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_build_job_signals_task_and_marks_cancelled() -> None:
    """取消一个正在跑的任务：任务被信号取消，最终落盘状态为 cancelled（不是 interrupted）。"""
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
    await asyncio.sleep(0)

    cancel_result = await api.cancel_build_job(job_id)

    assert cancel_result["job_id"] == job_id
    assert cancel_result["status"] == "cancelled"
    assert cancel_result["cleanup"]["active_state_removed"] is True
    job = api._graph_build_jobs[job_id]
    assert job.status == "cancelled"
    assert job_id not in api._build_tasks
    assert job_id not in api._build_pause_events


@pytest.mark.asyncio
async def test_cancel_build_job_is_idempotent() -> None:
    """对已取消的 job 再次调用 cancel：不报错，返回全零清理计数。"""
    api = _make_api()
    job = BuildJob(job_id="job-1", collection="papers", status="running")
    api._graph_build_jobs["job-1"] = job

    async def _long() -> None:
        await asyncio.sleep(60)

    api._build_tasks["job-1"] = asyncio.create_task(_long())

    first = await api.cancel_build_job("job-1")
    second = await api.cancel_build_job("job-1")

    assert first["status"] == "cancelled"
    assert second["status"] == "cancelled"
    assert second["cleanup"]["index_status_rows"] == 0
    assert second["cleanup"]["codex_tasks"] == 0


@pytest.mark.asyncio
async def test_cancel_build_job_unknown_id_raises_keyerror() -> None:
    api = _make_api()

    with pytest.raises(KeyError):
        await api.cancel_build_job("does-not-exist")


@pytest.mark.asyncio
async def test_cancel_build_job_rejects_already_terminal_non_cancelled_job() -> None:
    """取消一个已经成功完成的任务应报错，不能把 success 回退为 cancelled。"""
    api = _make_api()
    job = BuildJob(job_id="job-done", collection="papers", status="success")
    api._graph_build_jobs["job-done"] = job

    with pytest.raises(ValueError, match="already finished"):
        await api.cancel_build_job("job-done")


@pytest.mark.asyncio
async def test_cancel_build_job_removes_job_scoped_artifacts_only() -> None:
    """取消 job A 只删 A 写入的 lightrag_index_status/codex_graph_tasks 行，B 的不受影响。

    这是本 Phase 最核心的正确性断言：取消一个任务绝不能牵连另一个任务/另一次构建轮次
    的记录，更不能触碰文档本身。
    """
    from kacore.api import KnowledgeRepositoryApi
    from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from kacore.repository.source_store.memory import InMemorySourceDocumentStore

    store = InMemorySourceDocumentStore()
    api = KnowledgeRepositoryApi(
        source_store=store,
        kb_reader=InMemoryKnowledgeBaseReader({}),
        lightrag_registry=MagicMock(),  # type: ignore[arg-type]
    )

    await store.set_lightrag_index_status("doc-a", "papers", "indexed", job_id="job-A")
    await store.set_lightrag_index_status("doc-b", "papers", "indexed", job_id="job-B")
    await store.replace_codex_graph_tasks(
        "job-A",
        [
            {
                "task_id": "t-a1",
                "job_id": "job-A",
                "collection": "papers",
                "doc_id": "doc-a",
                "chunk_index": 0,
                "chunk_hash": "h1",
                "content": "c1",
            }
        ],
    )
    await store.replace_codex_graph_tasks(
        "job-B",
        [
            {
                "task_id": "t-b1",
                "job_id": "job-B",
                "collection": "papers",
                "doc_id": "doc-b",
                "chunk_index": 0,
                "chunk_hash": "h2",
                "content": "c2",
            }
        ],
    )
    api._graph_build_jobs["job-A"] = BuildJob(job_id="job-A", collection="papers", status="running")
    api._graph_build_jobs["job-B"] = BuildJob(job_id="job-B", collection="papers", status="running")

    result = await api.cancel_build_job("job-A")

    assert result["cleanup"]["index_status_rows"] == 1
    assert result["cleanup"]["codex_tasks"] == 1
    assert await store.get_lightrag_index_status("doc-a") is None
    assert (await store.get_lightrag_index_status("doc-b"))["job_id"] == "job-B"
    assert await store.list_codex_graph_tasks("job-A") == []
    assert len(await store.list_codex_graph_tasks("job-B")) == 1
    # job-B 自身的任务记录（BuildJob）完全未被本次取消触碰。
    assert api._graph_build_jobs["job-B"].status == "running"


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
    from kacore.repository.source_store.memory import InMemorySourceDocumentStore

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
    from kacore.api import KnowledgeRepositoryApi
    from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from kacore.repository.source_store.memory import InMemorySourceDocumentStore

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
    from kacore.api import KnowledgeRepositoryApi
    from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from kacore.repository.source_store.memory import InMemorySourceDocumentStore

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
    from kacore.api import KnowledgeRepositoryApi
    from kacore.domain.models import DocumentChunk, SourceDocument
    from kacore.index_compatibility import IndexCompatibilityStore
    from kacore.repository.kb_reader.memory import InMemoryKnowledgeBaseReader
    from kacore.repository.source_store.memory import InMemorySourceDocumentStore

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
