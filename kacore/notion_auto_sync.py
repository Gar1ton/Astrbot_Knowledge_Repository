"""Notion 自动推送调度：观察已提交内容版本，合并变更，周期补偿并退避失败。

只消费 repository 的版本契约；不读取凭据，不写运行配置，不创建并行推送任务。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kacore.config import NotionSyncConfig
    from kacore.repository.source_store.base import SourceDocumentStore

logger = logging.getLogger("NotionAutoSync")


class NotionAutoSync:
    """push 返回 True=完成、False=失败、None=忙；忙时保留变更，失败至少退避。"""

    def __init__(
        self,
        store: SourceDocumentStore,
        config: Callable[[], NotionSyncConfig],
        push: Callable[[], Awaitable[bool | None]],
        *,
        debounce_sec: float = 10,
    ) -> None:
        self._store = store
        self._config = config
        self._push = push
        self._debounce = debounce_sec
        self._revision: str | None = None
        self._changed_at: float | None = None
        self._last_push: float | None = None
        self._retry_after = 0.0

    async def tick(self, now: float | None = None) -> None:
        """单次调度检查；可注入时间便于验证 debounce/周期补偿。"""
        now = time.monotonic() if now is None else now
        cfg = self._config()
        if not cfg.enabled or not cfg.auto_sync_enabled:
            return
        revision = await self._store.get_notion_local_revision()
        if self._revision is None:
            self._revision = revision
            self._last_push = now
        elif revision != self._revision:
            self._revision = revision
            self._changed_at = now
        interval = max(0, cfg.auto_sync_interval_sec)
        changed = self._changed_at is not None and now - self._changed_at >= self._debounce
        periodic = interval > 0 and now - (self._last_push or 0) >= interval
        if now < self._retry_after or not (changed or periodic):
            return
        try:
            accepted = await self._push()
        except Exception as exc:  # noqa: BLE001 — 重试由调度器统一退避
            logger.warning("Notion 自动同步失败：%s", exc)
            accepted = False
        if accepted is None:
            return
        self._last_push = now
        if accepted:
            self._changed_at = None
            self._retry_after = 0
        else:
            self._retry_after = now + (interval or 300)

    async def run(self) -> None:
        """常驻单任务；取消时向调用方传播，生命周期负责关闭它。"""
        while True:
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 — 本地版本读取失败不结束任务
                logger.warning("Notion 本地变更检测失败：%s", exc)
            await asyncio.sleep(1)
