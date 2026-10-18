"""Milvus 索引自动重建调度器（后台循环，无 I/O、无框架依赖）。

为什么存在：自动索引本来就有，但它被兼容门挡着——`api.register_document()` 与
`api._index_document()` 只在 `_milvus_index_is_compatible()` 为真时才同步写 Milvus，否则把文档
落进 `needs_reindex` 队列。而兼容态一旦坏掉（换 embedding / collection 被重建 / schema 不匹配），
**只有跑完一次重建才会翻回来**，于是其后进来的每一个新文件都只是排队，全项目没有任何东西会主动
排空该队列——只有 WebUI 那个「重建索引」按钮。本模块就是那个「自己按按钮的人」。

它**不含任何索引逻辑**：只调用注入进来的 `run_rebuild`（组合根接的是 `api` 的单飞重建入口），
因此自动重建与手动点按钮走同一个 job、同一条进度条、同一套 runtime events。

设计要点：
- **防抖**：Zotero 批量同步会为每篇文档打一次信号，静默期内不断有新信号就继续等，只在批次
  安静下来后跑一次，而不是跑一百次。
- **退避 + park**：失败按指数退避；连续 `MAX_FAILURE_STREAK` 次「零进展」后进入 park——只等新
  信号，不再定时重试。一篇永远清洗失败的坏 PDF 会让队列永远非空，没有 park 就是无限重试风暴。
- **重建期内的信号不解除 park**：重建自身会把失败文档重新标记为 `needs_reindex`，那也会经
  `notify()` 打信号；若它能重置失败计数，park 永远不会发生。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from kacore.milvus_build import MILVUS_BUILD_SUCCESS

if TYPE_CHECKING:
    from kacore.config import VectorDbConfig

logger = logging.getLogger("AutoReindexScheduler")

# 退避参数：首次失败等 60s，逐次翻倍，封顶 1 小时。
RETRY_BASE_SECONDS: float = 60.0
RETRY_MAX_SECONDS: float = 3600.0
# 连续多少次「零进展」后 park（只等新信号，不再定时重试）。
MAX_FAILURE_STREAK: int = 6


class AutoReindexScheduler:
    """把「排空 `needs_reindex` 队列」变成后台自动行为的调度循环。

    契约：
    - `notify()` 是**同步**方法，可在任意上下文调用；它只打信号，从不抛错、从不阻塞。
    - `run()` 是长驻协程，由组合根 `create_task` 持有，`CancelledError` 时干净退出；
      其余异常一律吞掉记日志——调度器不得因单次重建失败而死掉。
    - 每轮循环都**重读配置**，因此 `auto_rebuild_enabled` / `auto_rebuild_delay_seconds`
      改完即生效，无需重启插件。
    - 单飞由 `run_rebuild` 自身保证（组合根接的 `api.start_milvus_rebuild` 已是全局单飞），
      本类不再加锁：手动重建正在跑时，自动重建会自然复用同一个 job。
    """

    def __init__(
        self,
        *,
        pending_count: Callable[[], Awaitable[int]],
        run_rebuild: Callable[[], Awaitable[dict[str, Any]]],
        config_provider: Callable[[], VectorDbConfig],
        is_ready: Callable[[], bool],
        retry_base_seconds: float = RETRY_BASE_SECONDS,
        retry_max_seconds: float = RETRY_MAX_SECONDS,
        max_failure_streak: int = MAX_FAILURE_STREAK,
    ) -> None:
        self._pending_count = pending_count
        self._run_rebuild = run_rebuild
        self._config_provider = config_provider
        self._is_ready = is_ready
        # 退避参数可注入：生产用模块常量，测试注入极小值以免把用例拖成分钟级。
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._max_failure_streak = max_failure_streak
        self._signal = asyncio.Event()
        self._failure_streak = 0
        self._retry_after = 0.0
        self._rebuilding = False

    # ── 对外信号 ──────────────────────────────────────────────────

    def notify(self) -> None:
        """有文档被标记为待重建 —— 打一次信号（幂等，防抖窗口会把连击合并成一次）。"""
        if not self._rebuilding:
            # 重建期内的标记来自重建自身的失败文档，不该被当作「新希望」解除 park。
            self._failure_streak = 0
            self._retry_after = 0.0
        self._signal.set()

    @property
    def parked(self) -> bool:
        """连续零进展达到上限后为真：不再定时重试，只等下一次 `notify()`。"""
        return self._failure_streak >= self._max_failure_streak

    # ── 主循环 ───────────────────────────────────────────────────

    async def run(self) -> None:
        """长驻循环：等信号 → 防抖 → 门禁 → 重建 → 判成败。"""
        logger.info("Milvus 索引自动重建调度器已启动。")
        try:
            while True:
                await self._wait_for_trigger()
                await self._debounce()
                try:
                    await self._maybe_rebuild()
                except Exception as exc:  # noqa: BLE001 - 单轮失败不得打崩调度循环
                    logger.error("自动重建轮次异常：%s", exc, exc_info=True)
                    self._note_failure(str(exc))
        except asyncio.CancelledError:
            logger.info("Milvus 索引自动重建调度器已取消。")
            raise

    async def _wait_for_trigger(self) -> None:
        """等待下一次触发：退避期内睡满退避（信号不打断），否则等信号。

        退避期「信号不打断」是刻意的：重建失败时会把失败文档重新标记，那本身就会打信号，
        若信号能打断退避，失败就会变成紧密重试。
        """
        remaining = self._retry_after - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)
            return
        await self._signal.wait()

    async def _debounce(self) -> None:
        """静默窗口：期间只要还有新信号就继续等，直到安静下来才返回。

        下限只兜到 0（生产值由 `Config.get_vector_db_config()` 夹到 ≥5 秒）——这里再夹一次
        会让测试无法注入亚秒窗口。
        """
        delay = max(0.0, float(self._config_provider().auto_rebuild_delay_seconds))
        while True:
            self._signal.clear()
            await asyncio.sleep(delay)
            if not self._signal.is_set():
                return

    async def _maybe_rebuild(self) -> None:
        """门禁 → 查队列 → 跑一次重建 → 按「有无进展」判定成败。"""
        cfg = self._config_provider()
        if not cfg.auto_rebuild_enabled or cfg.backend != "milvus":
            return
        if not self._is_ready():
            # 向量库/embedding 尚未装配：退避重试而不是空转（等用户修配置或重启）。
            self._note_failure("vector store or embedding provider is not ready")
            return

        pending = await self._pending_count()
        if pending <= 0:
            self._note_success()
            return

        logger.info("自动重建触发：%d 个文档待重建。", pending)
        self._rebuilding = True
        try:
            snapshot = await self._run_rebuild()
        finally:
            self._rebuilding = False

        status = str(snapshot.get("status") or "")
        processed = int(snapshot.get("processed_docs") or 0)
        # 判「有无进展」而非只看 status：partial_failure 里只要有文档成功入库就是在推进，
        # 值得下一轮继续；一篇都没成功才算真失败，进退避。
        if status == MILVUS_BUILD_SUCCESS or processed > 0:
            self._note_success()
            remaining = await self._pending_count()
            if remaining > 0:
                logger.info("自动重建仍余 %d 个待重建文档，安排下一轮。", remaining)
                self._signal.set()
            return

        self._note_failure(str(snapshot.get("recent_error") or status or "unknown error"))

    # ── 退避状态 ─────────────────────────────────────────────────

    def _note_success(self) -> None:
        self._failure_streak = 0
        self._retry_after = 0.0

    def _note_failure(self, reason: str) -> None:
        self._failure_streak += 1
        if self.parked:
            self._retry_after = 0.0
            logger.error(
                "自动重建连续 %d 次零进展，暂停定时重试（等待新文档或手动重建）。最近原因：%s",
                self._failure_streak,
                reason,
            )
            return
        delay = min(self._retry_max, self._retry_base * (2 ** (self._failure_streak - 1)))
        self._retry_after = time.monotonic() + delay
        logger.warning(
            "自动重建未取得进展（第 %d 次），%.0fs 后重试。原因：%s",
            self._failure_streak,
            delay,
            reason,
        )


__all__ = [
    "AutoReindexScheduler",
    "MAX_FAILURE_STREAK",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_SECONDS",
]
