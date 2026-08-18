"""AutoReindexScheduler 测试（纯内存假件驱动，不碰真 Milvus）。

调度器的价值全在「什么时候不跑」上：防抖合并连击、开关关闭不跑、空队列不跑、失败退避、
连续零进展后 park。因此本文件的多数用例都在断言**没有发生的事**。

时间控制：构造时注入极小的退避参数与亚秒防抖窗口，避免用例被拖成分钟级。
"""
from __future__ import annotations

import asyncio

import pytest

from kacore.auto_reindex import AutoReindexScheduler
from kacore.config import VectorDbConfig
from kacore.milvus_build import (
    MILVUS_BUILD_ERROR,
    MILVUS_BUILD_PARTIAL,
    MILVUS_BUILD_SUCCESS,
)

# 防抖窗口：短到用例秒级完成，长到足以在窗口内再打几次信号。
DEBOUNCE = 0.05


class FakeRebuild:
    """可编排的重建替身：记录调用次数，按脚本返回终态快照并扣减待重建队列。"""

    def __init__(
        self,
        *,
        pending: int = 1,
        snapshots: list[dict] | None = None,
        drains: bool = True,
    ) -> None:
        self.pending = pending
        self.calls = 0
        self._snapshots = snapshots or []
        self._drains = drains
        self.started = asyncio.Event()

    async def pending_count(self) -> int:
        return self.pending

    async def run(self) -> dict:
        self.calls += 1
        self.started.set()
        if self._snapshots:
            snapshot = self._snapshots[min(self.calls - 1, len(self._snapshots) - 1)]
        else:
            snapshot = {"status": MILVUS_BUILD_SUCCESS, "processed_docs": self.pending}
        if self._drains:
            self.pending = 0
        return snapshot


def _make_scheduler(
    fake: FakeRebuild,
    *,
    config: VectorDbConfig | None = None,
    is_ready: bool = True,
    max_failure_streak: int = 3,
) -> AutoReindexScheduler:
    cfg = config or VectorDbConfig(auto_rebuild_delay_seconds=DEBOUNCE)  # type: ignore[arg-type]
    return AutoReindexScheduler(
        pending_count=fake.pending_count,
        run_rebuild=fake.run,
        config_provider=lambda: cfg,
        is_ready=lambda: is_ready,
        retry_base_seconds=DEBOUNCE,
        retry_max_seconds=DEBOUNCE * 4,
        max_failure_streak=max_failure_streak,
    )


async def _run_briefly(scheduler: AutoReindexScheduler, seconds: float) -> None:
    """跑一小段调度循环后取消，模拟「插件运行了一会儿」。"""
    task = asyncio.create_task(scheduler.run())
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_notify_triggers_rebuild_after_debounce() -> None:
    fake = FakeRebuild(pending=3)
    scheduler = _make_scheduler(fake)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 4)

    assert fake.calls == 1
    assert fake.pending == 0


async def test_burst_of_notifies_collapses_into_single_rebuild() -> None:
    """Zotero 批量同步会为每篇文档打一次信号——防抖必须把连击合并成一次重建。"""
    fake = FakeRebuild(pending=5)
    scheduler = _make_scheduler(fake)

    task = asyncio.create_task(scheduler.run())
    for _ in range(5):
        scheduler.notify()
        await asyncio.sleep(DEBOUNCE / 3)  # 每次都在静默窗口内 → 窗口被不断延长
    await asyncio.sleep(DEBOUNCE * 4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.calls == 1


async def test_disabled_switch_never_rebuilds() -> None:
    fake = FakeRebuild(pending=3)
    scheduler = _make_scheduler(
        fake,
        config=VectorDbConfig(
            auto_rebuild_enabled=False,
            auto_rebuild_delay_seconds=DEBOUNCE,  # type: ignore[arg-type]
        ),
    )

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 4)

    assert fake.calls == 0
    assert fake.pending == 3


async def test_non_milvus_backend_never_rebuilds() -> None:
    fake = FakeRebuild(pending=3)
    scheduler = _make_scheduler(
        fake,
        config=VectorDbConfig(
            backend="astr",
            auto_rebuild_delay_seconds=DEBOUNCE,  # type: ignore[arg-type]
        ),
    )

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 4)

    assert fake.calls == 0


