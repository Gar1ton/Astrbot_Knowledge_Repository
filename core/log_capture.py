"""内存日志与运行事件捕获（横切工具，无业务依赖）。

将 Python logging 与前端运行事件存入同一个环形缓冲区，供 /api/logs 端点读取。
线程安全：使用 threading.Lock 保护 deque。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any


class MemoryLogHandler(logging.Handler):
    """将日志记录存入内存环形缓冲区。

    记录同时保留旧字段（ts/level/name/msg）与结构化字段
    （category/source/operation/status/metadata），便于 terminal 分类筛选。
    """

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)

    _SKIP_PREFIXES = (
        "aiohttp.access",
        "aiohttp.server",
        "aiohttp.web",
        "charset_normalizer",
        "httpx",
        "hpack",
        "httpcore",
        "urllib3",
        "asyncio",
    )

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(self._SKIP_PREFIXES):
            return
        try:
            msg = record.getMessage()
            if record.exc_info:
                import traceback
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        except Exception:
            msg = str(record.msg)
        self._append(
            _make_entry(
                ts=record.created,
                level=record.levelname,
                name=record.name,
                msg=msg,
                source="backend",
                category=_categorize(record.name, msg),
                operation=_operation(record.name, msg),
                status=_status_from_level(record.levelname),
                metadata={},
            )
        )

    def add_event(
        self,
        *,
        source: str,
        category: str,
        operation: str,
        status: str,
        msg: str,
        level: str = "INFO",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一个非 logging 来源的结构化运行事件。"""
        self._append(
            _make_entry(
                ts=time.time(),
                level=level,
                name=f"{source}.{category}",
                msg=msg,
                source=source,
                category=category,
                operation=operation,
                status=status,
                metadata=metadata or {},
            )
        )

    def _append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(entry)

    def get_lines(self, after_ts: float = 0.0, limit: int = 200) -> list[dict[str, Any]]:
        """返回 after_ts 之后的日志行，最多 limit 条（按时间升序）。"""
        with self._lock:
            records = list(self._records)
        filtered = [r for r in records if r["ts"] > after_ts]
        return filtered[-limit:]


def _make_entry(
    *,
    ts: float,
    level: str,
    name: str,
    msg: str,
    source: str,
    category: str,
    operation: str,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ts": ts,
        "level": level,
        "name": name,
        "msg": msg,
        "source": source,
        "category": category,
        "operation": operation,
        "status": status,
        "elapsed_ms": metadata.pop("elapsed_ms", None),
        "metadata": metadata,
    }


def _status_from_level(level: str) -> str:
    if level in {"ERROR", "CRITICAL"}:
        return "error"
    if level == "WARNING":
        return "warning"
    return "ok"


def _categorize(name: str, msg: str) -> str:
    text = f"{name} {msg}".lower()
    if "lightrag" in text or "graph" in text:
        return "graph"
    if "lmstudio" in text or "llm" in text:
        return "llm"
    if "embedding" in text:
        return "embedding"
    if "retrieval" in text or "vector_search" in text or "rrf" in text:
        return "retrieval"
    if name.startswith("KRWebServer") or "upload" in text or "api" in text:
        return "web"
    if "sync" in text or "backup" in text or "notion" in text:
        return "sync"
    if "dependency" in text or "system" in text or "memoryloghandler" in text:
        return "system"
    return "other"


def _operation(name: str, msg: str) -> str:
    text = msg.lower()
    if "ainsert" in text or "build" in text:
        return "build"
    if "aquery" in text or "query" in text:
        return "query"
    if "upload" in text:
        return "upload"
    if "delete" in text:
        return "delete"
    if "install" in text:
        return "install"
    return name.split(".")[-1] or "log"


def install(maxlen: int = 500) -> MemoryLogHandler:
    """安装 MemoryLogHandler 到 root logger 并返回句柄。

    幂等：若 root logger 上已有同类 handler 则直接返回已有实例。
    """
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, MemoryLogHandler):
            return h

    handler = MemoryLogHandler(maxlen=maxlen)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)

    logging.getLogger("log_capture").info("MemoryLogHandler installed (maxlen=%d)", maxlen)
    return handler


__all__ = ["MemoryLogHandler", "install"]
