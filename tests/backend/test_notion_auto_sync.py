"""自动推送的时间与生命周期契约，无真实等待/服务调用。"""

from __future__ import annotations

import asyncio

import pytest

from kacore.config import NotionSyncConfig
from kacore.domain.models import Collection, NotionEntityRecord
from kacore.notion_auto_sync import NotionAutoSync
from kacore.repository.source_store.memory import InMemorySourceDocumentStore


async def test_coalesces_changes_and_ledger_writes_do_not_trigger() -> None:
    store = InMemorySourceDocumentStore()
    cfg = NotionSyncConfig(enabled=True)
    calls = []

    async def push() -> bool:
        calls.append(True)
        return True

    scheduler = NotionAutoSync(store, lambda: cfg, push)
    await scheduler.tick(0)
    await store.upsert_collection(Collection(name="first"))
    await scheduler.tick(1)
    await store.upsert_collection(Collection(name="second"))
    await scheduler.tick(7)
    await scheduler.tick(16)
    assert not calls
    await scheduler.tick(17)
    assert len(calls) == 1
    await store.upsert_notion_entity(NotionEntityRecord("document", "d1"))
    await scheduler.tick(18)
    await scheduler.tick(29)
    assert len(calls) == 1


async def test_interval_zero_keeps_event_sync_and_switch_disables_all() -> None:
    store = InMemorySourceDocumentStore()
    cfg = NotionSyncConfig(enabled=True, auto_sync_interval_sec=0)
    calls = []

    async def push() -> bool:
        calls.append(True)
        return True

    scheduler = NotionAutoSync(store, lambda: cfg, push)
    await scheduler.tick(0)
    await scheduler.tick(600)
    assert not calls
    await store.upsert_collection(Collection(name="change"))
    await scheduler.tick(601)
    await scheduler.tick(611)
    assert len(calls) == 1
    cfg.auto_sync_enabled = False
    await store.upsert_collection(Collection(name="disabled"))
    await scheduler.tick(1000)
    await scheduler.tick(1100)
    assert len(calls) == 1


async def test_busy_retries_without_losing_changes_and_failures_back_off() -> None:
    store = InMemorySourceDocumentStore()
    cfg = NotionSyncConfig(enabled=True)
    responses = [None, False, True]
    calls = []

    async def push() -> bool | None:
        calls.append(True)
        return responses.pop(0)

    scheduler = NotionAutoSync(store, lambda: cfg, push)
    await scheduler.tick(0)
    await store.upsert_collection(Collection(name="change"))
    await scheduler.tick(1)
    await scheduler.tick(11)  # busy
    await scheduler.tick(12)  # failure
    await scheduler.tick(100)
    assert len(calls) == 2
    await scheduler.tick(312)
    assert len(calls) == 3


async def test_periodic_catchup_runs_without_local_changes() -> None:
    store = InMemorySourceDocumentStore()
    cfg = NotionSyncConfig(enabled=True)
    calls = []

    async def push() -> bool:
        calls.append(True)
        return True

    scheduler = NotionAutoSync(store, lambda: cfg, push)
    await scheduler.tick(0)
    await scheduler.tick(299)
    assert not calls
    await scheduler.tick(300)
    assert len(calls) == 1


async def test_scheduler_cancellation_stops_pending_work() -> None:
    store = InMemorySourceDocumentStore()
    cfg = NotionSyncConfig(enabled=True)
    started = asyncio.Event()
    ended = asyncio.Event()

    async def push() -> bool:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()
        return True

    scheduler = NotionAutoSync(store, lambda: cfg, push, debounce_sec=0)
    await scheduler.tick(0)
    await store.upsert_collection(Collection(name="change"))
    task = asyncio.create_task(scheduler.run())
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended.is_set()
