"""内存日志捕获（横切工具，无业务依赖）。

将 Python logging 记录存入环形缓冲区，供 /api/logs 端点读取。
线程安全：使用 threading.Lock 保护 deque。
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any


class MemoryLogHandler(logging.Handler):
    """将日志记录存入内存环形缓冲区。

    maxlen=500 保留最近 500 条，足够终端页面展示历史且内存占用极低。
    """

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)

    # logger 名称前缀黑名单：框架/库内部日志，对业务调试无意义且产生噪声
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
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "name": record.name,
            "msg": msg,
        }
        with self._lock:
            self._records.append(entry)

    def get_lines(self, after_ts: float = 0.0, limit: int = 200) -> list[dict[str, Any]]:
        """返回 after_ts 之后的日志行，最多 limit 条（按时间升序）。"""
        with self._lock:
            records = list(self._records)
        filtered = [r for r in records if r["ts"] > after_ts]
        return filtered[-limit:]


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

    # 记录第一条安装日志（帮助前端确认 handler 已生效）
    logging.getLogger("log_capture").info("MemoryLogHandler installed (maxlen=%d)", maxlen)
    return handler


__all__ = ["MemoryLogHandler", "install"]
