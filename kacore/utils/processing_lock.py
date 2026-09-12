"""处理与索引互斥：只允许同一 asyncio Task 重入，子任务不会继承锁所有权。"""
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any


class ProcessingLock:
    """进程内串行化嵌套维护调用；取消等待者不影响持锁任务。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def __aenter__(self) -> ProcessingLock:
        task = asyncio.current_task()
        if self._owner is not task or task is None:
            await self._lock.acquire()
            self._owner = task
        self._depth += 1
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()


def serialized_processing(fn: Any) -> Any:
    """组件构造器注入同一 _processing_lock；不通过 ContextVar 传播所有权。"""
    @wraps(fn)
    async def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        async with self._processing_lock:
            return await fn(self, *args, **kwargs)
    return wrapped


async def complete_thread_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """文件写入下放线程；取消时等写入退出再释放维护锁，防止遗留线程覆盖下次重试。"""
    worker = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        if not worker.cancelled():
            worker.exception()  # 消费线程异常；持久 pending 标记负责后续恢复。
        raise asyncio.CancelledError()
    return worker.result()