async def test_empty_queue_does_not_rebuild() -> None:
    """信号来了但队列已空（例如同步时就已同步入库）→ 不该白跑一次全量重建。"""
    fake = FakeRebuild(pending=0)
    scheduler = _make_scheduler(fake)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 4)

    assert fake.calls == 0


async def test_not_ready_backs_off_instead_of_spinning() -> None:
    """向量库没装配好时不能空转：一轮之后进入退避，而不是紧密重试。"""
    fake = FakeRebuild(pending=2)
    scheduler = _make_scheduler(fake, is_ready=False, max_failure_streak=99)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 6)

    assert fake.calls == 0
    assert not scheduler.parked  # streak 未到上限，仍会定时重试


async def test_failed_rebuild_retries_after_backoff() -> None:
    """首轮整体失败、次轮成功：退避到点后应自行重试，无需新的 notify。"""
    fake = FakeRebuild(
        pending=2,
        snapshots=[
            {"status": MILVUS_BUILD_ERROR, "processed_docs": 0, "recent_error": "boom"},
            {"status": MILVUS_BUILD_SUCCESS, "processed_docs": 2},
        ],
        drains=False,
    )
    scheduler = _make_scheduler(fake)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 12)

    assert fake.calls >= 2


async def test_partial_failure_with_progress_counts_as_progress() -> None:
    """partial_failure 但有文档成功入库 = 在推进：不该进退避，且应安排下一轮清剩余。"""
    fake = FakeRebuild(
        pending=5,
        snapshots=[{"status": MILVUS_BUILD_PARTIAL, "processed_docs": 3, "failed_docs": 2}],
        drains=False,
    )
    scheduler = _make_scheduler(fake)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 8)

    assert fake.calls >= 2
    assert not scheduler.parked


async def test_zero_progress_streak_parks_the_scheduler() -> None:
    """回归锁：一篇永远失败的坏文档会让队列永远非空。

    没有 park，就是「每小时一次全量重建」的无限重试风暴——这是本模块最重要的一条约束。
    """
    fake = FakeRebuild(
        pending=1,
        snapshots=[{"status": MILVUS_BUILD_PARTIAL, "processed_docs": 0, "failed_docs": 1}],
        drains=False,
    )
    scheduler = _make_scheduler(fake, max_failure_streak=3)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 30)

    assert scheduler.parked
    calls_at_park = fake.calls
    assert calls_at_park == 3  # 恰好在第 3 次零进展后停手，不再定时重试

    # park 后继续跑：没有新信号就一次都不再尝试。
    await _run_briefly(scheduler, DEBOUNCE * 10)
    assert fake.calls == calls_at_park


async def test_notify_unparks_and_resets_backoff() -> None:
    """park 之后来了新文档 → 新文档有独立的成功可能，必须唤醒并重置退避。"""
    fake = FakeRebuild(
        pending=1,
        snapshots=[{"status": MILVUS_BUILD_PARTIAL, "processed_docs": 0, "failed_docs": 1}],
        drains=False,
    )
    scheduler = _make_scheduler(fake, max_failure_streak=2)

    scheduler.notify()
    await _run_briefly(scheduler, DEBOUNCE * 20)
    assert scheduler.parked
    calls_at_park = fake.calls

    scheduler.notify()
    assert not scheduler.parked
    await _run_briefly(scheduler, DEBOUNCE * 4)
    assert fake.calls > calls_at_park


async def test_notify_during_rebuild_does_not_unpark() -> None:
    """重建会把失败文档重新标记为 needs_reindex，那也会打信号。

    若这种「自造信号」能重置失败计数，park 永远不会发生——这里钉死它不会。
    """
    fake = FakeRebuild(pending=1)
    scheduler = _make_scheduler(fake, max_failure_streak=2)
    scheduler._failure_streak = 2  # 已 park
    assert scheduler.parked

    scheduler._rebuilding = True
    scheduler.notify()
    assert scheduler.parked  # 重建期内的信号不解除 park

    scheduler._rebuilding = False
    scheduler.notify()
    assert not scheduler.parked
